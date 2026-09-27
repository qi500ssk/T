import json
import pytest

from core.memory.world import extract_document_graph, document_graph_snapshot, digest
from core.memory.builder import build_character_drafts
from core.memory.character import recall_character_memories
from infrastructure.database import CharacterMemory, Document, DocumentChunk, DocumentGraphChunk, WorldFact, SessionLocal
from tests.test_character_memory import document_fixture


class WorldProvider:
    def __init__(self, partial=False, fail=False):
        self.calls = []
        self.partial, self.fail, self.closed = partial, fail, False

    async def complete(self, messages, temperature=0):
        source = json.loads(messages[-1]["content"])["source"]
        self.calls.append(source)
        if self.fail:
            raise RuntimeError("do not expose provider secrets")
        return json.dumps({"complete": not self.partial, "facts": [{"content": source, "source_quote": source,
            "graph": {"people": ["小岚", "老师"], "event": "独立事件"}}]})

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_world_covers_all_chunks_and_resume_is_idempotent():
    doc_id, chunks = document_fixture()
    first = WorldProvider()
    await extract_document_graph(doc_id, first, 6000)
    assert len(first.calls) == 2 and first.closed
    again = WorldProvider()
    await extract_document_graph(doc_id, again, 6000)
    assert not again.calls
    with SessionLocal() as session:
        snapshot = document_graph_snapshot(session, session.get(Document, doc_id))
        assert snapshot["completed"] == snapshot["total"] == 2
        assert session.query(WorldFact).count() == 2
        assert session.query(CharacterMemory).count() == 0
        assert session.get(Document, doc_id).agent_id is None
        assert {n["label"] for n in snapshot["nodes"] if n["type"] == "person"} == {"小岚", "老师"}
        assert not any(n["type"] == "character" for n in snapshot["nodes"])


@pytest.mark.asyncio
async def test_partial_and_failed_chunks_remain_visible_and_retryable():
    doc_id, _ = document_fixture()
    await extract_document_graph(doc_id, WorldProvider(partial=True), 6000)
    with SessionLocal() as session:
        snapshot = document_graph_snapshot(session, session.get(Document, doc_id))
        assert snapshot["partial"] == 2 and snapshot["completed"] == 0
    await extract_document_graph(doc_id, WorldProvider(fail=True), 6000)
    with SessionLocal() as session:
        snapshot = document_graph_snapshot(session, session.get(Document, doc_id))
        assert snapshot["failed"] == 2 and len(snapshot["facts"]) == 2
        assert "secrets" not in str(snapshot)
    await extract_document_graph(doc_id, WorldProvider(), 6000)
    with SessionLocal() as session:
        assert session.query(WorldFact).count() == 2
        assert all(row.status == "completed" for row in session.query(DocumentGraphChunk))


def fact_fixture():
    doc_id, chunks = document_fixture()
    with SessionLocal() as session:
        chunk = session.get(DocumentChunk, chunks[0])
        fact = WorldFact(document_id=doc_id, chunk_id=chunk.id, source_hash=digest(chunk.content),
            content=chunk.content, source_quote=chunk.content, status="active", graph={"event": "钟楼救援",
            "people": ["小岚", "同伴"], "event_links": [{"event": "私下秘密", "relation": "after", "quote": chunk.content}]})
        session.add(fact); session.commit()
        return doc_id, fact.id


class PerspectiveProvider:
    def __init__(self, unknown=False):
        self.unknown = unknown
    async def complete(self, messages, temperature=0):
        evidence = json.loads(messages[-1]["content"])["evidence"]
        return json.dumps({"knowledge": "unknown" if self.unknown else "direct", "content": "我曾在钟楼救下同伴",
            "evidence_quote": evidence, "importance": 5, "emotion": "担心"})
    async def close(self):
        pass


