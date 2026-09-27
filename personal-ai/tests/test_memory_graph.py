import importlib.util
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.memory.character import extract_document, recall_character_memories
from core.chat.context import build_context
from core.memory.graph import MemoryGraphData, build_memory_graph
from infrastructure.database import CharacterMemory, CharacterExtraction, Conversation, SessionLocal
from tests.test_character_memory import document_fixture


def memory(session, **values):
    row = CharacterMemory(agent_id=values.pop("agent_id", "default"), status=values.pop("status", "active"),
                          content=values.pop("content", "往事"), **values)
    session.add(row)
    session.flush()
    return row


def test_unresolved_mentions_never_become_people_but_facts_remain():
    row = SimpleNamespace(id="fact", graph={"people": ["她", "对方", "林岚"],
        "relationships": [{"subject": "她", "predicate": "遇见", "object": "林岚"}]},
        content="她遇见林岚", is_core=False, evidence_type="fact", source_quote="她遇见林岚")
    result = build_memory_graph([row], None)
    assert [n["label"] for n in result["nodes"] if n["type"] == "person"] == ["林岚"]
    assert any(n["id"] == "memory:fact" for n in result["nodes"])
    ids = {n["id"] for n in result["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in result["edges"])
    assert row.graph["people"] == ["她", "对方", "林岚"]


def test_graph_scope_review_and_evidence(client):
    with SessionLocal() as session:
        active = memory(session, source_quote="林岚是小雨的母亲", graph={"event": "搬家", "people": ["林岚"],
            "relationships": [{"subject": "林岚", "predicate": "母亲", "object": "小雨", "quote": "林岚是小雨的母亲"}]})
        draft = memory(session, status="draft", content="待确认秘密", graph={"people": ["秘密人物"]})
        memory(session, agent_id="other", content="另一角色秘密", graph={"people": ["他人"]})
        session.commit()
        active_id, draft_id = active.id, draft.id
    graph = client.get("/api/characters/default/memory-graph").json()
    assert any(node["type"] == "event" and node["label"] == "搬家" for node in graph["nodes"])
    assert all("秘密" not in node["label"] and node["label"] != "他人" for node in graph["nodes"])
    relation = next(edge for edge in graph["edges"] if edge["label"] == "母亲")
    assert relation["memory_id"] == active_id and relation["quote"] == "林岚是小雨的母亲"
    draft_graph = client.get("/api/characters/default/memory-graph?status=draft").json()
    assert any(draft_id in node["memory_ids"] for node in draft_graph["nodes"])
    assert client.get("/api/characters/default/memory-graph?status=anything").status_code == 422


def test_invalid_dates_and_old_clients_preserve_graph(client):
    assert client.post("/api/characters/default/memories", json={"content": "旅行", "graph": {
        "start": "2020-01-02", "end": "2020-01-01"}}).status_code == 422
    assert client.post("/api/characters/default/memories", json={"content": "旅行", "graph": {
        "start": "2020-02-30"}}).status_code == 422
    created = client.post("/api/characters/default/memories", json={"content": "旅行", "graph": {
        "start": "2020-01-02", "importance": 4, "people": ["小雨"]}}).json()
    saved = client.patch(f"/api/characters/default/memories/{created['id']}", json={
        "content": "旅行的新描述", "status": "active"}).json()
    assert saved["graph"]["start"] == "2020-01-02" and saved["graph"]["people"] == ["小雨"]


def test_relevant_memory_wins_over_many_core_memories_and_graph_neighbors_are_bounded():
    with SessionLocal() as session:
        for i in range(30):
            memory(session, content=f"稳定背景{i}", is_core=True, graph={"importance": 5})
        target = memory(session, content="早餐喜欢吃豆浆油条", graph={"importance": 1, "event": "早餐"})
        neighbor = memory(session, content="重逢后开始共同生活", graph={"event": "重逢", "event_links": [
            {"event": "早餐", "relation": "before", "quote": "重逢以后一起吃早餐"}]})
        memory(session, content="未确认", status="draft", graph={"event": "早餐"})
        memory(session, content="不知情", known_to_character=False, is_core=True)
        session.commit()
        rows = recall_character_memories(session, "default", "早餐", limit=6)
        assert rows[0].id == target.id
        assert neighbor.id in [row.id for row in rows]
        assert sum(row.is_core for row in rows) <= 2 and len(rows) <= 6
        assert not any(row.content in {"不知情", "未确认"} for row in rows)


def test_full_recollection_is_budgeted_without_using_display_summary():
    from infrastructure.config import settings
    with SessionLocal() as session:
        row = memory(session, content="冗长原文" * 200, is_core=True, graph={
            "summary": "小雨与母亲一起搬家", "start": "2020-01-02",
            "relationships": [{"subject": "林岚", "predicate": "母亲", "object": "小雨"}]})
        conversation = Conversation(agent_id="default")
        session.add(conversation); session.commit()
        config = SimpleNamespace(**{**settings.model_dump(), "character_memory_tokens_budget": 200})
        context = build_context(session, "角色", conversation.id, "搬家", 1000, 5, rag_settings=config)
        assert "小雨与母亲一起搬家" not in context.system and "冗长原文" not in context.system
        assert row.id not in context.character_memory_ids and context.token_estimate <= 1000
        config.character_memory_tokens_budget = 3000
        context = build_context(session, "角色", conversation.id, "搬家", 4000, 5, rag_settings=config)
        assert row.content in context.system
        assert "2020-01-02" in context.system and "林岚—母亲—小雨" in context.system
        assert row.id in context.character_memory_ids and context.token_estimate <= 4000


def test_event_links_resolve_across_chunks_only_when_target_is_unique():
    with SessionLocal() as session:
        first = memory(session, graph={"event": "相识"})
        second = memory(session, graph={"event": "重逢", "event_links": [
            {"event": "相识", "relation": "after", "quote": "相识之后重逢"}]})
        result = build_memory_graph([first, second], "小雨")
        assert any(edge["label"] == "晚于" for edge in result["edges"])
        duplicate = memory(session, graph={"event": "相识"})
        result = build_memory_graph([first, second, duplicate], "小雨")
        assert not any(edge["label"] == "晚于" for edge in result["edges"])


@pytest.mark.asyncio
async def test_extraction_rejects_unsupported_relation_and_time():
    doc_id, _ = document_fixture("default")
    class Provider:
        async def complete(self, messages, temperature=0):
            source = json.loads(messages[-1]["content"])["source"]
            return json.dumps({"memories": [
                {"content": source, "source_quote": source, "graph": {"start": "2020-01-01", "time_quote": "不存在的日期"}},
                {"content": source, "source_quote": source, "graph": {"relationships": [
                    {"subject": "甲", "predicate": "朋友", "object": "乙", "quote": "不存在的关系"}]}}
            ]})
        async def close(self):
            pass
    with SessionLocal() as session:
        job = CharacterExtraction(agent_id="default", document_id=doc_id)
        session.add(job); session.commit(); job_id = job.id
    await extract_document(job_id, "小岚", Provider(), 6000)
    with SessionLocal() as session:
        assert session.query(CharacterMemory).count() == 0
        assert session.get(CharacterExtraction, job_id).rejected == 4


def test_incremental_graph_migration_preserves_old_memory(tmp_path):
    spec = importlib.util.spec_from_file_location("graph_migration", "migrations/sqlite_versions/20260915_04_memory_graph.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///" + (tmp_path / "old.db").as_posix())
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE character_memories (id TEXT PRIMARY KEY, content TEXT)"))
            connection.execute(text("INSERT INTO character_memories VALUES ('old', '原有经历')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade(); migration.upgrade()
            assert connection.execute(text("SELECT content, graph FROM character_memories WHERE id='old'")).one() == ("原有经历", "{}")
    finally:
        engine.dispose()
