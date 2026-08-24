"""执行域共享循环：direct 与 planned Run 使用同一安全链路。"""

from __future__ import annotations

import json
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

import anyio

from core.execution.permissions import create_approval, wait_for_approval
from core.chat.checkpoints import create_checkpoint
from core.execution.tool_pipeline import ToolInvocation, run_post_tool_hooks, run_pre_tool_hooks
from core.execution.tools import TOOLS, ToolValidationError, execute_tool, prepare_tool
from infrastructure.config import settings
from infrastructure.database import SessionLocal, ToolRun


logger = logging.getLogger(__name__)
MAX_SUMMARY_CHARS = 500
MAX_ARGS_SUMMARY_CHARS = 300
STEP_LIMIT_REPLY = "已达到工具调用步骤上限，请缩小任务范围后重试。"
_BLOCKED_PROTOCOL_TAGS = (
    "source",
    "tool_call",
    "tool_calls",
    "function_call",
    "function_calls",
)


@dataclass
class ExecutorEvent:
    type: str
    data: dict = field(default_factory=dict)


@dataclass
class ToolCallBudget:
    remaining: int
    used: int = 0


@dataclass(frozen=True)
class ToolRunReservation:
    id: str
    reused: bool = False
    result: str = ""


class ProtocolLeakFilter:
    """流式移除模型误复述的内部 RAG/工具协议，同时保留普通 Markdown 代码。"""

    def __init__(self) -> None:
        self._state = "text"
        self._pending = ""
        self._tag = ""
        self._close_tail = ""
        self._in_code_fence = False
        self._backticks = 0

    def feed(self, text: str) -> str:
        visible: list[str] = []
        for char in text:
            if self._state == "blocked":
                close = f"</{self._tag}>"
                self._close_tail = (self._close_tail + char)[-len(close):]
                if self._close_tail.lower() == close:
                    self._state = "text"
                    self._tag = ""
                    self._close_tail = ""
                continue

            if self._state == "opening":
                self._pending += char
                if char == ">":
                    if self._pending.rstrip().endswith("/>"):
                        self._state = "text"
                        self._tag = ""
                    else:
                        self._state = "blocked"
                    self._pending = ""
                continue

            if self._pending:
                self._pending += char
                lowered = self._pending.lower()
                prefixes = [f"<{tag}" for tag in _BLOCKED_PROTOCOL_TAGS]
                if any(prefix.startswith(lowered) for prefix in prefixes):
                    continue
                matched_tag = next(
                    (
                        tag
                        for tag in _BLOCKED_PROTOCOL_TAGS
                        if lowered.startswith(f"<{tag}")
                        and lowered[len(tag) + 1 : len(tag) + 2]
                        in {" ", "\t", "\r", "\n", ">", "/"}
                    ),
                    None,
                )
                if matched_tag:
                    self._tag = matched_tag
                    if char == ">":
                        self._state = "blocked"
                        self._pending = ""
                    else:
                        self._state = "opening"
                    continue
                visible.append(self._pending)
                self._pending = ""
                continue

            if char == "`":
                visible.append(char)
                self._backticks += 1
                if self._backticks == 3:
                    self._in_code_fence = not self._in_code_fence
                    self._backticks = 0
                continue
            self._backticks = 0
            if self._in_code_fence:
                visible.append(char)
                continue
            if char == "<":
                self._pending = char
            else:
                visible.append(char)
        return "".join(visible)

    def finish(self) -> str:
        if self._state == "text":
            tail = self._pending
            self._pending = ""
            return tail
        self._pending = ""
        return ""


def merge_tool_call_deltas(target: dict[int, dict], deltas: list[dict]) -> None:
    for delta in deltas:
        index = int(delta.get("index", 0))
        item = target.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if delta.get("id"):
            item["id"] += str(delta["id"])
        if delta.get("type"):
            item["type"] = str(delta["type"])
        function = delta.get("function") or {}
        if function.get("name"):
            item["function"]["name"] += str(function["name"])
        if function.get("arguments"):
            item["function"]["arguments"] += str(function["arguments"])


