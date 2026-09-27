import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from core.memory.character import extract_document, recall_character_memories
from core.chat.context import build_context
from core.rag.embedding import KeywordEmbeddingProvider, MockEmbeddingProvider, build_embedding_provider
from core.rag.retrieval import retrieve
from infrastructure.config import settings
from infrastructure.database import CharacterMemory, CharacterExtraction, Document, DocumentChunk, Conversation, Memory, SessionLocal, engine


def document_fixture(agent_id=None, model="keyword-v1", dim=0):
    with SessionLocal() as session:
        doc = Document(original_filename="角色故事.txt", stored_filename="fixture.txt", mime_type="text/plain",
            file_type=".txt", size_bytes=100, content_hash="fixture", status="indexed", chunk_count=2,
            embedding_model=model, embedding_dim=dim, agent_id=agent_id)
        session.add(doc); session.flush()
        chunks = []
        for index, content in enumerate(["第1集，小岚在钟楼救下同伴，重视承诺。", "第2集，小岚来到海港寻找老师。"]):
            chunk = DocumentChunk(document_id=doc.id, chunk_index=index, content=content,
                section=f"第{index + 1}集", embedding=[1.0] * dim)
            session.add(chunk); session.flush(); chunks.append(chunk.id)
        session.commit()
        return doc.id, chunks


class ExtractProvider:
    def __init__(self, invalid=False):
        self.calls = []
        self.invalid = invalid
        self.closed = False

    async def complete(self, messages, temperature=0):
        source = json.loads(messages[-1]["content"])["source"]
        self.calls.append(source)
        return json.dumps({"memories": [{"content": source, "source_quote": "不存在的引用" if self.invalid else source,
            "time_label": "童年", "kind": "experience"}]}, ensure_ascii=False)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_extraction_processes_all_chunks_preserves_sources_and_drafts():
    doc_id, chunks = document_fixture("role-a")
    with SessionLocal() as session:
        job = CharacterExtraction(agent_id="role-a", document_id=doc_id)
        session.add(job); session.commit(); job_id = job.id
    provider = ExtractProvider()
    await extract_document(job_id, "小岚", provider, 6000)
    assert len(provider.calls) == 2 and provider.closed
    with SessionLocal() as session:
        assert session.get(CharacterExtraction, job_id).status == "completed"
        rows = session.query(CharacterMemory).all()
        assert len(rows) == 2
        assert {row.chunk_id for row in rows} == set(chunks)
        assert all(row.status == "draft" and row.source_quote in provider.calls for row in rows)
        assert recall_character_memories(session, "role-a", "钟楼") == []
        # 重试不得生成同内容的第二套草稿。
        second = CharacterExtraction(agent_id="role-a", document_id=doc_id)
        session.add(second); session.commit(); second_id = second.id
    await extract_document(second_id, "小岚", ExtractProvider(), 6000)
    with SessionLocal() as session:
        assert session.query(CharacterMemory).count() == 2


@pytest.mark.asyncio
async def test_invalid_source_quotes_do_not_enter_library():
    doc_id, _ = document_fixture()
    with SessionLocal() as session:
        job = CharacterExtraction(agent_id="a", document_id=doc_id)
        session.add(job); session.commit(); job_id = job.id
    await extract_document(job_id, "小岚", ExtractProvider(invalid=True), 6000)
    with SessionLocal() as session:
        assert session.query(CharacterMemory).count() == 0
        assert session.get(CharacterExtraction, job_id).rejected == 2


def test_recall_enforces_role_status_and_knowledge_before_core():
    with SessionLocal() as session:
        for agent, status, known, content in [
            ("a", "active", True, "小岚重视承诺"), ("b", "active", True, "其他角色秘密"),
            ("a", "draft", True, "未确认草稿"), ("a", "disabled", True, "停用"),
            ("a", "active", False, "角色不知情"),
        ]:
            session.add(CharacterMemory(agent_id=agent, status=status, known_to_character=known, content=content, is_core=True))
        session.commit()
        result = recall_character_memories(session, "a", "你好", KeywordEmbeddingProvider())
        assert [row.content for row in result] == ["小岚重视承诺"]


