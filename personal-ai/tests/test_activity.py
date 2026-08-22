import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.automation.activity import (
    ActivityConflictError,
    _claim_due_activity,
    _finish_activity,
    activity_worker,
    create_activity,
    pause_activity,
    recover_interrupted_activities,
    resume_activity,
    run_activity_now,
)
from core.chat.agent import run_chat
from core.chat.gateway import MockProvider
from core.execution.permissions import APPROVAL_WAITERS
from core.capabilities.skills import load_skills
from infrastructure.config import settings
from infrastructure.database import (
    Activity,
    AgentRun,
    Conversation,
    Memory,
    Plan,
    PlanStep,
    SessionLocal,
    ToolRun,
)


NOW = datetime(2026, 8, 21, 9, 0, tzinfo=timezone.utc)


def _create(**overrides):
    values = {
        "title": "每日总结",
        "prompt": "总结最近资料",
        "schedule_type": "once",
        "next_run_at": NOW,
    }
    values.update(overrides)
    return create_activity(**values)


def test_create_activity_and_state_transitions():
    row = _create(next_run_at=NOW + timedelta(hours=1))
    with SessionLocal() as session:
        assert session.get(Conversation, row.conversation_id).title == "活动：每日总结"

    assert pause_activity(row.id).status == "paused"
    with pytest.raises(ActivityConflictError):
        pause_activity(row.id)
    assert resume_activity(row.id).status == "scheduled"
    queued = run_activity_now(row.id, now=NOW)
    assert queued.next_run_at.replace(tzinfo=timezone.utc) == NOW


def test_claim_only_due_scheduled_activity():
    future = _create(title="未来", next_run_at=NOW + timedelta(minutes=1))
    due = _create(title="到期", next_run_at=NOW - timedelta(minutes=1))
    claimed = _claim_due_activity(NOW)
    assert claimed.id == due.id
    assert claimed.status == "running"
    with SessionLocal() as session:
        assert session.get(Activity, future.id).status == "scheduled"


def test_interval_finish_advances_to_one_future_occurrence():
    row = _create(
        schedule_type="interval",
        interval_minutes=10,
        next_run_at=NOW - timedelta(minutes=35),
    )
    assert _claim_due_activity(NOW).id == row.id
    finished = _finish_activity(row.id, succeeded=False, error="boom", now=NOW)
    assert finished.status == "scheduled"
    assert finished.last_error == "boom"
    assert finished.next_run_at.replace(tzinfo=timezone.utc) == NOW + timedelta(minutes=5)


def test_recover_running_activity():
    row = _create(next_run_at=NOW - timedelta(hours=1))
    assert _claim_due_activity(NOW).id == row.id
    with SessionLocal() as session:
        run = AgentRun(
            conversation_id=row.conversation_id,
            activity_id=row.id,
            execution_mode="planned",
            status="running",
        )
        session.add(run)
        session.flush()
        plan = Plan(
            run_id=run.id,
            conversation_id=row.conversation_id,
            activity_id=row.id,
            goal="恢复测试",
            status="running",
        )
        session.add(plan)
        session.flush()
        session.add(
            PlanStep(
                plan_id=plan.id,
                version=1,
                position=1,
                title="运行中",
                instruction="执行",
                status="running",
            )
        )
        session.commit()
    assert recover_interrupted_activities(NOW + timedelta(minutes=1)) == 1
    with SessionLocal() as session:
        recovered = session.get(Activity, row.id)
        assert recovered.status == "scheduled"
        assert "服务重启" in recovered.last_error
        assert session.query(AgentRun).one().status == "cancelled"
        assert session.query(Plan).one().status == "cancelled"
        assert session.query(PlanStep).one().status == "cancelled"


@pytest.mark.asyncio
async def test_activity_run_links_agent_and_skips_memory(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", True)
    row = _create(prompt="我喜欢无糖拿铁。")
    events = []
    async for event in run_chat(
        MockProvider(delay=0),
        row.conversation_id,
        row.prompt,
        skills=load_skills(),
        activity_id=row.id,
        approval_mode="deny",
    ):
        events.append(event.type)
    assert "run.completed" in events
    with SessionLocal() as session:
        assert session.query(AgentRun).one().activity_id == row.id
        assert session.query(Memory).count() == 0


@pytest.mark.asyncio
async def test_background_high_tool_is_rejected_without_waiter(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "sandbox_dir", str(tmp_path))
    row = _create(prompt="保存笔记：后台不能写")
    event_types = []
    async for event in run_chat(
        MockProvider(delay=0),
        row.conversation_id,
        row.prompt,
        skills=load_skills(),
        activity_id=row.id,
        approval_mode="deny",
    ):
        event_types.append(event.type)
    assert "approval.required" not in event_types
    assert not APPROVAL_WAITERS
    assert not (tmp_path / "notes.md").exists()
    with SessionLocal() as session:
        tool_run = session.query(ToolRun).one()
        assert tool_run.status == "rejected"
        assert "后台任务" in tool_run.result_summary


@pytest.mark.asyncio
async def test_worker_executes_due_activity(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "activity_poll_seconds", 1)
    row = _create(
        next_run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        execution_mode="planned",
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        activity_worker(stop_event, MockProvider(delay=0), None, load_skills())
    )
    try:
        for _ in range(300):
            await asyncio.sleep(0.01)
            with SessionLocal() as session:
                current = session.get(Activity, row.id)
                if current.status == "completed":
                    break
        else:
            pytest.fail("worker did not complete due activity")
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with SessionLocal() as session:
        current = session.get(Activity, row.id)
        run = session.query(AgentRun).one()
        assert current.last_run_id == run.id
        assert run.activity_id == row.id
        assert run.execution_mode == "planned"
        plan = session.query(Plan).one()
        assert plan.activity_id == row.id
        assert plan.status == "completed"


def test_activity_crud_api_and_conversation_guard(client):
    response = client.post(
        "/api/activities",
        json={
            "title": "资料总结",
            "prompt": "总结知识库",
            "schedule_type": "interval",
            "interval_minutes": 60,
            "next_run_at": "2026-08-22T09:00:00+08:00",
        },
    )
    assert response.status_code == 200
    row = response.json()
    assert row["next_run_at"].endswith("+00:00")
    assert client.get(f"/api/activities/{row['id']}").status_code == 200
    assert client.post(f"/api/activities/{row['id']}/pause").json()["status"] == "paused"
    assert client.post(f"/api/activities/{row['id']}/resume").json()["status"] == "scheduled"
    assert client.delete(f"/api/conversations/{row['conversation_id']}").status_code == 409
    assert client.delete(f"/api/activities/{row['id']}").status_code == 200
    assert client.delete(f"/api/conversations/{row['conversation_id']}").status_code == 200


def test_activity_api_rejects_naive_time_and_invalid_interval(client):
    base = {
        "title": "x",
        "prompt": "y",
        "schedule_type": "interval",
        "next_run_at": "2026-08-22T09:00:00",
    }
    assert client.post("/api/activities", json={**base, "interval_minutes": 10}).status_code == 422
    assert client.post(
        "/api/activities",
        json={**base, "next_run_at": "2026-08-22T09:00:00Z"},
    ).status_code == 422
