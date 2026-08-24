"""自动任务域 Planner：结构化计划、持久化状态和一次性 Replan。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from infrastructure.database import Plan, PlanStep, SessionLocal


PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts" / "planning"
PLANNER_VERSION = "p6-v1"


class PlanValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DraftStep:
    title: str
    instruction: str
    tool_hints: tuple[str, ...]


@dataclass(frozen=True)
class PlanDraft:
    goal: str
    steps: tuple[DraftStep, ...]


def _json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise PlanValidationError("Planner 未返回可解析的 JSON 对象")


def _clean(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise PlanValidationError(f"{field} 必须是字符串")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", value).strip()
    if not text or len(text) > limit:
        raise PlanValidationError(f"{field} 长度不合法")
    return text


def parse_plan(
    text: str,
    allowed_tools: set[str],
    max_steps: int,
    *,
    min_steps: int = 2,
) -> PlanDraft:
    raw = _json_object(text)
    if set(raw) - {"goal", "steps"}:
        raise PlanValidationError("Planner 顶层包含未知字段")
    goal = _clean(raw.get("goal"), "goal", 4000)
    items = raw.get("steps")
    if not isinstance(items, list) or not min_steps <= len(items) <= max_steps:
        raise PlanValidationError(f"计划步骤数必须在 {min_steps}..{max_steps}")
    steps: list[DraftStep] = []
    fingerprints: set[tuple[str, str]] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or set(item) - {"title", "instruction", "tool_hints"}:
            raise PlanValidationError(f"第 {index} 步结构无效")
        title = _clean(item.get("title"), f"steps[{index}].title", 200)
        instruction = _clean(item.get("instruction"), f"steps[{index}].instruction", 1000)
        hints = item.get("tool_hints", [])
        if not isinstance(hints, list) or any(not isinstance(name, str) for name in hints):
            raise PlanValidationError(f"第 {index} 步 tool_hints 必须是字符串列表")
        unknown = set(hints) - allowed_tools
        if unknown:
            raise PlanValidationError(f"计划引用未授权工具：{', '.join(sorted(unknown))}")
        fingerprint = (title.casefold(), instruction.casefold())
        if fingerprint in fingerprints:
            raise PlanValidationError(f"第 {index} 步与前序步骤重复")
        fingerprints.add(fingerprint)
        steps.append(DraftStep(title, instruction, tuple(dict.fromkeys(hints))))
    return PlanDraft(goal, tuple(steps))


def _tool_payload(allowed_tools: set[str], tool_details: list[dict]) -> list[dict]:
    return [
        {"name": item["name"], "description": item["description"], "risk_level": item["risk_level"]}
        for item in tool_details
        if item.get("name") in allowed_tools
    ]


async def generate_plan(provider, goal: str, allowed_tools: set[str], tool_details: list[dict], max_steps: int) -> PlanDraft:
    payload = json.dumps(
        {"goal": goal, "available_tools": _tool_payload(allowed_tools, tool_details), "max_steps": max_steps},
        ensure_ascii=False,
    )
    result = await provider.complete(
        [
            {"role": "system", "content": (PROMPT_ROOT / "create.md").read_text(encoding="utf-8")},
            {"role": "user", "content": payload},
        ],
        temperature=0.0,
    )
    try:
        return parse_plan(result, allowed_tools, max_steps)
    except PlanValidationError as exc:
        repaired = await _repair_plan(
            provider,
            result,
            str(exc),
            allowed_tools,
            max_steps,
            min_steps=2,
        )
        return parse_plan(repaired, allowed_tools, max_steps)


async def generate_replan(
    provider,
    goal: str,
    completed: list[dict],
    blocked: dict,
    allowed_tools: set[str],
    tool_details: list[dict],
    max_steps: int,
) -> PlanDraft:
    payload = json.dumps(
        {
            "goal": goal,
            "completed_steps": completed,
            "blocked_step": blocked,
            "available_tools": _tool_payload(allowed_tools, tool_details),
            "max_steps": max_steps,
        },
        ensure_ascii=False,
    )
    result = await provider.complete(
        [
            {"role": "system", "content": (PROMPT_ROOT / "replan.md").read_text(encoding="utf-8")},
            {"role": "user", "content": payload},
        ],
        temperature=0.0,
    )
    try:
        return parse_plan(result, allowed_tools, max_steps, min_steps=1)
    except PlanValidationError as exc:
        repaired = await _repair_plan(
            provider,
            result,
            str(exc),
            allowed_tools,
            max_steps,
            min_steps=1,
        )
        return parse_plan(repaired, allowed_tools, max_steps, min_steps=1)


async def _repair_plan(
    provider,
    invalid_output: str,
    validation_error: str,
    allowed_tools: set[str],
    max_steps: int,
    *,
    min_steps: int,
) -> str:
    """格式错误时只修复一次；修复结果仍由同一严格解析器裁决。"""
    payload = json.dumps(
        {
            "validation_error": validation_error,
            "invalid_output": invalid_output[:12000],
            "allowed_tools": sorted(allowed_tools),
            "min_steps": min_steps,
            "max_steps": max_steps,
        },
        ensure_ascii=False,
    )
    return await provider.complete(
        [
            {
                "role": "system",
                "content": (PROMPT_ROOT / "repair.md").read_text(encoding="utf-8"),
            },
            {"role": "user", "content": payload},
        ],
        temperature=0.0,
    )


def create_planning_record(
    run_id: str, conversation_id: str, activity_id: str | None, goal: str
) -> Plan:
    with SessionLocal() as session:
        plan = Plan(
            run_id=run_id,
            conversation_id=conversation_id,
            activity_id=activity_id,
            goal=goal[:4000],
            status="planning",
            planner_version=PLANNER_VERSION,
        )
        session.add(plan)
        session.commit()
        return plan


def populate_plan(plan_id: str, draft: PlanDraft) -> tuple[Plan, list[PlanStep]]:
    with SessionLocal() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            raise LookupError("plan not found")
        plan.status = "running"
        steps = _add_steps(session, plan.id, 1, draft.steps)
        session.commit()
        return plan, steps


def _add_steps(session, plan_id: str, version: int, drafts: tuple[DraftStep, ...]) -> list[PlanStep]:
    rows = [
        PlanStep(
            plan_id=plan_id, version=version, position=index, title=step.title,
            instruction=step.instruction, tool_hints=list(step.tool_hints) or None,
        )
        for index, step in enumerate(drafts, start=1)
    ]
    session.add_all(rows)
    session.flush()
    return rows


def set_step_running(step_id: str) -> PlanStep:
    with SessionLocal() as session:
        row = session.get(PlanStep, step_id)
        if row is None:
            raise LookupError("plan step not found")
        row.status = "running"
        row.started_at = datetime.now(timezone.utc)
        session.commit()
        return row


def finish_step(step_id: str, status: str, output: str = "", error: str = "") -> PlanStep:
    with SessionLocal() as session:
        row = session.get(PlanStep, step_id)
        if row is None:
            raise LookupError("plan step not found")
        row.status = status
        row.output_summary = output[:2000] or None
        row.error = error[:1000] or None
        row.completed_at = datetime.now(timezone.utc)
        session.commit()
        return row


def apply_replan(plan_id: str, draft: PlanDraft) -> tuple[Plan, list[PlanStep]]:
    with SessionLocal() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            raise LookupError("plan not found")
        current = (
            session.query(PlanStep)
            .filter(PlanStep.plan_id == plan_id, PlanStep.version == plan.current_version)
            .all()
        )
        for row in current:
            if row.status in {"pending", "blocked"}:
                row.status = "superseded"
        plan.current_version += 1
        plan.replan_count += 1
        plan.updated_at = datetime.now(timezone.utc)
        steps = _add_steps(session, plan.id, plan.current_version, draft.steps)
        session.commit()
        return plan, steps


def finish_plan(plan_id: str, status: str, error: str = "") -> Plan:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            raise LookupError("plan not found")
        plan.status = status
        plan.error = error[:1000] or None
        plan.updated_at = now
        plan.completed_at = now
        if status in {"failed", "cancelled"}:
            for step in session.query(PlanStep).filter(PlanStep.plan_id == plan.id).all():
                if step.status == "running":
                    step.status = status
                    step.error = error[:1000] or None
                    step.completed_at = now
                elif step.status == "pending":
                    step.status = "cancelled"
                    step.completed_at = now
        session.commit()
        return plan


def cancel_plan_for_run(run_id: str) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        plan = session.query(Plan).filter(Plan.run_id == run_id).first()
        if plan is None or plan.status not in {"planning", "running"}:
            return
        plan.status = "cancelled"
        plan.completed_at = now
        for step in session.query(PlanStep).filter(PlanStep.plan_id == plan.id).all():
            if step.status in {"pending", "running"}:
                step.status = "cancelled"
                step.completed_at = now
        session.commit()


def plan_dict(plan: Plan, steps: list[PlanStep]) -> dict:
    def iso(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return {
        "id": plan.id, "run_id": plan.run_id, "conversation_id": plan.conversation_id,
        "activity_id": plan.activity_id, "goal": plan.goal, "status": plan.status,
        "current_version": plan.current_version, "replan_count": plan.replan_count,
        "error": plan.error, "planner_version": plan.planner_version,
        "created_at": iso(plan.created_at), "updated_at": iso(plan.updated_at),
        "completed_at": iso(plan.completed_at),
        "steps": [
            {
                "id": row.id, "version": row.version, "position": row.position,
                "title": row.title, "instruction": row.instruction,
                "tool_hints": row.tool_hints or [], "status": row.status,
                "output_summary": row.output_summary, "error": row.error,
                "started_at": iso(row.started_at), "completed_at": iso(row.completed_at),
            }
            for row in steps
        ],
    }