def test_character_context_is_bounded_and_separate_from_user_memories():
    with SessionLocal() as session:
        conversation = Conversation(agent_id="a")
        session.add(conversation)
        session.add(CharacterMemory(agent_id="a", content="小岚曾救下同伴", status="active", is_core=True))
        session.add(CharacterMemory(agent_id="b", content="另一角色的秘密", status="active", is_core=True))
        session.commit()
        context = build_context(session, "你是小岚", conversation.id, "你好", 3000, 5, embedding_provider=KeywordEmbeddingProvider())
        assert "小岚曾救下同伴" in context.system
        assert "另一角色" not in context.system
        assert context.character_memory_ids and not context.memory_ids
        assert sum(context.token_breakdown.values()) == context.token_estimate <= 3000


def test_keyword_retrieval_survives_model_mismatch_and_semantic_error():
    doc_id, _ = document_fixture(model="old-model", dim=2)
    class BrokenProvider:
        dimension = 2
        model_name = "new-model"
        def embed_query(self, query):
            raise RuntimeError("offline")
    with SessionLocal() as session:
        assert retrieve(session, KeywordEmbeddingProvider(), "钟楼", settings)[0].document_id == doc_id
        assert retrieve(session, BrokenProvider(), "钟楼", settings)[0].document_id == doc_id
        assert retrieve(session, KeywordEmbeddingProvider(), "总结一下", settings, document_ids=[doc_id])


def test_raw_role_documents_do_not_bypass_knowledge_boundary():
    doc_id, chunks = document_fixture("a")
    with SessionLocal() as session:
        session.add(CharacterMemory(agent_id="a", document_id=doc_id, chunk_id=chunks[0],
            content="钟楼", status="active", known_to_character=True))
        session.commit()
        assert not retrieve(session, KeywordEmbeddingProvider(), "钟楼", settings, agent_id="b")
        assert retrieve(session, KeywordEmbeddingProvider(), "钟楼", settings, agent_id="a", document_ids=[doc_id])
        assert not retrieve(session, KeywordEmbeddingProvider(), "钟楼", settings, agent_id="a")


def test_review_cannot_cross_roles_or_forge_evidence(client):
    with SessionLocal() as session:
        row = CharacterMemory(agent_id="default", content="重视承诺", source_quote="原文", status="draft")
        session.add(row); session.commit(); memory_id = row.id
    endpoint = f"/api/characters/default/memories/{memory_id}"
    assert client.patch(endpoint, json={"content": "重视承诺", "source_quote": "伪造", "status": "active"}).status_code == 422
    response = client.patch(endpoint, json={"content": "重视承诺", "source_quote": "原文", "status": "active", "is_core": True})
    assert response.status_code == 200 and response.json()["status"] == "active"
    assert client.patch(endpoint.replace("/default/", "/missing/"), json={"content": "x"}).status_code == 404


def test_settings_status_never_returns_key_and_online_requires_explicit_key_for_new_host(client):
    from apps.api.retrieval_settings import RetrievalBody, values_for
    from fastapi import HTTPException
    client.app.state.runtime_settings_store.update("embedding", {"embedding_api_key": "private-secret", "embedding_base_url": "https://one.invalid/v1"})
    response = client.get("/api/settings/retrieval")
    assert response.status_code == 200 and "private-secret" not in response.text
    assert response.json()["has_api_key"]
    with pytest.raises(HTTPException):
        values_for(RetrievalBody(provider="openai-compatible", model="text-embedding-3-small", base_url="https://two.invalid/v1"), client.app.state.runtime_settings_store.snapshot()["embedding"])