def finalize_tool_calls(items: dict[int, dict]) -> list[dict]:
    calls: list[dict] = []
    for _, item in sorted(items.items()):
        if not item["id"]:
            item["id"] = f"tool-{uuid.uuid4().hex}"
        calls.append(item)
    return calls


def _args_summary(tool: str, args: object) -> str:
    if not isinstance(args, dict):
        return "参数格式错误"
    if tool in {"write_file", "code_create_file"}:
        path = str(args.get("path", ""))
        content = args.get("content", "")
        size = len(content.encode("utf-8")) if isinstance(content, str) else 0
        return f"path={path!r}, content_bytes={size}"
    if tool == "code_edit":
        path = str(args.get("path", ""))
        old = args.get("old_text", "")
        new = args.get("new_text", "")
        old_size = len(old.encode("utf-8")) if isinstance(old, str) else 0
        new_size = len(new.encode("utf-8")) if isinstance(new, str) else 0
        return f"path={path!r}, old_bytes={old_size}, new_bytes={new_size}"
    return json.dumps(args, ensure_ascii=False, sort_keys=True)[:MAX_ARGS_SUMMARY_CHARS]


def _cached_prompt_tokens(raw_usage: dict) -> int | None:
    """兼容 OpenAI 与 DeepSeek 风格的提示词缓存统计字段。"""
    details = raw_usage.get("prompt_tokens_details")
    if isinstance(details, dict) and "cached_tokens" in details:
        return int(details.get("cached_tokens") or 0)
    for key in ("prompt_cache_hit_tokens", "cached_prompt_tokens"):
        if key in raw_usage:
            return int(raw_usage.get(key) or 0)
    return None