@pytest.mark.asyncio
async def test_two_characters_reference_one_fact_and_unknown_is_not_imported():
    _, fact_id = fact_fixture()
    for agent in ("a", "b"):
        result = await build_character_drafts(agent, "小岚", [fact_id], PerspectiveProvider(), 6000)
        assert result["created"] == 1
    unknown = await build_character_drafts("c", "旁人", [fact_id], PerspectiveProvider(unknown=True), 6000)
    assert unknown["unknown"] == 1
    with SessionLocal() as session:
        assert session.query(WorldFact).count() == 1
        memories = session.query(CharacterMemory).all()
        assert len(memories) == 2 and all(m.world_fact_id == fact_id and m.graph == {} for m in memories)
        assert recall_character_memories(session, "a", "钟楼") == []
        for row in memories:
            row.status = "active"
        session.commit()
        recalled = recall_character_memories(session, "a", "钟楼")
        assert len(recalled) == 1 and recalled[0].agent_id == "a"
        assert not recalled[0].graph["event_links"]  # 不沿世界关系泄露另一件未知事件。
        assert recalled[0].graph["importance"] == 5
        assert not recall_character_memories(session, "c", "钟楼")
        session.get(WorldFact, fact_id).status = "rejected"
        session.commit()
        assert not recall_character_memories(session, "a", "钟楼")


def test_world_review_requires_matching_source_and_document(client):
    doc_id, fact_id = fact_fixture()
    with SessionLocal() as session:
        fact = session.get(WorldFact, fact_id)
        quote = fact.source_quote
    route = f"/api/documents/{doc_id}/graph/facts/{fact_id}"
    assert client.patch(route, json={"content": "改写", "source_quote": "虚构引用"}).status_code == 422
    assert client.patch(route, json={"content": "改写", "source_quote": quote, "status": "active"}).status_code == 200
    with SessionLocal() as session:
        other_doc = Document(original_filename="other.txt", stored_filename="other.txt", mime_type="text/plain",
            file_type=".txt", size_bytes=1, content_hash="other", status="indexed", embedding_model="keyword-v1", embedding_dim=0)
        session.add(other_doc); session.commit(); other = other_doc.id
    assert client.patch(f"/api/documents/{other}/graph/facts/{fact_id}", json={"content": "改写", "source_quote": quote}).status_code == 404


def test_world_source_does_not_bypass_character_knowledge_via_global_rag():
    from core.rag.retrieval import retrieve
    from core.rag.embedding import KeywordEmbeddingProvider
    from infrastructure.config import settings
    doc_id, _ = fact_fixture()
    with SessionLocal() as session:
        assert not retrieve(session, KeywordEmbeddingProvider(), "钟楼", settings, agent_id="uninformed")
        # 用户主动附上原文进行讨论仍可查阅；它不自动成为角色原作记忆。
        assert retrieve(session, KeywordEmbeddingProvider(), "钟楼", settings, document_ids=[doc_id], agent_id="uninformed")


@pytest.mark.asyncio
async def test_edit_world_fact_returns_linked_active_memories_to_review(client):
    doc_id, fact_id = fact_fixture()
    await build_character_drafts("default", "小岚", [fact_id], PerspectiveProvider(), 6000)
    with SessionLocal() as session:
        memory = session.query(CharacterMemory).one()
        memory.status = "active"
        quote = session.get(WorldFact, fact_id).source_quote
        session.commit()
    assert client.patch(f"/api/documents/{doc_id}/graph/facts/{fact_id}", json={
        "content": "世界事实已核正", "source_quote": quote, "status": "active"}).status_code == 200
    with SessionLocal() as session:
        assert session.query(CharacterMemory).one().status == "draft"


@pytest.mark.asyncio
async def test_removed_document_removes_world_facts_without_orphan_reference():
    doc_id, fact_id = fact_fixture()
    await build_character_drafts("default", "小岚", [fact_id], PerspectiveProvider(), 6000)
    with SessionLocal() as session:
        session.delete(session.get(Document, doc_id)); session.commit()
        assert session.query(WorldFact).count() == 0
        assert session.query(CharacterMemory).one().world_fact_id is None
