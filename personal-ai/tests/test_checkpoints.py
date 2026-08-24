from datetime import datetime, timezone

import pytest

from core.capabilities.registry import build_run_capability_snapshot
from core.capabilities.skills import allowed_tool_names, load_skills
from core.chat.agent import run_chat
from core.chat.checkpoints import create_checkpoint, recover_interrupted_runs
from core.chat.gateway import MockProvider
from core.chat.intent import IntentResult, narrow_allowed_tools
from core.execution.executor import _tool_idempotency_key
from infrastructure.config import settings
from infrastructure.database import (
    AgentRun,
    Checkpoint,
    Conversation,
    Message,
    Plan,
    PlanStep,
    SessionLocal,
    ToolRun,
)


def _seed_interrupted_time_run(skills=None) -> tuple[str, str, str]:
    skills = load_skills() if skills is None else list(skills)
    intent = IntentResult(
        intent="current_information",
        action="get_time",
        needs_memory=False,
        needs_knowledge=False,
        needs_workspace=False,
        needs_plan=True,
        candidate_tools=("get_time",),
        risk_hint="low",
        confidence=1.0,
        source="rule",
    )
    allowed = narrow_allowed_tools(intent, allowed_tool_names(skills, settings.tools_enabled))
    capability_version, snapshot = build_run_capability_snapshot(skills, allowed)
    with SessionLocal() as session:
        conversation = Conversation(title="Checkpoint test")
        session.add(conversation)
        session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="查询现在时间",
        )
        session.add(message)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.id,
            input_message_id=message.id,
            execution_mode="planned",
            capability_version=capability_version,
            capability_snapshot=snapshot,
            intent_json=intent.to_dict(),
            status="interrupted",
        )
        session.add(run)
        session.flush()
        plan = Plan(
            run_id=run.id,
            conversation_id=conversation.id,
            goal="查询时间",
            status="interrupted",
            current_version=1,
        )
        session.add(plan)
        session.flush()
        step = PlanStep(
            plan_id=plan.id,
            version=1,
            position=1,
            title="查询时间",
            instruction="查询现在时间",
            tool_hints=["get_time"],
            status="interrupted",
        )
        session.add(step)
        session.commit()
        ids = (conversation.id, run.id, step.id)
    create_checkpoint(
        ids[1],
        plan.id,
        ids[2],
        {
            "goal": "查询时间",
            "plan_version": 1,
            "current_step": 1,
            "completed_steps": [],
        },
        "interrupted",
    )
    return ids


def test_startup_recovery_interrupts_run_step_and_pending_tool():
    with SessionLocal() as session:
        conversation = Conversation(title="recover")
        session.add(conversation)
        session.flush()
        run = AgentRun(
            conversation_id=conversation.id,
            execution_mode="planned",
            capability_version="v1",
            status="running",
        )
        session.add(run)
        session.flush()
        plan = Plan(
            run_id=run.id,
            conversation_id=conversation.id,
            goal="恢复测试",
            status="running",
        )
        session.add(plan)
        session.flush()
        step = PlanStep(
            plan_id=plan.id,
            version=1,
            position=1,
            title="执行",
            instruction="执行",
            status="running",
        )
        session.add(step)
        session.flush()
        tool = ToolRun(
            run_id=run.id,
            conversation_id=conversation.id,
            tool_call_id="pending-call",
            step_index=0,
            tool="get_time",
            risk_level="low",
            approval_id="old-approval",
            status="pending_approval",
        )
        session.add(tool)
        session.commit()
        ids = run.id, plan.id, step.id, tool.id

    assert recover_interrupted_runs() == 1
    with SessionLocal() as session:
        assert session.get(AgentRun, ids[0]).status == "interrupted"
        assert session.get(Plan, ids[1]).status == "interrupted"
        assert session.get(PlanStep, ids[2]).status == "interrupted"
        recovered_tool = session.get(ToolRun, ids[3])
        assert recovered_tool.status == "interrupted"
        assert recovered_tool.approval_id is None
        checkpoint = session.query(Checkpoint).filter_by(run_id=ids[0]).one()
        assert checkpoint.status == "interrupted"
        assert checkpoint.state_json["pending_approval_id"] is None
        assert "files" in checkpoint.workspace_snapshot_json


@pytest.mark.asyncio
async def test_resume_reuses_completed_tool_even_when_budget_is_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "planner_max_tool_calls", 1)
    conversation_id, run_id, step_id = _seed_interrupted_time_run()
    key = _tool_idempotency_key(run_id, 1, step_id, "get_time", {})
    with SessionLocal() as session:
        session.add(
            ToolRun(
                run_id=run_id,
                conversation_id=conversation_id,
                tool_call_id="completed-call",
                step_index=0,
                plan_version=1,
                plan_step_id=step_id,
                idempotency_key=key,
                tool="get_time",
                args_summary="{}",
                result_summary="当前时间：2026-08-23 12:00:00",
                risk_level="low",
                status="completed",
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    events = []
    async for event in run_chat(
        MockProvider(delay=0),
        conversation_id,
        "查询现在时间",
        skills=load_skills(),
        execution_mode="planned",
        run_id=run_id,
        resume=True,
    ):
        events.append(event.type)

    assert "run.resumed" in events
    assert "tool.reused" in events
    assert events[-1] == "run.completed"
    with SessionLocal() as session:
        assert session.query(ToolRun).filter_by(run_id=run_id).count() == 1
        assert session.get(AgentRun, run_id).status == "completed"
        assert session.query(PlanStep).filter_by(plan_id=session.query(Plan.id).scalar()).one().status == "completed"


def test_checkpoint_api_lists_latest_first(client):
    conversation_id, run_id, _ = _seed_interrupted_time_run()
    response = client.get(f"/api/runs/{run_id}/checkpoints")
    assert response.status_code == 200
    assert response.json()[0]["sequence"] == 1
    by_conversation = client.get(f"/api/conversations/{conversation_id}/checkpoints")
    assert by_conversation.status_code == 200
    assert by_conversation.json()[0]["run_id"] == run_id


def test_resume_api_continues_original_run(client, monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    _, run_id, _ = _seed_interrupted_time_run(client.app.state.skills)
    response = client.post(f"/api/chat/{run_id}/resume")
    assert response.status_code == 200
    assert "event: run.resumed" in response.text
    assert "event: run.completed" in response.text
    with SessionLocal() as session:
        assert session.get(AgentRun, run_id).status == "completed"


def test_continue_message_auto_resumes_latest_planned_run(client, monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    conversation_id, run_id, _ = _seed_interrupted_time_run(client.app.state.skills)

    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation_id,
            "message": "继续",
            # 前端不需要知道上次是哪种模式，后端按 Checkpoint 自动续接。
            "execution_mode": "direct",
        },
    )

    assert response.status_code == 200
    assert "event: run.resumed" in response.text
    assert f'"run_id": "{run_id}"' in response.text
    assert "event: run.completed" in response.text
    with SessionLocal() as session:
        runs = session.query(AgentRun).filter_by(conversation_id=conversation_id).all()
        assert [run.id for run in runs] == [run_id]
        assert runs[0].status == "completed"
        continuation = (
            session.query(Message)
            .filter_by(conversation_id=conversation_id, role="user", content="继续")
            .one()
        )
        assert continuation.status == "completed"