async def execute_model_loop(
    provider,
    messages: list[dict],
    schemas: list[dict] | None,
    allowed_tools: set[str],
    run_id: str,
    conversation_id: str,
    *,
    approval_mode: Literal["interactive", "deny"] = "interactive",
    max_turns: int,
    tool_budget: ToolCallBudget,
    plan_id: str | None = None,
    plan_version: int | None = None,
    plan_step_id: str | None = None,
    checkpoint_state: dict | None = None,
) -> AsyncIterator[ExecutorEvent]:
    """执行有限模型/工具循环，最后产生仅供 Agent 消费的 executor.completed。"""
    reply_parts: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    failures = 0
    successes = 0

    for round_index in range(max_turns):
        turn_text: list[str] = []
        tool_deltas: dict[int, dict] = {}
        protocol_filter = ProtocolLeakFilter()
        async for chunk in provider.stream(messages, tools=schemas):
            if chunk.text:
                visible_text = protocol_filter.feed(chunk.text)
                if visible_text:
                    turn_text.append(visible_text)
                    reply_parts.append(visible_text)
                    yield ExecutorEvent("message.delta", {"content": visible_text})
            if chunk.tool_calls_delta:
                merge_tool_call_deltas(tool_deltas, chunk.tool_calls_delta)
            if chunk.usage:
                usage["prompt_tokens"] += int(chunk.usage.get("prompt_tokens", 0))
                usage["completion_tokens"] += int(chunk.usage.get("completion_tokens", 0))
                cached_tokens = _cached_prompt_tokens(chunk.usage)
                if cached_tokens is not None:
                    usage["cached_prompt_tokens"] = (
                        int(usage.get("cached_prompt_tokens", 0)) + cached_tokens
                    )

        visible_tail = protocol_filter.finish()
        if visible_tail:
            turn_text.append(visible_tail)
            reply_parts.append(visible_tail)
            yield ExecutorEvent("message.delta", {"content": visible_tail})

        tool_calls = finalize_tool_calls(tool_deltas)
        if not tool_calls:
            break
        if round_index == max_turns - 1:
            reply_parts.append(STEP_LIMIT_REPLY)
            yield ExecutorEvent("message.delta", {"content": STEP_LIMIT_REPLY})
            failures += 1
            break

        messages.append(
            {"role": "assistant", "content": "".join(turn_text) or None, "tool_calls": tool_calls}
        )
        limit_announced = False
        for call in tool_calls:
            step_index = tool_budget.used
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw_arguments = str(function.get("arguments") or "{}")
            try:
                args = json.loads(raw_arguments)
            except json.JSONDecodeError:
                args = None
            tool = TOOLS.get(name)
            risk = tool.risk_level if tool else "unknown"
            summary = _args_summary(name, args)
            started = time.perf_counter()

            try:
                validated_tool, validated_args = prepare_tool(name, args, allowed_tools)
            except ToolValidationError as exc:
                if tool_budget.remaining <= 0:
                    result = STEP_LIMIT_REPLY
                    if not limit_announced:
                        reply_parts.append(STEP_LIMIT_REPLY)
                        yield ExecutorEvent("message.delta", {"content": STEP_LIMIT_REPLY})
                        limit_announced = True
                    failures += 1
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                    continue
                tool_budget.remaining -= 1
                tool_budget.used += 1
                result = f"工具错误：{exc}"
                tool_run = await _create_tool_run(
                    run_id, conversation_id, call["id"], step_index, name or "unknown",
                    summary, risk, "failed",
                )
                await _finish_tool_run(
                    tool_run.id, "failed", result, int((time.perf_counter() - started) * 1000)
                )
                failures += 1
                yield ExecutorEvent(
                    "tool.completed", _tool_event(run_id, step_index, name, summary, result, "failed")
                )
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                continue

            invocation = ToolInvocation.create(
                run_id,
                conversation_id,
                step_index,
                name,
                validated_args,
                validated_tool.risk_level,
            )
            policy_denial = await run_pre_tool_hooks(invocation)
            if policy_denial:
                if tool_budget.remaining <= 0:
                    if not limit_announced:
                        reply_parts.append(STEP_LIMIT_REPLY)
                        yield ExecutorEvent("message.delta", {"content": STEP_LIMIT_REPLY})
                        limit_announced = True
                    failures += 1
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": STEP_LIMIT_REPLY}
                    )
                    continue
                tool_budget.remaining -= 1
                tool_budget.used += 1
                tool_run = await _create_tool_run(
                    run_id,
                    conversation_id,
                    call["id"],
                    step_index,
                    name,
                    summary,
                    validated_tool.risk_level,
                    "rejected",
                )
                await _finish_tool_run(
                    tool_run.id,
                    "rejected",
                    policy_denial,
                    int((time.perf_counter() - started) * 1000),
                )
                failures += 1
                yield ExecutorEvent(
                    "tool.completed",
                    _tool_event(
                        run_id, step_index, name, summary, policy_denial, "rejected"
                    ),
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": policy_denial}
                )
                continue

            yield ExecutorEvent(
                "tool.proposed",
                {
                    "run_id": run_id,
                    "step_index": step_index,
                    "tool": name,
                    "args_summary": summary,
                    "risk_level": validated_tool.risk_level,
                    "effect": validated_tool.description,
                    "requires_approval": validated_tool.risk_level == "high",
                },
            )

            background_rejected = validated_tool.risk_level == "high" and approval_mode == "deny"
            idempotency_key = _tool_idempotency_key(
                run_id,
                plan_version,
                plan_step_id,
                name,
                validated_args,
            )
            if idempotency_key:
                cached = await _completed_tool_run(idempotency_key)
                if cached is not None:
                    successes += 1
                    yield ExecutorEvent(
                        "tool.reused",
                        {
                            **_tool_event(
                                run_id,
                                step_index,
                                name,
                                summary,
                                cached.result_summary or "",
                                "completed",
                            ),
                            "idempotency_key": idempotency_key,
                            "reused": True,
                        },
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": cached.result_summary or "工具已在中断前完成",
                        }
                    )
                    continue
            if tool_budget.remaining <= 0:
                if not limit_announced:
                    reply_parts.append(STEP_LIMIT_REPLY)
                    yield ExecutorEvent("message.delta", {"content": STEP_LIMIT_REPLY})
                    limit_announced = True
                failures += 1
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": STEP_LIMIT_REPLY}
                )
                continue
            tool_budget.remaining -= 1
            tool_budget.used += 1
            approval_id = None
            initial_status = (
                "rejected" if background_rejected else
                "pending_approval" if validated_tool.risk_level == "high" else "running"
            )
            if validated_tool.risk_level == "high" and not background_rejected:
                approval_id = create_approval(run_id)
            tool_run = await _create_tool_run(
                run_id, conversation_id, call["id"], step_index, name, summary,
                validated_tool.risk_level, initial_status, approval_id,
                plan_version=plan_version,
                plan_step_id=plan_step_id,
                idempotency_key=idempotency_key,
            )

            if background_rejected:
                result = "后台任务不能执行需要用户审批的工具"
                await _finish_tool_run(
                    tool_run.id, "rejected", result, int((time.perf_counter() - started) * 1000)
                )
                failures += 1
                yield ExecutorEvent(
                    "tool.completed", _tool_event(run_id, step_index, name, summary, result, "rejected")
                )
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                continue

            if approval_id:
                if plan_id and plan_step_id:
                    state = dict(checkpoint_state or {})
                    state.update(
                        {
                            "pending_approval_id": approval_id,
                            "pending_tool": name,
                            "pending_tool_run_id": tool_run.id,
                        }
                    )
                    await anyio.to_thread.run_sync(
                        create_checkpoint,
                        run_id,
                        plan_id,
                        plan_step_id,
                        state,
                        "awaiting_approval",
                    )
                yield ExecutorEvent("approval.required", {
                    "approval_id": approval_id, "run_id": run_id,
                    "step_index": step_index, "tool": name,
                    "args_summary": summary, "risk_level": validated_tool.risk_level,
                    "effect": validated_tool.description,
                })
                approved = await wait_for_approval(approval_id, settings.approval_timeout_seconds)
                yield ExecutorEvent("approval.completed", {
                    "approval_id": approval_id, "run_id": run_id, "tool": name,
                    "approved": approved is True,
                })
                if approved is not True:
                    status = "timeout" if approved is None else "rejected"
                    result = "审批超时，未执行工具" if approved is None else "用户拒绝了该操作"
                    await _finish_tool_run(
                        tool_run.id, status, result, int((time.perf_counter() - started) * 1000)
                    )
                    failures += 1
                    yield ExecutorEvent(
                        "tool.completed", _tool_event(run_id, step_index, name, summary, result, status)
                    )
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                    continue
                await _approve_tool_run(tool_run.id)

            yield ExecutorEvent("agent.status", {"status": "running_tool", "tool": name})
            yield ExecutorEvent("tool.started", {
                "run_id": run_id, "step_index": step_index, "tool": name,
                "args_summary": summary, "risk_level": validated_tool.risk_level,
                "effect": validated_tool.description,
            })
            execution = await execute_tool(name, validated_args, allowed_tools)
            execution = await run_post_tool_hooks(invocation, execution)
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _finish_tool_run(tool_run.id, execution.status, execution.content, duration_ms)
            if execution.status == "completed":
                successes += 1
            else:
                failures += 1
            logger.info(
                "tool_run run_id=%s step_index=%s tool=%s status=%s duration_ms=%s",
                run_id, step_index, name, execution.status, duration_ms,
            )
            yield ExecutorEvent(
                "tool.completed",
                _tool_event(run_id, step_index, name, summary, execution.content, execution.status),
            )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": execution.content})

    yield ExecutorEvent("executor.completed", {
        "content": "".join(reply_parts),
        "usage": usage,
        "blocked": failures > 0 and successes == 0,
        "tool_failures": failures,
        "tool_successes": successes,
    })


