"""执行域共享循环：direct 与 planned Run 使用同一安全链路。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

import anyio

from core.execution.permissions import create_approval, wait_for_approval
from core.execution.tool_pipeline import ToolInvocation, run_post_tool_hooks, run_pre_tool_hooks
from core.execution.tools import TOOLS, ToolValidationError, execute_tool, prepare_tool
from infrastructure.config import settings
from infrastructure.database import SessionLocal, ToolRun


logger = logging.getLogger(__name__)
MAX_SUMMARY_CHARS = 500
MAX_ARGS_SUMMARY_CHARS = 300
STEP_LIMIT_REPLY = "已达到工具调用步骤上限，请缩小任务范围后重试。"


@dataclass
class ExecutorEvent:
    type: str
    data: dict = field(default_factory=dict)


@dataclass
class ToolCallBudget:
    remaining: int
    used: int = 0


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
) -> AsyncIterator[ExecutorEvent]:
    """执行有限模型/工具循环，最后产生仅供 Agent 消费的 executor.completed。"""
    reply_parts: list[str] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    failures = 0
    successes = 0

    for round_index in range(max_turns):
        turn_text: list[str] = []
        tool_deltas: dict[int, dict] = {}
        async for chunk in provider.stream(messages, tools=schemas):
            if chunk.text:
                turn_text.append(chunk.text)
                reply_parts.append(chunk.text)
                yield ExecutorEvent("message.delta", {"content": chunk.text})
            if chunk.tool_calls_delta:
                merge_tool_call_deltas(tool_deltas, chunk.tool_calls_delta)
            if chunk.usage:
                usage["prompt_tokens"] += int(chunk.usage.get("prompt_tokens", 0))
                usage["completion_tokens"] += int(chunk.usage.get("completion_tokens", 0))

        tool_calls = finalize_tool_calls(tool_deltas)
        if not tool_calls:
            break
        if round_index == max_turns - 1 or len(tool_calls) > tool_budget.remaining:
            reply_parts.append(STEP_LIMIT_REPLY)
            yield ExecutorEvent("message.delta", {"content": STEP_LIMIT_REPLY})
            failures += 1
            break

        tool_budget.remaining -= len(tool_calls)
        messages.append(
            {"role": "assistant", "content": "".join(turn_text) or None, "tool_calls": tool_calls}
        )
        for call in tool_calls:
            step_index = tool_budget.used
            tool_budget.used += 1
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
                result = f"工具错误：{exc}"
                tool_run_id = await _create_tool_run(
                    run_id, conversation_id, call["id"], step_index, name or "unknown",
                    summary, risk, "failed",
                )
                await _finish_tool_run(
                    tool_run_id, "failed", result, int((time.perf_counter() - started) * 1000)
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
                tool_run_id = await _create_tool_run(
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
                    tool_run_id,
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

            background_rejected = validated_tool.risk_level == "high" and approval_mode == "deny"
            approval_id = None
            initial_status = (
                "rejected" if background_rejected else
                "pending_approval" if validated_tool.risk_level == "high" else "running"
            )
            if validated_tool.risk_level == "high" and not background_rejected:
                approval_id = create_approval(run_id)
            tool_run_id = await _create_tool_run(
                run_id, conversation_id, call["id"], step_index, name, summary,
                validated_tool.risk_level, initial_status, approval_id,
            )

            if background_rejected:
                result = "后台任务不能执行需要用户审批的工具"
                await _finish_tool_run(
                    tool_run_id, "rejected", result, int((time.perf_counter() - started) * 1000)
                )
                failures += 1
                yield ExecutorEvent(
                    "tool.completed", _tool_event(run_id, step_index, name, summary, result, "rejected")
                )
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                continue

            if approval_id:
                yield ExecutorEvent("approval.required", {
                    "approval_id": approval_id, "run_id": run_id, "tool": name,
                    "args_summary": summary, "risk_level": validated_tool.risk_level,
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
                        tool_run_id, status, result, int((time.perf_counter() - started) * 1000)
                    )
                    failures += 1
                    yield ExecutorEvent(
                        "tool.completed", _tool_event(run_id, step_index, name, summary, result, status)
                    )
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                    continue
                await _approve_tool_run(tool_run_id)

            yield ExecutorEvent("agent.status", {"status": "running_tool", "tool": name})
            yield ExecutorEvent("tool.started", {
                "run_id": run_id, "step_index": step_index, "tool": name, "args_summary": summary,
            })
            execution = await execute_tool(name, validated_args, allowed_tools)
            execution = await run_post_tool_hooks(invocation, execution)
            duration_ms = int((time.perf_counter() - started) * 1000)
            await _finish_tool_run(tool_run_id, execution.status, execution.content, duration_ms)
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
) -> str:
    def _create() -> str:
        with SessionLocal() as session:
            row = ToolRun(
                run_id=run_id, conversation_id=conversation_id, tool_call_id=tool_call_id,
                step_index=step_index, tool=tool, args_summary=args_summary[:MAX_SUMMARY_CHARS],
                risk_level=risk_level, approval_id=approval_id, status=status,
            )
            session.add(row)
            session.commit()
            return row.id
    return await anyio.to_thread.run_sync(_create)


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
