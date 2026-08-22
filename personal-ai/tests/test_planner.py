import json

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from core.chat.agent import run_chat
from core.chat.gateway import MockProvider
from core.execution.permissions import APPROVAL_WAITERS
from core.automation.planner import PlanValidationError, parse_plan
from core.capabilities.skills import load_skills
from infrastructure.config import settings
from infrastructure.database import (
    AgentRun,
    Conversation,
    Message,
    Plan,
    PlanStep,
    SessionLocal,
    ToolRun,
    _migrate_sqlite_p6,
    engine,
)


class InvalidPlannerProvider(MockProvider):
    async def complete(self, messages, temperature=0.2):
        if "PLANNER_CREATE_V1" in str(messages[0].get("content", "")):
            return '{"goal":"坏计划","steps":[]}'
        return await super().complete(messages, temperature=temperature)


class DoubleTimePlanProvider(MockProvider):
    async def complete(self, messages, temperature=0.2):
        if "PLANNER_CREATE_V1" in str(messages[0].get("content", "")):
            return json.dumps(
                {
                    "goal": "两次查询",
                    "steps": [
                        {
                            "title": "第一次查询",
                            "instruction": "查询现在时间",
                            "tool_hints": ["get_time"],
                        },
                        {
                            "title": "第二次查询",
                            "instruction": "再次查询时间",
                            "tool_hints": ["get_time"],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        return await super().complete(messages, temperature=temperature)


def _conversation() -> str:
    with SessionLocal() as session:
        row = Conversation(title="Planner test")
        session.add(row)
        session.commit()
        return row.id


def test_parse_plan_validates_schema_and_tool_hints():
    text = json.dumps(
        {
            "goal": "完成任务",
            "steps": [
                {"title": "查询", "instruction": "查询时间", "tool_hints": ["get_time"]},
                {"title": "整理", "instruction": "整理结果", "tool_hints": []},
            ],
        },
        ensure_ascii=False,
    )
    draft = parse_plan(text, {"get_time"}, 6)
    assert len(draft.steps) == 2
    with pytest.raises(PlanValidationError):
        parse_plan(text.replace("get_time", "unknown"), {"get_time"}, 6)
    with pytest.raises(PlanValidationError):
        parse_plan('{"goal":"x","steps":[],"extra":1}', set(), 6)
    duplicate = json.dumps(
        {
            "goal": "重复",
            "steps": [
                {"title": "同一步", "instruction": "重复执行", "tool_hints": []},
                {"title": "同一步", "instruction": "重复执行", "tool_hints": []},
            ],
        },
        ensure_ascii=False,
    )
    with pytest.raises(PlanValidationError):
        parse_plan(duplicate, set(), 6)


@pytest.mark.asyncio
async def test_planned_run_persists_steps_and_uses_one_agent_run(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    events = []
    async for event in run_chat(
        MockProvider(delay=0),
        _conversation(),
        "查询现在的时间并整理结果",
        skills=load_skills(),
        execution_mode="planned",
    ):
        events.append(event)
    types = [event.type for event in events]
    assert "plan.created" in types
    assert types.count("plan.step.completed") == 2
    assert "plan.completed" in types
    assert types[-1] == "run.completed"
    with SessionLocal() as session:
        assert session.query(AgentRun).one().execution_mode == "planned"
        plan = session.query(Plan).one()
        assert plan.status == "completed"
        assert session.query(PlanStep).filter(PlanStep.status == "completed").count() == 2
        assert session.query(ToolRun).count() == 1


@pytest.mark.asyncio
async def test_background_planned_high_replans_without_waiter(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "sandbox_dir", str(tmp_path))
    events = []
    async for event in run_chat(
        MockProvider(delay=0),
        _conversation(),
        "保存笔记：不能后台写入",
        skills=load_skills(),
        execution_mode="planned",
        approval_mode="deny",
        activity_id="activity-test",
    ):
        events.append(event.type)
    assert "plan.step.blocked" in events
    assert "plan.replanned" in events
    assert "plan.completed" in events
    assert not APPROVAL_WAITERS
    assert not (tmp_path / "notes.md").exists()
    with SessionLocal() as session:
        assert session.query(Plan).one().replan_count == 1
        assert session.query(ToolRun).one().status == "rejected"


def test_plan_and_capability_api(client):
    conv = client.post("/api/conversations", json={}).json()
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conv["id"],
            "message": "分两步整理这个目标",
            "execution_mode": "planned",
        },
    )
    assert response.status_code == 200
    plans = client.get(f"/api/conversations/{conv['id']}/plans")
    assert plans.status_code == 200 and len(plans.json()) == 1
    plan_id = plans.json()[0]["id"]
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "completed"
    capabilities = client.get("/api/capabilities")
    assert capabilities.status_code == 200
    assert any(item["name"] == "get_time" for item in capabilities.json())
    serialized = json.dumps(capabilities.json(), ensure_ascii=False).lower()
    assert "command" not in serialized and "api_key" not in serialized


def test_conversation_with_running_run_cannot_start_or_delete(client):
    conv = client.post("/api/conversations", json={}).json()
    with SessionLocal() as session:
        session.add(AgentRun(conversation_id=conv["id"], status="running"))
        session.commit()
    assert client.post(
        "/api/chat", json={"conversation_id": conv["id"], "message": "hi"}
    ).status_code == 409
    assert client.delete(f"/api/conversations/{conv['id']}").status_code == 409


def test_database_rejects_two_running_runs_for_one_conversation():
    conversation_id = _conversation()
    with SessionLocal() as session:
        session.add(AgentRun(conversation_id=conversation_id, status="running"))
        session.commit()
        session.add(AgentRun(conversation_id=conversation_id, status="running"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.asyncio
async def test_invalid_planner_output_fails_plan_and_saves_explanation(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    events = []
    async for event in run_chat(
        InvalidPlannerProvider(delay=0),
        _conversation(),
        "执行一个复杂目标",
        skills=load_skills(),
        execution_mode="planned",
    ):
        events.append(event.type)
    assert events[-1] == "run.failed"
    with SessionLocal() as session:
        assert session.query(Plan).one().status == "failed"
        assert session.query(PlanStep).count() == 0
        assert session.query(AgentRun).one().status == "failed"
        messages = session.query(Message).order_by(Message.created_at).all()
        assert [row.role for row in messages] == ["user", "assistant"]
        assert "安全停止" in messages[-1].content


@pytest.mark.asyncio
async def test_plan_steps_share_total_tool_budget(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "planner_max_tool_calls", 1)
    monkeypatch.setattr(settings, "planner_max_replans", 0)
    events = []
    async for event in run_chat(
        DoubleTimePlanProvider(delay=0),
        _conversation(),
        "执行两次时间查询",
        skills=load_skills(),
        execution_mode="planned",
    ):
        events.append(event.type)
    assert events[-1] == "run.failed"
    with SessionLocal() as session:
        assert session.query(ToolRun).count() == 1
        assert session.query(Plan).one().status == "failed"
        assert session.query(PlanStep).filter(PlanStep.status == "completed").count() == 1
        assert session.query(PlanStep).filter(PlanStep.status == "blocked").count() == 1


def test_planner_disabled_rejects_chat_and_activity(client, monkeypatch):
    monkeypatch.setattr(settings, "planner_enabled", False)
    conv = client.post("/api/conversations", json={}).json()
    assert client.post(
        "/api/chat",
        json={"conversation_id": conv["id"], "message": "规划", "execution_mode": "planned"},
    ).status_code == 409
    assert client.post(
        "/api/activities",
        json={
            "title": "规划活动",
            "prompt": "执行目标",
            "execution_mode": "planned",
            "schedule_type": "once",
            "next_run_at": "2026-08-22T09:00:00+08:00",
        },
    ).status_code == 409


def test_p6_migration_adds_execution_modes_and_is_idempotent():
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_agent_runs_running_conversation"))
        connection.execute(text("ALTER TABLE agent_runs DROP COLUMN execution_mode"))
        connection.execute(text("ALTER TABLE activities DROP COLUMN execution_mode"))
    _migrate_sqlite_p6()
    _migrate_sqlite_p6()
    inspector = inspect(engine)
    assert "execution_mode" in {row["name"] for row in inspector.get_columns("agent_runs")}
    assert "execution_mode" in {row["name"] for row in inspector.get_columns("activities")}
    assert "uq_agent_runs_running_conversation" in {
        row["name"] for row in inspector.get_indexes("agent_runs")
    }


def test_delete_conversation_cleans_plan_run_and_steps(client):
    conv = client.post("/api/conversations", json={}).json()
    client.post(
        "/api/chat",
        json={"conversation_id": conv["id"], "message": "规划", "execution_mode": "planned"},
    )
    assert client.delete(f"/api/conversations/{conv['id']}").status_code == 200
    with SessionLocal() as session:
        assert session.query(PlanStep).count() == 0
        assert session.query(Plan).count() == 0
        assert session.query(AgentRun).count() == 0
        assert session.query(ToolRun).count() == 0