def test_missing_local_model_boots_in_keyword_mode(monkeypatch):
    import core.rag.embedding as embedding
    monkeypatch.setattr(embedding, "FastEmbeddingProvider", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    result = build_embedding_provider(SimpleNamespace(embedding_provider="fastembed", embedding_model=embedding.DEFAULT_LOCAL_MODEL))
    assert result.dimension == 0 and result.embed_documents(["中文"]) == [[]]


def test_rebuild_failure_preserves_previous_vectors_settings_and_ids(client):
    from apps.api.retrieval_settings import rebuild
    doc_id, chunks = document_fixture(model="old-model", dim=2)
    provider = MockEmbeddingProvider(3)
    store = client.app.state.runtime_settings_store
    previous = store.snapshot()["embedding"]
    values = {**previous, "embedding_model": "new-model"}
    class Broken:
        dimension = 3
        model_name = "new-model"
        def embed_documents(self, texts):
            raise RuntimeError("failed")
    with pytest.raises(RuntimeError):
        rebuild(Broken(), values, store, {})
    with SessionLocal() as session:
        assert session.get(Document, doc_id).embedding_model == "old-model"
        assert session.get(DocumentChunk, chunks[0]).embedding == [1.0, 1.0]
    assert store.snapshot()["embedding"] == previous
    rebuild(provider, values, store, {})
    with SessionLocal() as session:
        assert session.get(DocumentChunk, chunks[0]) is not None
        assert len(session.get(DocumentChunk, chunks[0]).embedding) == 3
        assert session.get(Document, doc_id).embedding_dim == 3


def test_model_change_blocks_active_requests_and_maintains_auth(client):
    client.app.state.retrieval_requests = 1
    assert client.post("/api/settings/retrieval", json={"provider": "keyword"}).status_code == 409
    client.app.state.retrieval_requests = 0
    client.app.state.retrieval_maintenance = True
    assert client.get("/api/documents").status_code == 503
    assert client.get("/api/settings/retrieval").status_code == 200
    client.app.state.retrieval_maintenance = False


def test_online_small_model_dimensions_and_nonfinite_validation():
    import httpx
    from core.rag.embedding import OpenAICompatibleEmbeddingProvider
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1., 0., 0.]}]})
    provider = OpenAICompatibleEmbeddingProvider("https://test.invalid/v1", "secret", "text-embedding-3-small", 3, "", request_dimensions=True)
    provider._client.close()
    provider._client = httpx.Client(base_url="https://test.invalid/v1", transport=httpx.MockTransport(handler))
    try:
        assert provider.embed_query("承诺") == [1., 0., 0.]
        assert captured[0]["dimensions"] == 3 and captured[0]["encoding_format"] == "float"
    finally:
        provider.close()


def test_manual_life_memory_indexes_immediately_and_survives_embedding_failure(client, monkeypatch):
    response = client.post("/api/characters/default/memories", json={"content": "小时候和奶奶一起种过桂花", "is_core": True})
    assert response.status_code == 201
    value = response.json()
    assert value["status"] == "active" and value["source_name"] == "用户编写"
    assert value["document_id"] is None and value["time_label"] == ""
    with SessionLocal() as session:
        row = session.get(CharacterMemory, value["id"])
        assert len(row.embedding) == client.app.state.embedding_provider.dimension
        assert recall_character_memories(session, "default", "你好")[0].id == row.id
    assert client.post("/api/characters/default/memories", json={"content": value["content"]}).status_code == 409
    def offline(*args):
        raise RuntimeError("offline")
    monkeypatch.setattr(client.app.state.embedding_provider, "embed_documents", offline)
    response = client.post("/api/characters/default/memories", json={"content": "桂花盛开时喜欢泡茶"})
    assert response.status_code == 201
    with SessionLocal() as session:
        assert session.get(CharacterMemory, response.json()["id"]).embedding is None
        assert any(row.id == response.json()["id"] for row in recall_character_memories(session, "default", "泡茶"))


def test_extract_api_review_and_context_flow(client, monkeypatch):
    import apps.api.character_memory as api
    provider = ExtractProvider()
    monkeypatch.setattr(api, "build_provider", lambda _: provider)
    doc_id, _ = document_fixture()
    response = client.post("/api/characters/default/extract", json={"document_id": doc_id})
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        library = client.get("/api/characters/default/memories").json()
        if library["jobs"][0]["status"] != "running":
            break
        time.sleep(0.02)
    assert library["jobs"][0]["status"] == "completed" and len(library["memories"]) == 2
    draft = library["memories"][0]
    reviewed = client.patch(f"/api/characters/default/memories/{draft['id']}", json={
        "content": "记得在海港寻找老师的日子", "source_quote": draft["source_quote"], "status": "active", "is_core": True,
    })
    assert reviewed.status_code == 200
    with SessionLocal() as session:
        conversation = Conversation(agent_id="default")
        session.add(conversation); session.commit()
        context = build_context(session, "你好", conversation.id, "你好", 3000, 5, embedding_provider=KeywordEmbeddingProvider())
        assert "记得在海港寻找老师的日子" in context.system
        assert context.character_memory_ids == [draft["id"]]


