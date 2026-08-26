"""计划 Run 的持久化恢复点、启动恢复和安全工作区摘要。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.execution.workspace import current_coding_workspace
from infrastructure.database import (
    AgentRun,
    Checkpoint,
    Plan,
    PlanStep,
    SessionLocal,
    ToolRun,
)


MAX_CHECKPOINT_JSON_BYTES = 64 * 1024
MAX_SNAPSHOT_FILES = 50


def _bounded_json(value: dict) -> dict:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_CHECKPOINT_JSON_BYTES:
        raise ValueError("Checkpoint 状态超过 64 KiB 上限")
    return json.loads(encoded.decode("utf-8"))


def _git_head(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
        if value.startswith("ref: "):
            ref = root / ".git" / value[5:]
            return ref.read_text(encoding="utf-8").strip() if ref.is_file() else value
        return value or None
    except (OSError, UnicodeError):
        return None


def capture_workspace_snapshot(relevant_files: list[str] | None = None) -> dict:
    """只保存路径和哈希，不读取到数据库中的文件正文。"""
    root = current_coding_workspace()
    if root is None:
        return {
            "files": [],
            "git_head": None,
            "worktree_status": None,
            "artifact_refs": [],
            "diff_refs": [],
        }
    files: list[dict] = []
    for raw in list(dict.fromkeys(relevant_files or []))[:MAX_SNAPSHOT_FILES]:
        candidate = (root / raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            continue
        files.append({"path": candidate.relative_to(root).as_posix(), "sha256": digest})
    return {
        "files": files,
        "git_head": _git_head(root),
        "worktree_status": None,
        "artifact_refs": [],
        "diff_refs": [],
    }


def create_checkpoint(
    run_id: str,
    plan_id: str,
    step_id: str | None,
    state: dict,
    status: str,
    *,
    workspace_snapshot: dict | None = None,
) -> Checkpoint:
    with SessionLocal() as session:
        run = session.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
        if run is None:
            raise LookupError("agent run not found")
        sequence = int(
            session.query(func.coalesce(func.max(Checkpoint.sequence), 0))
            .filter(Checkpoint.run_id == run_id)
            .scalar()
        ) + 1
        snapshot = workspace_snapshot or capture_workspace_snapshot(
            [str(item) for item in state.get("relevant_files", []) if isinstance(item, str)]
        )
        row = Checkpoint(
            run_id=run_id,
            plan_id=plan_id,
            step_id=step_id,
            sequence=sequence,
            state_json=_bounded_json(state),
            workspace_snapshot_json=_bounded_json(snapshot),
            capability_version=run.capability_version,
            status=status,
        )
        session.add(row)
        session.commit()
        return row


def checkpoint_dict(row: Checkpoint) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "plan_id": row.plan_id,
        "step_id": row.step_id,
        "sequence": row.sequence,
        "state": row.state_json or {},
        "workspace_snapshot": row.workspace_snapshot_json or {},
        "capability_version": row.capability_version,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def latest_checkpoint(run_id: str, session: Session | None = None) -> Checkpoint | None:
    owns_session = session is None
    session = session or SessionLocal()
    try:
        return (
            session.query(Checkpoint)
            .filter(Checkpoint.run_id == run_id)
            .order_by(Checkpoint.sequence.desc())
            .first()
        )
    finally:
        if owns_session:
            session.close()


def recover_interrupted_runs() -> int:
    """启动时释放遗留 running Run，并让未完成工具调用失效。"""
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        runs = session.query(AgentRun).filter(AgentRun.status == "running").all()
        for run in runs:
            run.status = "interrupted"
            run.error = "应用重启或运行进程中断"
            run.completed_at = None
            plan = session.query(Plan).filter(Plan.run_id == run.id).first()
            current_step = None
            if plan and plan.status in {"planning", "running"}:
                plan.status = "interrupted"
                plan.error = run.error
                plan.completed_at = None
                current_step = (
                    session.query(PlanStep)
                    .filter(PlanStep.plan_id == plan.id, PlanStep.status == "running")
                    .order_by(PlanStep.version.desc(), PlanStep.position.asc())
                    .first()
                )
                if current_step:
                    current_step.status = "interrupted"
            pending_tools = (
                session.query(ToolRun)
                .filter(
                    ToolRun.run_id == run.id,
                    ToolRun.status.in_(["running", "pending_approval"]),
                )
                .all()
            )
            for tool_run in pending_tools:
                tool_run.status = "interrupted"
                tool_run.approval_id = None
                tool_run.completed_at = now
            session.flush()
            if plan:
                completed = (
                    session.query(PlanStep)
                    .filter(
                        PlanStep.plan_id == plan.id,
                        PlanStep.version == plan.current_version,
                        PlanStep.status == "completed",
                    )
                    .order_by(PlanStep.position.asc())
                    .all()
                )
                sequence = int(
                    session.query(func.coalesce(func.max(Checkpoint.sequence), 0))
                    .filter(Checkpoint.run_id == run.id)
                    .scalar()
                ) + 1
                session.add(
                    Checkpoint(
                        run_id=run.id,
                        plan_id=plan.id,
                        step_id=current_step.id if current_step else None,
                        sequence=sequence,
                        state_json={
                            "goal": plan.goal,
                            "plan_version": plan.current_version,
                            "current_step": current_step.position if current_step else None,
                            "completed_steps": [row.position for row in completed],
                            "pending_approval_id": None,
                            "last_observation": run.error,
                        },
                        workspace_snapshot_json=capture_workspace_snapshot(),
                        capability_version=run.capability_version,
                        status="interrupted",
                    )
                )
        session.commit()
        return len(runs)


def interrupt_run(run_id: str, reason: str) -> None:
    """把非用户主动取消的 planned Run 留在可恢复状态。"""
    checkpoint_payload: tuple[str, str | None, dict] | None = None
    with SessionLocal() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status != "running":
            return
        run.status = "interrupted"
        run.error = reason[:1000]
        run.completed_at = None
        plan = session.query(Plan).filter(Plan.run_id == run_id).first()
        current_step = None
        if plan:
            plan.status = "interrupted"
            plan.error = run.error
            plan.completed_at = None
            current_step = (
                session.query(PlanStep)
                .filter(PlanStep.plan_id == plan.id, PlanStep.status == "running")
                .first()
            )
            if current_step:
                current_step.status = "interrupted"
            checkpoint_payload = (
                plan.id,
                current_step.id if current_step else None,
                {
                    "goal": plan.goal,
                    "plan_version": plan.current_version,
                    "current_step": current_step.position if current_step else None,
                    "completed_steps": [],
                    "pending_approval_id": None,
                    "last_observation": reason,
                },
            )
        for tool_run in session.query(ToolRun).filter(
            ToolRun.run_id == run_id,
            ToolRun.status.in_(["running", "pending_approval"]),
        ):
            tool_run.status = "interrupted"
            tool_run.approval_id = None
            tool_run.completed_at = datetime.now(timezone.utc)
        session.commit()
    if checkpoint_payload:
        plan_id, step_id, state = checkpoint_payload
        create_checkpoint(
            run_id,
            plan_id,
            step_id,
            state,
            "interrupted",
        )
