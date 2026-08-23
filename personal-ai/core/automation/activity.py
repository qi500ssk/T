"""自动任务域 Activity 持久化调度与单进程后台 Worker。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from functools import partial

import anyio

from core.chat.agent import run_chat
from core.capabilities.skills import Skill
from infrastructure.config import settings
from infrastructure.database import (
    Activity,
    AgentRun,
    Conversation,
    Plan,
    PlanStep,
    SessionLocal,
)


logger = logging.getLogger(__name__)
MAX_ACTIVITIES = 100
MAX_ERROR_CHARS = 1000
RECOVERY_MESSAGE = "上次运行被服务重启中断，已重新排队"


class ActivityNotFoundError(LookupError):
    pass


class ActivityConflictError(RuntimeError):
    pass


class ActivityLimitError(RuntimeError):
    pass


def utc_datetime(value: datetime) -> datetime:
    """兼容数据库驱动返回的 naive 时间，并明确按 UTC 处理。"""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_activity(
    *,
    title: str,
    prompt: str,
    schedule_type: str,
    next_run_at: datetime,
    interval_minutes: int | None = None,
    execution_mode: str = "direct",
    user_id: str = "default",
) -> Activity:
    """在一个事务中创建 Activity 及其专属会话。"""
    title = title.strip()
    prompt = prompt.strip()
    if not 1 <= len(title) <= 200:
        raise ValueError("title must contain 1..200 characters")
    if not 1 <= len(prompt) <= 4000:
        raise ValueError("prompt must contain 1..4000 characters")
    if schedule_type not in {"once", "interval"}:
        raise ValueError("invalid schedule_type")
    if execution_mode not in {"direct", "planned"}:
        raise ValueError("invalid execution_mode")
    if schedule_type == "once" and interval_minutes is not None:
        raise ValueError("once activity cannot have interval_minutes")
    if schedule_type == "interval" and not (
        interval_minutes is not None and 1 <= interval_minutes <= 10080
    ):
        raise ValueError("interval_minutes must be between 1 and 10080")

    with SessionLocal() as session:
        count = session.query(Activity).filter(Activity.user_id == user_id).count()
        if count >= MAX_ACTIVITIES:
            raise ActivityLimitError("最多只能创建 100 个活动")
        conversation = Conversation(user_id=user_id, title=f"活动：{title}"[:200])
        session.add(conversation)
        session.flush()
        activity = Activity(
            user_id=user_id,
            conversation_id=conversation.id,
            title=title,
            prompt=prompt,
            execution_mode=execution_mode,
            schedule_type=schedule_type,
            interval_minutes=interval_minutes,
            next_run_at=utc_datetime(next_run_at),
            status="scheduled",
        )
        session.add(activity)
        session.commit()
        return activity


def list_activities(user_id: str = "default") -> list[Activity]:
    with SessionLocal() as session:
        return (
            session.query(Activity)
            .filter(Activity.user_id == user_id)
            .order_by(Activity.created_at.desc())
            .all()
        )


def get_activity(activity_id: str, user_id: str = "default") -> Activity:
    with SessionLocal() as session:
        row = session.get(Activity, activity_id)
        if row is None or row.user_id != user_id:
            raise ActivityNotFoundError("activity not found")
        return row


def pause_activity(activity_id: str, user_id: str = "default") -> Activity:
    return _transition(activity_id, {"scheduled"}, "paused", user_id=user_id)


def resume_activity(activity_id: str, user_id: str = "default") -> Activity:
    return _transition(activity_id, {"paused"}, "scheduled", user_id=user_id)


def run_activity_now(
    activity_id: str,
    user_id: str = "default",
    now: datetime | None = None,
) -> Activity:
    return _transition(
        activity_id,
        {"scheduled", "completed", "failed"},
        "scheduled",
        user_id=user_id,
        next_run_at=utc_datetime(now or utc_now()),
    )


def delete_activity(activity_id: str, user_id: str = "default") -> None:
    with SessionLocal() as session:
        row = session.get(Activity, activity_id)
        if row is None or row.user_id != user_id:
            raise ActivityNotFoundError("activity not found")
        if row.status == "running":
            raise ActivityConflictError("运行中的活动不能删除")
        session.delete(row)
        session.commit()


def _transition(
    activity_id: str,
    allowed_from: set[str],
    target: str,
    *,
    user_id: str,
    next_run_at: datetime | None = None,
) -> Activity:
    with SessionLocal() as session:
        row = session.get(Activity, activity_id)
        if row is None or row.user_id != user_id:
            raise ActivityNotFoundError("activity not found")
        if row.status not in allowed_from:
            raise ActivityConflictError(f"不能从 {row.status} 状态执行此操作")
        row.status = target
        if next_run_at is not None:
            row.next_run_at = next_run_at
        row.updated_at = utc_now()
        session.commit()
        return row


def _claim_due_activity(now: datetime | None = None) -> Activity | None:
    """单 Worker 短事务领取最早的到期 Activity。"""
    current = utc_datetime(now or utc_now())
    with SessionLocal() as session:
        row = (
            session.query(Activity)
            .filter(Activity.status == "scheduled", Activity.next_run_at <= current)
            .order_by(Activity.next_run_at.asc(), Activity.created_at.asc())
            .first()
        )
        if row is None:
            return None
        row.status = "running"
        row.last_started_at = current
        row.last_error = None
        row.updated_at = current
        session.commit()
        return row


def _record_last_run(activity_id: str, run_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(Activity, activity_id)
        if row is not None and row.status == "running":
            row.last_run_id = run_id
            row.updated_at = utc_now()
            session.commit()


def _finish_activity(
    activity_id: str,
    *,
    succeeded: bool,
    error: str | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> Activity | None:
    completed_at = utc_datetime(now or utc_now())
    with SessionLocal() as session:
        row = session.get(Activity, activity_id)
        if row is None:
            return None
        if run_id:
            row.last_run_id = run_id
        row.last_error = None if succeeded else (error or "运行失败")[:MAX_ERROR_CHARS]
        row.last_completed_at = completed_at
        row.updated_at = completed_at
        if row.schedule_type == "interval" and row.interval_minutes:
            interval = timedelta(minutes=row.interval_minutes)
            next_run = utc_datetime(row.next_run_at)
            if next_run <= completed_at:
                elapsed = completed_at - next_run
                steps = int(elapsed.total_seconds() // interval.total_seconds()) + 1
                next_run += interval * steps
            row.next_run_at = next_run
            row.status = "scheduled"
        else:
            row.status = "completed" if succeeded else "failed"
        session.commit()
        return row


def recover_interrupted_activities(now: datetime | None = None) -> int:
    """把上次进程中断遗留的 running Activity 重新排队。"""
    current = utc_datetime(now or utc_now())
    with SessionLocal() as session:
        rows = session.query(Activity).filter(Activity.status == "running").all()
        for row in rows:
            interrupted_runs = (
                session.query(AgentRun)
                .filter(AgentRun.activity_id == row.id, AgentRun.status == "running")
                .all()
            )
            for run in interrupted_runs:
                run.status = "cancelled"
                run.error = RECOVERY_MESSAGE
                run.completed_at = current
                plan = session.query(Plan).filter(Plan.run_id == run.id).first()
                if plan is not None and plan.status in {"planning", "running"}:
                    plan.status = "cancelled"
                    plan.error = RECOVERY_MESSAGE
                    plan.completed_at = current
                    for step in (
                        session.query(PlanStep).filter(PlanStep.plan_id == plan.id).all()
                    ):
                        if step.status in {"pending", "running"}:
                            step.status = "cancelled"
                            step.completed_at = current
            row.status = "scheduled"
            row.next_run_at = min(utc_datetime(row.next_run_at), current)
            row.last_error = RECOVERY_MESSAGE
            row.updated_at = current
        session.commit()
        return len(rows)


async def _run_activity(
    activity: Activity,
    provider,
    embedding_provider,
    skills: list[Skill],
    agent_profile: dict | None = None,
    mcp_clients: list | None = None,
) -> None:
    run_id: str | None = None
    succeeded = False
    error = "Agent Run 未正常完成"
    try:
        async for event in run_chat(
            provider,
            activity.conversation_id,
            activity.prompt,
            user_id=activity.user_id,
            embedding_provider=embedding_provider,
            skills=skills,
            activity_id=activity.id,
            approval_mode="deny",
            execution_mode=activity.execution_mode,
            agent_profile=agent_profile,
            mcp_clients=mcp_clients,
            context_window_tokens=settings.llm_context_window_tokens,
            max_output_tokens=settings.llm_max_output_tokens,
        ):
            if event.type == "run.started":
                run_id = str(event.data["run_id"])
                await anyio.to_thread.run_sync(_record_last_run, activity.id, run_id)
            elif event.type == "run.completed":
                succeeded = True
                error = ""
            elif event.type == "run.failed":
                error = str(event.data.get("error") or error)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Activity 执行失败 activity_id=%s", activity.id)
        error = str(exc)

    await anyio.to_thread.run_sync(
        partial(
            _finish_activity,
            activity.id,
            succeeded=succeeded,
            error=error,
            run_id=run_id,
        )
    )


async def _wait_for_poll(stop_event: asyncio.Event) -> None:
    poll_seconds = min(max(int(settings.activity_poll_seconds), 1), 60)
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
    except TimeoutError:
        pass


async def activity_worker(
    stop_event: asyncio.Event,
    provider,
    embedding_provider,
    skills: list[Skill],
    agent_profile: dict | None = None,
    mcp_manager=None,
) -> None:
    """串行领取并执行 Activity；单个任务或数据库失败不会终止 Worker。"""
    while not stop_event.is_set():
        try:
            activity = await anyio.to_thread.run_sync(_claim_due_activity)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Activity Worker 查询到期任务失败")
            await _wait_for_poll(stop_event)
            continue

        if activity is None:
            await _wait_for_poll(stop_event)
            continue
        try:
            await _run_activity(
                activity,
                provider,
                embedding_provider,
                skills,
                agent_profile,
                mcp_manager.clients if mcp_manager is not None else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Activity Worker 未能完成任务收尾 activity_id=%s", activity.id)