def test_failed_extraction_provider_does_not_claim_document_or_leave_running_job(client, monkeypatch):
    import apps.api.character_memory as api
    def broken(_):
        raise RuntimeError("bad provider")
    monkeypatch.setattr(api, "build_provider", broken)
    doc_id, _ = document_fixture()
    assert client.post("/api/characters/default/extract", json={"document_id": doc_id}).status_code == 422
    with SessionLocal() as session:
        assert session.get(Document, doc_id).agent_id is None
        assert session.query(CharacterExtraction).count() == 0


def test_retrieval_switch_persists_for_restart_and_write_failure_restores_memory(client, monkeypatch):
    from core.settings.runtime import RuntimeSettingsStore
    response = client.post("/api/settings/retrieval", json={"provider": "keyword"})
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = client.get("/api/settings/retrieval").json()
        if value["job"]["status"] not in {"preparing", "indexing"}:
            break
        time.sleep(0.02)
    assert value["job"]["status"] == "completed" and not value["semantic_ready"]
    store = client.app.state.runtime_settings_store
    restored = RuntimeSettingsStore(str(store.path), settings, {})
    assert restored.snapshot()["embedding"] == store.snapshot()["embedding"]
    previous = store.snapshot()["embedding"]
    def fail_write():
        raise OSError("disk full")
    monkeypatch.setattr(store, "_write", fail_write)
    with pytest.raises(OSError):
        store.update("embedding", {"embedding_provider": "fastembed"})
    assert store.snapshot()["embedding"] == previous


def test_invalid_online_url_is_validation_error(client):
    response = client.post("/api/settings/retrieval", json={"provider": "openai-compatible", "model": "test", "base_url": "https://[invalid", "api_key": "test"})
    assert response.status_code == 422
    assert not client.app.state.retrieval_maintenance


def test_user_memory_query_falls_back_when_embedding_is_offline():
    from core.memory.conversation import retrieve_memories
    class Offline:
        dimension = 3
        model_name = "offline"
        def embed_query(self, query):
            raise RuntimeError("offline")
    with SessionLocal() as session:
        row = Memory(user_id="default", content="喜欢桂花茶", normalized_key="tea", kind="profile",
            scope_type="global", scope_key="global", importance=4, confidence=1)
        session.add(row); session.commit()
        assert retrieve_memories(session, "default", "桂花", 3, Offline())[0].id == row.id


