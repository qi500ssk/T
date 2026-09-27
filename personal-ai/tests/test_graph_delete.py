from threading import Event

from apps.api.main import app
from infrastructure.database import (SessionLocal, Document, DocumentChunk, WorldFact,
    CharacterMemory, DocumentGraphChunk, PersonResolution, GraphOrganization)
from tests.test_person_identity import identity_fixture
from tests.test_document_graph import WorldProvider


def test_delete_graph_preserves_source_and_other_documents(client):
    doc, fact, memory = identity_fixture()
    with SessionLocal() as session:
        session.get(Document, doc).stored_filename = "first.txt"
        session.get(Document, doc).content_hash = "first"
        session.add(PersonResolution(document_id=doc, name="一里", target="后藤一里", decision="same"))
        session.add(GraphOrganization(document_id=doc, status="completed", state={}))
        session.commit()
    other, other_fact, other_memory = identity_fixture()
    root = f"/api/documents/{doc}/graph"
    assert client.delete(root).status_code == 200
    assert client.get(root).json()["facts"] == []
    assert client.get(root).json()["completed"] == 0
    with SessionLocal() as session:
        assert session.get(Document, doc) is not None
        assert session.query(DocumentChunk).filter_by(document_id=doc).count() == 2
        assert session.get(WorldFact, fact) is None
        for model in (DocumentGraphChunk, PersonResolution, GraphOrganization):
            assert session.query(model).filter_by(document_id=doc).count() == 0
        saved = session.get(CharacterMemory, memory)
        assert saved.content == "回忆" and saved.status == "draft" and saved.world_fact_id is None
        assert session.get(WorldFact, other_fact) is not None
        assert session.get(CharacterMemory, other_memory).status == "active"
    assert client.delete(root).status_code == 200
    assert client.delete("/api/documents/missing/graph").status_code == 404


def test_delete_graph_blocks_background_writers(client):
    doc, fact, _ = identity_fixture()
    app.state.character_tasks["other-character"] = object()
    try:
        assert client.delete(f"/api/documents/{doc}/graph").status_code == 409
        with SessionLocal() as session:
            assert session.get(WorldFact, fact) is not None
    finally:
        app.state.character_tasks.clear()


def test_regenerate_clears_progress_only_after_provider_is_ready(client, monkeypatch):
    import apps.api.document_graph as api
    doc, fact, _ = identity_fixture()
    monkeypatch.setattr(api.settings, "llm_provider", "mock")
    def fail(_):
        raise RuntimeError("unavailable")
    monkeypatch.setattr(api, "build_provider", fail)
    root = f"/api/documents/{doc}/graph/extract?reset=true"
    assert client.post(root).status_code == 422
    with SessionLocal() as session:
        assert session.get(WorldFact, fact) is not None
    monkeypatch.setattr(api, "build_provider", lambda _: WorldProvider())
    observed = []
    finished = Event()
    async def inspect(document_id, provider, budget, **kwargs):
        with SessionLocal() as session:
            observed.append(session.query(WorldFact).filter_by(document_id=document_id).count())
            assert not session.query(DocumentGraphChunk).filter_by(document_id=document_id, status="completed").count()
        await provider.close()
        finished.set()
    monkeypatch.setattr(api, "extract_document_graph", inspect)
    assert client.post(root).status_code == 202
    assert finished.wait(3), "Background extraction did not finish"
    assert observed == [0]
