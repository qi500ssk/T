"""Agent Runtime：流式回答、受限工具循环、审批和执行记录。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

import anyio

from core.character import load_character, render_system_prompt
from core.context import build_context
from core.memory import extract_memories, save_memories
from core.permissions import (
    cancel_run_approvals,
    create_approval,
    wait_for_approval,
)
from core.skills import Skill, allowed_tool_names, render_skill_instructions
from core.summary import update_conversation_summary
from core.tools import TOOLS, ToolValidationError, execute_tool, prepare_tool, tool_schemas
from infrastructure.config import settings
from infrastructure.database import AgentRun, Conversation, Message, SessionLocal, ToolRun


logger = logging.getLogger(__name__)
MAX_SUMMARY_CHARS = 500
MAX_ARGS_SUMMARY_CHARS = 300
STEP_LIMIT_REPLY = "已达到工具调用步骤上限，请缩小任务范围后重试。"


@dataclass
class AgentEvent:
    type: str
    data: dict = field(default_factory=dict)


def sse_packet(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def merge_tool_call_deltas(target: dict[int, dict], deltas: list[dict]) -> None:
    """按 OpenAI tool_calls[].index 合并流式 id/name/arguments 片段。"""
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
    if tool == "write_file":
        path = str(args.get("path", ""))
        content = args.get("content", "")
        size = len(content.encode("utf-8")) if isinstance(content, str) else 0
        return f"path={path!r}, content_bytes={size}"
    text = json.dumps(args, ensure_ascii=False, sort_keys=True)
    return text[:MAX_ARGS_SUMMARY_CHARS]


async def run_chat(
    provider,
    conversation_id: str,
    message: str,
    user_id: str = "default",
    embedding_provider=None,
    skills: list[Skill] | None = None,
) -> AsyncIterator[AgentEvent]:
    """执行一次 Agent Run，产出 SSE Agent Event Protocol 事件。"""
    run_id = uuid.uuid4().hex

    def _init_run() -> str:
        with SessionLocal() as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                raise ValueError("conversation not found")
            if conv.title == "新对话":
                conv.title = message[:20]
            user_message = Message(conversation_id=conversation_id, role="user", content=message)
            session.add(user_message)
            session.add(
                AgentRun(id=run_id, conversation_id=conversation_id, user_id=user_id, status="running")
            )
            conv.updated_at = datetime.now(timezone.utc)
            session.commit()
            return user_message.id

    user_message_id = await anyio.to_thread.run_sync(_init_run)
    yield AgentEvent("run.started", {"run_id": run_id, "conversation_id": conversation_id})

    context = None
    reply = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    try:
        async with asyncio.timeout(settings.agent_timeout_seconds):
            character = await anyio.to_thread.run_sync(load_character, settings.character_file)
            system_prompt = await anyio.to_thread.run_sync(
                render_system_prompt, character, settings.system_prompt_file
            )
            active_skills = list(skills or []) if settings.tools_enabled else []
            allowed_tools = allowed_tool_names(active_skills, settings.tools_enabled)
            schemas = tool_schemas(allowed_tools) if allowed_tools else None
            skill_prompt = render_skill_instructions(active_skills)

            def _build():
                with SessionLocal() as session:
                    return build_context(
                        session,
                        system_prompt,
                        conversation_id,
                        message,
                        settings.context_max_tokens,
                        settings.context_recent_messages,
                        user_id,
                        settings.memory_recall_limit if settings.memory_enabled else 0,
                        user_message_id,
                        embedding_provider,
                        settings,
                        system_addendum=skill_prompt,
                    )

            context = await anyio.to_thread.run_sync(_build)
            messages = [{"role": "system", "content": context.system}] + context.messages
            if context.sources:
                yield AgentEvent("rag.retrieved", {"sources": context.sources})

            reply_parts: list[str] = []
            step_index = 0
            for round_index in range(settings.agent_max_steps):
                turn_text: list[str] = []
                tool_deltas: dict[int, dict] = {}
                async for chunk in provider.stream(messages, tools=schemas):
                    if chunk.text:
                        turn_text.append(chunk.text)
                        reply_parts.append(chunk.text)
                        yield AgentEvent("message.delta", {"content": chunk.text})
                    if chunk.tool_calls_delta:
                        merge_tool_call_deltas(tool_deltas, chunk.tool_calls_delta)
                    if chunk.usage:
                        usage["prompt_tokens"] += int(chunk.usage.get("prompt_tokens", 0))
                        usage["completion_tokens"] += int(chunk.usage.get("completion_tokens", 0))

                tool_calls = finalize_tool_calls(tool_deltas)
                if not tool_calls:
                    break
                if round_index == settings.agent_max_steps - 1:
                    reply_parts.append(STEP_LIMIT_REPLY)
                    yield AgentEvent("message.delta", {"content": STEP_LIMIT_REPLY})
                    break

                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(turn_text) or None,
                        "tool_calls": tool_calls,
                    }
                )
                for call in tool_calls:
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
                            run_id,
                            conversation_id,
                            call["id"],
                            step_index,
                            name or "unknown",
                            summary,
                            risk,
                            "failed",
                        )
                        duration_ms = int((time.perf_counter() - started) * 1000)
                        await _finish_tool_run(tool_run_id, "failed", result, duration_ms)
                        yield AgentEvent(
                            "tool.completed",
                            _tool_event(run_id, step_index, name, summary, result, "failed"),
                        )
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
                        step_index += 1
                        continue

                    approval_id = None
                    initial_status = "pending_approval" if validated_tool.risk_level == "high" else "running"
                    if validated_tool.risk_level == "high":
                        approval_id = create_approval(run_id)
                    tool_run_id = await _create_tool_run(
                        run_id,
                        conversation_id,
                        call["id"],
                        step_index,
                        name,
                        summary,
                        validated_tool.risk_level,
                        initial_status,
                        approval_id,
                    )

                    if approval_id:
                        yield AgentEvent(
                            "approval.required",
                            {
                                "approval_id": approval_id,
                                "run_id": run_id,
                                "tool": name,
                                "args_summary": summary,
                                "risk_level": validated_tool.risk_level,
                            },
                        )
                        approved = await wait_for_approval(
                            approval_id, settings.approval_timeout_seconds
                        )
                        yield AgentEvent(
                            "approval.completed",
                            {
                                "approval_id": approval_id,
                                "run_id": run_id,
                                "tool": name,
                                "approved": approved is True,
                            },
                        )
                        if approved is not True:
                            status = "timeout" if approved is None else "rejected"
                            result = "审批超时，未执行工具" if approved is None else "用户拒绝了该操作"
                            duration_ms = int((time.perf_counter() - started) * 1000)
                            await _finish_tool_run(tool_run_id, status, result, duration_ms)
                            yield AgentEvent(
                                "tool.completed",
                                _tool_event(run_id, step_index, name, summary, result, status),
                            )
                            messages.append(
                                {"role": "tool", "tool_call_id": call["id"], "content": result}
                            )
                            step_index += 1
                            continue
                        await _approve_tool_run(tool_run_id)

                    yield AgentEvent(
                        "agent.status", {"status": "running_tool", "tool": name}
                    )
                    yield AgentEvent(
                        "tool.started",
                        {
                            "run_id": run_id,
                            "step_index": step_index,
                            "tool": name,
                            "args_summary": summary,
                        },
                    )
                    execution = await execute_tool(name, validated_args, allowed_tools)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    await _finish_tool_run(
                        tool_run_id, execution.status, execution.content, duration_ms
                    )
                    logger.info(
                        "tool_run run_id=%s step_index=%s tool=%s status=%s duration_ms=%s",
                        run_id,
                        step_index,
                        name,
                        execution.status,
                        duration_ms,
                    )
                    yield AgentEvent(
                        "tool.completed",
                        _tool_event(
                            run_id,
                            step_index,
                            name,
                            summary,
                            execution.content,
                            execution.status,
                        ),
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": execution.content,
                        }
                    )
                    step_index += 1

            reply = "".join(reply_parts)

        allowed_citations = {item["citation_id"] for item in context.sources}
        cited = {item.lower() for item in re.findall(r"\[(c\d+)\]", reply, flags=re.IGNORECASE)}
        unknown = cited - allowed_citations
        if unknown:
            logger.warning("模型返回未知引用：%s", ", ".join(sorted(unknown)))
        await _finish_run(run_id, conversation_id, reply, context.sources, usage)
    except asyncio.CancelledError:
        cancel_run_approvals(run_id)
        await _fail_run(run_id, "cancelled", "客户端已中止连接")
        raise
    except GeneratorExit:
        cancel_run_approvals(run_id)
        await _fail_run(run_id, "cancelled", "客户端已中止连接")
        raise
    except TimeoutError:
        cancel_run_approvals(run_id)
        await _fail_run(run_id, "failed", "Agent Run 超时")
        yield AgentEvent("run.failed", {"run_id": run_id, "error": "运行超时"})
        return
    except Exception as exc:
        cancel_run_approvals(run_id)
        await _fail_run(run_id, "failed", str(exc))
        yield AgentEvent("run.failed", {"run_id": run_id, "error": str(exc)})
        return

    yield AgentEvent("message.completed", {})
    if settings.memory_enabled:
        try:
            candidates = await extract_memories(provider, message, reply)

            def _save_extracted():
                with SessionLocal() as session:
                    return save_memories(
                        session,
                        candidates,
                        user_id,
                        conversation_id,
                        settings.memory_min_importance,
                        settings.memory_min_confidence,
                    )

            await anyio.to_thread.run_sync(_save_extracted)
        except Exception:
            logger.exception("记忆提取失败，聊天结果已正常保存")
        try:
            await update_conversation_summary(
                provider,
                conversation_id,
                settings.summary_trigger_messages,
                settings.summary_keep_recent_messages,
            )
        except Exception:
            logger.exception("会话摘要失败，聊天结果已正常保存")
    yield AgentEvent("run.completed", {"run_id": run_id, "token_usage": usage})


def _tool_event(
    run_id: str,
    step_index: int,
    tool: str,
    args_summary: str,
    result: str,
    status: str,
) -> dict:
    return {
        "run_id": run_id,
        "step_index": step_index,
        "tool": tool,
        "args_summary": args_summary,
        "result_summary": result[:MAX_SUMMARY_CHARS],
        "status": status,
    }


async def _create_tool_run(
    run_id: str,
    conversation_id: str,
    tool_call_id: str,
    step_index: int,
    tool: str,
    args_summary: str,
    risk_level: str,
    status: str,
    approval_id: str | None = None,
) -> str:
    def _create() -> str:
        with SessionLocal() as session:
            row = ToolRun(
                run_id=run_id,
                conversation_id=conversation_id,
                tool_call_id=tool_call_id,
                step_index=step_index,
                tool=tool,
                args_summary=args_summary[:MAX_SUMMARY_CHARS],
                risk_level=risk_level,
                approval_id=approval_id,
                status=status,
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


async def _finish_tool_run(
    tool_run_id: str, status: str, result: str, duration_ms: int
) -> None:
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


async def _finish_run(
    run_id: str,
    conversation_id: str,
    reply: str,
    sources: list[dict],
    usage: dict,
) -> None:
    def _finish() -> None:
        with SessionLocal() as session:
            session.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=reply,
                    citations=sources or None,
                )
            )
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                run.input_tokens = usage.get("prompt_tokens", 0)
                run.output_tokens = usage.get("completion_tokens", 0)
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.updated_at = datetime.now(timezone.utc)
            session.commit()

    await anyio.to_thread.run_sync(_finish)


async def _fail_run(run_id: str, status: str, error: str) -> None:
    def _fail() -> None:
        with SessionLocal() as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = status
                run.error = error[:MAX_SUMMARY_CHARS]
                run.completed_at = datetime.now(timezone.utc)
            pending_tools = (
                session.query(ToolRun)
                .filter(
                    ToolRun.run_id == run_id,
                    ToolRun.status.in_(["pending_approval", "running"]),
                )
                .all()
            )
            for tool_run in pending_tools:
                tool_run.status = "failed"
                tool_run.result_summary = error[:MAX_SUMMARY_CHARS]
                tool_run.completed_at = datetime.now(timezone.utc)
            session.commit()

    await anyio.to_thread.run_sync(_fail)
