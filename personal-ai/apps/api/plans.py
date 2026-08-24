"""Plan 历史与只读 Capability API。"""

from fastapi import APIRouter, HTTPException, Request

from core.automation.planner import plan_dict
from core.chat.checkpoints import checkpoint_dict
from core.chat.usage import conversation_cache_stats
from infrastructure.database import (
    Activity,
    AgentRun,
    Checkpoint,
    Conversation,
    Message,
    Plan,
    PlanStep,
    SessionLocal,
    ToolRun,
)


router = APIRouter(prefix="/api")


def _run_state(session, run: AgentRun) -> dict:
    message = session.get(Message, run.input_message_id) if run.input_message_id else None
    has_checkpoint = (
        session.query(Checkpoint.id).filter(Checkpoint.run_id == run.id).first() is not None
    )
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "execution_mode": run.execution_mode,
        "status": run.status,
        "input_message": message.content if message else "",
        "error": run.error,
        "has_checkpoint": has_checkpoint,
        "created_at": run.created_at.isoformat(),
    }


def _load_plan(session, plan: Plan) -> dict:
    steps = (
        session.query(PlanStep)
        .filter(PlanStep.plan_id == plan.id)
        .order_by(PlanStep.version.asc(), PlanStep.position.asc())
        .all()
    )
    return plan_dict(plan, steps)


def _run_history_item(session, run: AgentRun) -> dict:
    message = session.get(Message, run.input_message_id) if run.input_message_id else None
    tools = (
        session.query(ToolRun)
        .filter(ToolRun.run_id == run.id)
        .order_by(ToolRun.step_index.asc(), ToolRun.created_at.asc())
        .all()
    )
    return {
        "id": run.id,
        "conversation_id": run.conversation_id,
        "execution_mode": run.execution_mode,
        "status": run.status,
        "input_message": message.content if message else "",
        "intent": run.intent_json,
        "context_stats": run.context_stats,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "tools": [
            {
                "id": tool.id,
                "tool": tool.tool,
                "args_summary": tool.args_summary,
                "result_summary": tool.result_summary,
                "risk_level": tool.risk_level,
                "status": tool.status,
                "duration_ms": tool.duration_ms,
            }
            for tool in tools
        ],
    }


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    with SessionLocal() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            raise HTTPException(404, "plan not found")
        return _load_plan(session, plan)


@router.get("/conversations/{conversation_id}/plans")
def conversation_plans(conversation_id: str):
    with SessionLocal() as session:
        if session.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        rows = (
            session.query(Plan)
            .filter(Plan.conversation_id == conversation_id)
            .order_by(Plan.created_at.desc())
            .limit(20)
            .all()
        )
        return [_load_plan(session, row) for row in rows]


@router.get("/conversations/{conversation_id}/runs/current")
def current_conversation_run(conversation_id: str):
    """返回前端需要处理的运行中/中断 Run；没有时返回 null。"""
    with SessionLocal() as session:
        if session.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        # 必须先取最新一次 Run，再判断是否需要处理。若先按状态筛选，
        # 新 Run 已完成后仍会捞出更早的 interrupted Run，导致恢复卡片常驻。
        run = (
            session.query(AgentRun)
            .filter(AgentRun.conversation_id == conversation_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .first()
        )
        return _run_state(session, run) if run and run.status in {"running", "interrupted"} else None


@router.get("/conversations/{conversation_id}/runs/stats")
def conversation_run_stats(conversation_id: str):
    """返回当前会话可持久化的 Run 统计。"""
    with SessionLocal() as session:
        if session.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        return conversation_cache_stats(session, conversation_id)


@router.get("/conversations/{conversation_id}/runs/history")
def conversation_run_history(conversation_id: str, limit: int = 50):
    """返回可用于折叠工作记录的历史 Run 摘要。"""
    with SessionLocal() as session:
        if session.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        rows = (
            session.query(AgentRun)
            .filter(AgentRun.conversation_id == conversation_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [_run_history_item(session, run) for run in rows]


@router.get("/activities/{activity_id}/plans")
def activity_plans(activity_id: str):
    with SessionLocal() as session:
        if session.get(Activity, activity_id) is None:
            raise HTTPException(404, "activity not found")
        rows = (
            session.query(Plan)
            .filter(Plan.activity_id == activity_id)
            .order_by(Plan.created_at.desc())
            .limit(20)
            .all()
        )
        return [_load_plan(session, row) for row in rows]


@router.get("/runs/{run_id}/checkpoints")
def run_checkpoints(run_id: str):
    with SessionLocal() as session:
        if session.get(AgentRun, run_id) is None:
            raise HTTPException(404, "run not found")
        rows = (
            session.query(Checkpoint)
            .filter(Checkpoint.run_id == run_id)
            .order_by(Checkpoint.sequence.desc())
            .limit(50)
            .all()
        )
        return [checkpoint_dict(row) for row in rows]


@router.get("/conversations/{conversation_id}/checkpoints")
def conversation_checkpoints(conversation_id: str):
    with SessionLocal() as session:
        if session.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        rows = (
            session.query(Checkpoint)
            .join(Plan, Plan.id == Checkpoint.plan_id)
            .filter(Plan.conversation_id == conversation_id)
            .order_by(Checkpoint.created_at.desc())
            .limit(20)
            .all()
        )
        return [checkpoint_dict(row) for row in rows]


@router.get("/capabilities")
def capabilities(request: Request):
    return request.app.state.capability_registry
