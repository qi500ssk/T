import asyncio
from types import SimpleNamespace

import pytest

from apps.api.document_graph import stop_graph
from core.memory.identity import aliases_for
from core.memory.character import resolve_character_memories
from core.memory.world import extract_document_graph, digest
from infrastructure.database import SessionLocal, Document, DocumentChunk, DocumentGraphChunk, WorldFact, CharacterMemory, PersonResolution
from tests.test_character_memory import document_fixture
from tests.test_document_graph import WorldProvider


def identity_fixture():
    doc, chunks = document_fixture()
    with SessionLocal() as session:
        chunk = session.get(DocumentChunk, chunks[0])
        session.add(DocumentGraphChunk(chunk_id=chunk.id, document_id=doc, source_hash=digest(chunk.content), status="completed"))
        fact = WorldFact(document_id=doc, chunk_id=chunk.id, source_hash=digest(chunk.content), content=chunk.content,
            source_quote=chunk.content, status="active", graph={"people": ["一里", "后藤一里", "波奇"]})
        session.add(fact); session.flush()
        memory = CharacterMemory(agent_id="default", world_fact_id=fact.id, status="active", content="回忆", known_to_character=True, perspective={"knowledge":"direct"})
        session.add(memory); session.commit()
        return doc, fact.id, memory.id


def test_confirm_identity_undo_preserves_source_and_scopes_document(client):
    doc, fact_id, memory_id = identity_fixture()
    with SessionLocal() as session:
        session.get(Document, doc).stored_filename = "first-document.txt"
        session.get(Document, doc).content_hash = "first-document-hash"
        session.commit()
    other, _, other_memory = identity_fixture()
    root = f"/api/documents/{doc}/graph"
    body = {"name":"一里", "target":"后藤一里", "decision":"same"}
    assert client.post(root + "/identities", json=body).status_code == 200
    assert client.post(root + "/identities", json=body).status_code == 200
    result = client.get(root).json()
    assert {n["label"] for n in result["nodes"] if n["type"] == "person"} == {"后藤一里", "波奇"}
    assert result["facts"][0]["graph"]["people"] == ["一里", "后藤一里", "波奇"]
    assert "一里" in {n["label"] for n in client.get(f"/api/documents/{other}/graph").json()["nodes"]}
    with SessionLocal() as session:
        memory = session.get(CharacterMemory, memory_id)
        assert memory.status == "draft"
        assert session.get(CharacterMemory, other_memory).status == "active"
        assert resolve_character_memories(session, [memory])[0].graph["people"] == ["后藤一里", "波奇"]
        assert session.get(WorldFact, fact_id).graph["people"][0] == "一里"
    rule_id = result["identity_rules"][0]["id"]
    assert client.delete(f"/api/documents/{other}/graph/identities/{rule_id}").status_code == 404
    assert client.delete(root + f"/identities/{rule_id}").status_code == 200
    assert "一里" in {n["label"] for n in client.get(root).json()["nodes"]}


def test_distinct_people_block_direct_and_transitive_merges(client):
    doc, _, _ = identity_fixture()
    url = f"/api/documents/{doc}/graph/identities"
    assert client.post(url, json={"name":"一里", "target":"后藤一里", "decision":"different"}).status_code == 200
    assert client.post(url, json={"name":"一里", "target":"后藤一里", "decision":"same"}).status_code == 409
    assert client.post(url, json={"name":"一里", "target":"波奇", "decision":"same"}).status_code == 200
    assert client.post(url, json={"name":"波奇", "target":"后藤一里", "decision":"same"}).status_code == 409
    assert client.post(url, json={"name":"波奇", "target":"一里", "decision":"same"}).status_code == 409
    assert client.post(url, json={"name":"她", "target":"一里", "decision":"same"}).status_code == 422
    assert client.post(url, json={"name":"未知人物", "target":"一里", "decision":"same"}).status_code == 422


def test_alias_chains_and_ambiguity_are_explicit():
    rule = lambda a, b: {"name":a, "target":b, "decision":"same"}
    assert aliases_for([rule("一里", "波奇"), rule("波奇", "后藤一里")])["一里"] == "后藤一里"
    with pytest.raises(ValueError):
        aliases_for([rule("一里", "波奇"), rule("一里", "另一个人")])


@pytest.mark.asyncio
async def test_stop_interrupts_inflight_request_preserves_completed_and_resumes():
    doc, chunks = document_fixture()
    started = asyncio.Event()

    class Blocking(WorldProvider):
        async def complete(self, messages, temperature=0):
            if self.calls:
                started.set()
                await asyncio.Event().wait()
            return await super().complete(messages, temperature)

    provider = Blocking()
    task = asyncio.create_task(extract_document_graph(doc, provider, 6000))
    tasks = {f"document:{doc}":task}
    task.add_done_callback(lambda _: tasks.pop(f"document:{doc}", None))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(character_tasks=tasks)))
    await asyncio.wait_for(started.wait(), timeout=3)
    result = await stop_graph(doc, request)
    assert result == {"stopping":False}
    assert task.cancelled() and provider.closed
    assert await stop_graph(doc, request) == {"stopping":False}
    with SessionLocal() as session:
        assert session.get(DocumentGraphChunk, chunks[0]).status == "completed"
        assert session.get(DocumentGraphChunk, chunks[1]).status == "paused"
        assert session.query(WorldFact).count() == 1
    resumed = WorldProvider()
    await extract_document_graph(doc, resumed, 6000)
    assert len(resumed.calls) == 1
    with SessionLocal() as session:
        assert session.query(WorldFact).count() == 2


def test_stop_endpoint_idle_and_deleted_document(client):
    doc, _, _ = identity_fixture()
    assert client.post(f"/api/documents/{doc}/graph/stop").json() == {"stopping":False}
    assert client.post("/api/documents/missing/graph/stop").status_code == 404
    assert client.post(f"/api/documents/{doc}/graph/identities", json={"name":"一里","target":"后藤一里","decision":"same"}).status_code == 200
    assert client.delete(f"/api/documents/{doc}").status_code == 200
    with SessionLocal() as session:
        assert session.query(PersonResolution).count() == 0