def _tool_event(run_id: str, step_index: int, tool: str, args_summary: str, result: str, status: str) -> dict:
    return {
        "run_id": run_id, "step_index": step_index, "tool": tool,
        "args_summary": args_summary, "result_summary": result[:MAX_SUMMARY_CHARS], "status": status,
    }


async def _create_tool_run(
    run_id: str, conversation_id: str, tool_call_id: str, step_index: int,
    tool: str, args_summary: str, risk_level: str, status: str,
    approval_id: str | None = None,
    *,
    plan_version: int | None = None,
    plan_step_id: str | None = None,
    idempotency_key: str | None = None,
) -> ToolRunReservation:
    def _create() -> ToolRunReservation:
        with SessionLocal() as session:
            if idempotency_key:
                existing = (
                    session.query(ToolRun)
                    .filter(ToolRun.idempotency_key == idempotency_key)
                    .with_for_update()
                    .one_or_none()
                )
                if existing is not None:
                    if existing.status == "completed":
                        return ToolRunReservation(
                            existing.id, reused=True, result=existing.result_summary or ""
                        )
                    existing.tool_call_id = tool_call_id
                    existing.step_index = step_index
                    existing.args_summary = args_summary[:MAX_SUMMARY_CHARS]
                    existing.risk_level = risk_level
                    existing.approval_id = approval_id
                    existing.approved_at = None
                    existing.status = status
                    existing.result_summary = None
                    existing.duration_ms = None
                    existing.completed_at = None
                    session.commit()
                    return ToolRunReservation(existing.id)
            row = ToolRun(
                run_id=run_id, conversation_id=conversation_id, tool_call_id=tool_call_id,
                step_index=step_index, tool=tool, args_summary=args_summary[:MAX_SUMMARY_CHARS],
                risk_level=risk_level, approval_id=approval_id, status=status,
                plan_version=plan_version, plan_step_id=plan_step_id,
                idempotency_key=idempotency_key,
            )
            session.add(row)
            session.commit()
            return ToolRunReservation(row.id)
    return await anyio.to_thread.run_sync(_create)


