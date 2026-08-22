"""Plan 历史与只读 Capability API。"""

from fastapi import APIRouter, HTTPException, Request

from core.automation.planner import plan_dict
from infrastructure.database import Activity, Conversation, Plan, PlanStep, SessionLocal


router = APIRouter(prefix="/api")


def _load_plan(session, plan: Plan) -> dict:
    steps = (
        session.query(PlanStep)
        .filter(PlanStep.plan_id == plan.id)
        .order_by(PlanStep.version.asc(), PlanStep.position.asc())
        .all()
    )
    return plan_dict(plan, steps)


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


@router.get("/capabilities")
def capabilities(request: Request):
    return request.app.state.capability_registry