def test_incremental_sqlite_migration_preserves_existing_document(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("character_migration", Path("migrations/sqlite_versions/20260912_02_character_memory.py"))
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    old = create_engine("sqlite:///" + (tmp_path / "old.db").as_posix())
    try:
        with old.begin() as connection:
            connection.execute(text("CREATE TABLE documents (id VARCHAR(32) PRIMARY KEY, original_filename TEXT)"))
            connection.execute(text("CREATE TABLE document_chunks (id VARCHAR(32) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO documents VALUES ('kept', 'existing.txt')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
            assert connection.execute(text("SELECT original_filename, agent_id FROM documents WHERE id='kept'")).one() == ("existing.txt", None)
            assert CharacterMemory.__tablename__ in inspect(connection).get_table_names()
            assert CharacterExtraction.__tablename__ in inspect(connection).get_table_names()
    finally:
        old.dispose()


@pytest.fixture
def existing_model(tmp_path):
    folder = tmp_path / "BAAI--bge-small-zh-v1.5" / "snapshots" / "master"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({"hidden_size": 512}))
    (folder / "modules.json").write_text(json.dumps([
        {"type": "sentence_transformers.models.Transformer", "path": ""},
        {"type": "sentence_transformers.models.Pooling", "path": "1_Pooling"},
    ]))
    (folder / "1_Pooling").mkdir()
    (folder / "1_Pooling/config.json").write_text(json.dumps({"word_embedding_dimension": 512, "pooling_mode_cls_token": True}))
    (folder / "model.safetensors").write_bytes(b"fixture")
    (folder / "tokenizer.json").write_text("{}")
    return folder


def test_existing_model_inspection_resolves_snapshot_without_loading(client, existing_model, monkeypatch):
    import core.rag.embedding as embedding
    monkeypatch.setattr(embedding.LocalEmbeddingProvider, "_load", lambda _: pytest.fail("inspection must not load weights"))
    response = client.post("/api/settings/retrieval/inspect-local", json={"path": str(existing_model.parent.parent)})
    assert response.status_code == 200
    assert response.json()["path"] == str(existing_model)
    assert response.json()["dimension"] == 512
    assert not client.app.state.retrieval_maintenance


def test_existing_model_rejects_custom_modules_and_escape(existing_model):
    from core.rag.local_models import inspect_local_model
    for module in [{"type": "custom.Code", "path": ""}, {"type": "sentence_transformers.models.Transformer", "path": "../outside"}]:
        (existing_model / "modules.json").write_text(json.dumps([module]))
        with pytest.raises(ValueError):
            inspect_local_model(str(existing_model))


def test_existing_model_settings_use_detected_dimension_and_no_download(client, existing_model, monkeypatch):
    import apps.api.retrieval_settings as api
    from core.rag.local_models import inspect_local_model
    info = {**inspect_local_model(str(existing_model)), "runtime_ready": True}
    monkeypatch.setattr(api, "inspect_local_model", lambda _: info)
    seen = []
    def build(config, **kwargs):
        seen.append((config.embedding_model_path, config.embedding_dim, kwargs))
        return MockEmbeddingProvider(config.embedding_dim)
    monkeypatch.setattr(api, "build_embedding_provider", build)
    response = client.post("/api/settings/retrieval", json={"provider": "local", "model_path": str(existing_model.parent.parent), "dimension": 1536})
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get("/api/settings/retrieval").json()
        if result["job"]["status"] not in {"preparing", "indexing"}:
            break
        time.sleep(0.02)
    assert result["job"]["status"] == "completed" and result["retrieval_mode"] == "hybrid"
    assert seen == [(str(existing_model), 512, {"download": False, "strict": True})]
    assert result["model_path"] == str(existing_model)


def test_fastembed_cached_status_is_read_only_and_requires_complete_files(tmp_path, monkeypatch):
    from fastembed import TextEmbedding
    from core.rag import local_models
    root = tmp_path / "models--fixture--model" / "snapshots" / "revision"
    root.mkdir(parents=True)
    monkeypatch.setattr(local_models, "data_path", lambda _: str(tmp_path))
    monkeypatch.setattr(TextEmbedding, "list_supported_models", lambda: [{"model": "test", "sources": {"hf": "fixture/model"}, "model_file": "model.onnx"}])
    assert local_models.cached_model_directory("test") is None
    for name in ["model.onnx", "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]:
        (root / name).write_text("{}")
    assert local_models.cached_model_directory("test") == str(root)
    (root / "model.onnx").write_bytes(b"")
    assert local_models.cached_model_directory("test") is None


def test_vector_provider_keeps_bm25_candidates_in_hybrid_retrieval():
    doc_id, chunks = document_fixture(model="hybrid", dim=2)
    with SessionLocal() as session:
        session.get(DocumentChunk, chunks[0]).embedding = [1., 0.]
        session.get(DocumentChunk, chunks[1]).embedding = [0., 1.]
        session.commit()
        class Semantic:
            model_name = "hybrid"
            dimension = 2
            def embed_query(self, _):
                return [1., 0.]
        result = retrieve(session, Semantic(), "海港", settings)
        by_id = {row.chunk_id: row for row in result}
        assert set(by_id) == set(chunks)
        assert by_id[chunks[0]].vector_score == 1 and by_id[chunks[0]].bm25_score is None
        assert by_id[chunks[1]].bm25_score > 0 and by_id[chunks[1]].vector_score == 0


def test_missing_existing_model_runtime_is_explicit_and_does_not_start_job(client, existing_model, monkeypatch):
    import apps.api.retrieval_settings as api
    monkeypatch.setattr(api, "inspect_local_model", lambda _: {"runtime_ready": False})
    response = client.post("/api/settings/retrieval", json={"provider": "local", "model_path": str(existing_model)})
    assert response.status_code == 422 and "legacy-embedding" in response.text
    assert not client.app.state.retrieval_maintenance