def _tool_idempotency_key(
    run_id: str,
    plan_version: int | None,
    plan_step_id: str | None,
    tool: str,
    args: dict,
) -> str | None:
    if plan_version is None or not plan_step_id:
        return None
    normalized = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    args_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    raw = f"{run_id}:{plan_version}:{plan_step_id}:{tool}:{args_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _completed_tool_run(idempotency_key: str) -> ToolRun | None:
    def _load() -> ToolRun | None:
        with SessionLocal() as session:
            return (
                session.query(ToolRun)
                .filter(
                    ToolRun.idempotency_key == idempotency_key,
                    ToolRun.status == "completed",
                )
                .one_or_none()
            )

    return await anyio.to_thread.run_sync(_load)


async def _approve_tool_run(tool_run_id: str) -> None:
    def _approve() -> None:
        with SessionLocal() as session:
            row = session.get(ToolRun, tool_run_id)
            if row:
                row.status = "running"
                row.approved_at = datetime.now(timezone.utc)
                session.commit()
    await anyio.to_thread.run_sync(_approve)


async def _finish_tool_run(tool_run_id: str, status: str, result: str, duration_ms: int) -> None:
    def _finish() -> None:
        with SessionLocal() as session:
            row = session.get(ToolRun, tool_run_id)
            if row:
                row.status = status
                row.result_summary = result[:MAX_SUMMARY_CHARS]
                row.duration_ms = duration_ms
                row.completed_at = datetime.now(timezone.utc)
                session.commit()
    await anyio.to_thread.run_sync(_finish)
