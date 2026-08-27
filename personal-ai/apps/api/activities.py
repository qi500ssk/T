"""Activity CRUD、状态转换与运行历史 API。"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from core.automation.activity import (
    ActivityConflictError,
    ActivityLimitError,
    ActivityNotFoundError,
    create_activity,
    delete_activity,
    get_activity,
    list_activities,
    pause_activity,
    resume_activity,
    run_activity_now,
    utc_datetime,
)
from infrastructure.database import Activity, AgentRun, SessionLocal
from infrastructure.config import settings


router = APIRouter(prefix="/api/activities", tags=["activities"])


class ActivityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=4000)
    schedule_type: Literal["once", "interval"]
    execution_mode: Literal["direct", "planned"] = "direct"
    interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    next_run_at: datetime
    agent_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.next_run_at.tzinfo is None or self.next_run_at.utcoffset() is None:
            raise ValueError("next_run_at 必须包含时区")
        if self.schedule_type == "once" and self.interval_minutes is not None:
            raise ValueError("一次性活动不能设置 interval_minutes")
        if self.schedule_type == "interval" and self.interval_minutes is None:
            raise ValueError("周期活动必须设置 interval_minutes")
        if not self.title.strip() or not self.prompt.strip():
            raise ValueError("标题和任务内容不能为空")
        return self


def _iso(value: datetime | None) -> str | None:
    return utc_datetime(value).isoformat() if value is not None else None


def activity_dict(row: Activity) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "conversation_id": row.conversation_id,
        "title": row.title,
        "prompt": row.prompt,
        "execution_mode": row.execution_mode,
        "schedule_type": row.schedule_type,
        "interval_minutes": row.interval_minutes,
        "next_run_at": _iso(row.next_run_at),
        "status": row.status,
        "last_run_id": row.last_run_id,
        "last_error": row.last_error,
        "last_started_at": _iso(row.last_started_at),
        "last_completed_at": _iso(row.last_completed_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _run_dict(row: AgentRun) -> dict:
    return {
        "id": row.id,
        "activity_id": row.activity_id,
        "conversation_id": row.conversation_id,
        "execution_mode": row.execution_mode,
        "status": row.status,
        "error": row.error,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "created_at": _iso(row.created_at),
        "completed_at": _iso(row.completed_at),
    }


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ActivityNotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, (ActivityConflictError, ActivityLimitError)):
        return HTTPException(409, str(exc))
    return HTTPException(422, str(exc))


@router.get("")
def list_activity_rows():
    return [activity_dict(row) for row in list_activities()]


@router.post("")
def create_activity_row(body: ActivityCreate, request: Request):
    if body.execution_mode == "planned" and not settings.planner_enabled:
        raise HTTPException(409, "planner is disabled")
    agents = request.app.state.runtime_settings_store.snapshot()["agents"]
    agent_id = body.agent_id or agents["active_agent_id"]
    if not any(item["id"] == agent_id for item in agents["items"]):
        raise HTTPException(404, "角色不存在")
    try:
        row = create_activity(
            title=body.title,
            prompt=body.prompt,
            schedule_type=body.schedule_type,
            execution_mode=body.execution_mode,
            interval_minutes=body.interval_minutes,
            next_run_at=body.next_run_at,
            agent_id=agent_id,
        )
    except (ValueError, ActivityLimitError) as exc:
        raise _http_error(exc) from None
    return activity_dict(row)


@router.get("/{activity_id}")
def get_activity_row(activity_id: str):
    try:
        return activity_dict(get_activity(activity_id))
    except ActivityNotFoundError as exc:
        raise _http_error(exc) from None


@router.get("/{activity_id}/runs")
def list_activity_runs(activity_id: str):
    try:
        get_activity(activity_id)
    except ActivityNotFoundError as exc:
        raise _http_error(exc) from None
    with SessionLocal() as session:
        rows = (
            session.query(AgentRun)
            .filter(AgentRun.activity_id == activity_id)
            .order_by(AgentRun.created_at.desc())
            .all()
        )
        return [_run_dict(row) for row in rows]


@router.post("/{activity_id}/pause")
def pause_activity_row(activity_id: str):
    try:
        return activity_dict(pause_activity(activity_id))
    except (ActivityNotFoundError, ActivityConflictError) as exc:
        raise _http_error(exc) from None


@router.post("/{activity_id}/resume")
def resume_activity_row(activity_id: str):
    try:
        return activity_dict(resume_activity(activity_id))
    except (ActivityNotFoundError, ActivityConflictError) as exc:
        raise _http_error(exc) from None


@router.post("/{activity_id}/run-now")
def run_activity_now_row(activity_id: str):
    try:
        return activity_dict(run_activity_now(activity_id))
    except (ActivityNotFoundError, ActivityConflictError) as exc:
        raise _http_error(exc) from None


@router.delete("/{activity_id}")
def delete_activity_row(activity_id: str):
    try:
        delete_activity(activity_id)
    except (ActivityNotFoundError, ActivityConflictError) as exc:
        raise _http_error(exc) from None
    return {"ok": True}
