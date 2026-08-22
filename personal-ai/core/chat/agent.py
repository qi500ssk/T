"""聊天域 Agent Runtime：流式回答、受限工具循环、审批和执行记录。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

import anyio
from sqlalchemy.exc import IntegrityError

from core.chat.character import load_character, render_system_prompt
from core.chat.context import build_context
from core.chat.memory import extract_memories, save_memories
from core.execution.executor import ToolCallBudget, execute_model_loop, merge_tool_call_deltas
from core.automation.planner import (
    PROMPT_ROOT,
    apply_replan,
    cancel_plan_for_run,
    create_planning_record,
    finish_plan,
    finish_step,
    generate_plan,
    generate_replan,
    populate_plan,
    set_step_running,
)
from core.execution.permissions import cancel_run_approvals
from core.capabilities.registry import build_run_capability_snapshot
from core.capabilities.skills import Skill, allowed_tool_names, render_skill_instructions
from core.chat.summary import update_conversation_summary
from core.execution.tools import bind_active_skills, list_tools, reset_active_skills, tool_schemas
from infrastructure.config import settings
from infrastructure.database import AgentRun, Conversation, Message, SessionLocal, ToolRun


logger = logging.getLogger(__name__)
MAX_SUMMARY_CHARS = 500


@dataclass
class AgentEvent:
    type: str
    data: dict = field(default_factory=dict)


def sse_packet(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def run_chat(
    provider,
    conversation_id: str,
    message: str,
    user_id: str = "default",
    embedding_provider=None,
    skills: list[Skill] | None = None,
    activity_id: str | None = None,
    approval_mode: Literal["interactive", "deny"] = "interactive",
    execution_mode: Literal["direct", "planned"] = "direct",
) -> AsyncIterator[AgentEvent]:
    """执行一次 Agent Run，产出 SSE Agent Event Protocol 事件。"""
    run_id = uuid.uuid4().hex
    active_skills = list(skills or []) if settings.tools_enabled else []
    allowed_tools = allowed_tool_names(active_skills, settings.tools_enabled)
    capability_version, capability_snapshot = build_run_capability_snapshot(
        active_skills, allowed_tools
    )

    def _init_run() -> str:
        with SessionLocal() as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                raise ValueError("conversation not found")
            if (
                session.query(AgentRun)
                .filter(
                    AgentRun.conversation_id == conversation_id,
                    AgentRun.status == "running",
                )
                .first()
            ):
                raise RuntimeError("conversation already has a running agent run")
            if conv.title == "新对话":
                conv.title = message[:20]
            user_message = Message(conversation_id=conversation_id, role="user", content=message)
            session.add(user_message)
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    activity_id=activity_id,
                    execution_mode=execution_mode,
                    capability_version=capability_version,
                    capability_snapshot=capability_snapshot,
                    status="running",
                )
            )
            conv.updated_at = datetime.now(timezone.utc)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise RuntimeError("conversation already has a running agent run") from exc
            return user_message.id

    user_message_id = await anyio.to_thread.run_sync(_init_run)
    yield AgentEvent(
        "run.started",
        {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "capability_version": capability_version,
            "enabled_skills": [skill.id for skill in active_skills],
        },
    )

    context = None
    reply = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    used_sources: list[dict] = []
    plan_id: str | None = None
    run_status = "completed"
    run_error = ""
    skill_token = bind_active_skills(active_skills)
    try:
        async with asyncio.timeout(settings.agent_timeout_seconds):
            character = await anyio.to_thread.run_sync(load_character, settings.character_file)
            system_prompt = await anyio.to_thread.run_sync(
                render_system_prompt, character, settings.system_prompt_file
            )
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
            if execution_mode == "planned":
                if not settings.planner_enabled:
                    raise RuntimeError("Planner 已禁用")
                plan = await anyio.to_thread.run_sync(
                    create_planning_record,
                    run_id,
                    conversation_id,
                    activity_id,
                    message,
                )
                plan_id = plan.id
                draft = await generate_plan(
                    provider,
                    message,
                    allowed_tools,
                    list_tools(),
                    settings.planner_max_steps,
                )
                plan, steps = await anyio.to_thread.run_sync(populate_plan, plan.id, draft)
                yield AgentEvent(
                    "plan.created",
                    {
                        "plan_id": plan.id,
                        "goal": plan.goal,
                        "version": plan.current_version,
                        "steps": [_step_event(row) for row in steps],
                    },
                )
                tool_budget = ToolCallBudget(settings.planner_max_tool_calls)
                completed: list[dict] = []
                while True:
                    blocked = None
                    for step in steps:
                        await anyio.to_thread.run_sync(set_step_running, step.id)
                        yield AgentEvent(
                            "plan.step.started",
                            {"plan_id": plan.id, **_step_event(step), "status": "running"},
                        )
                        step_payload = json.dumps(
                            {
                                "goal": plan.goal,
                                "completed_steps": completed,
                                "current_step": {
                                    "title": step.title,
                                    "instruction": step.instruction,
                                    "tool_hints": step.tool_hints or [],
                                },
                            },
                            ensure_ascii=False,
                        )
                        step_messages = [
                            {
                                "role": "system",
                                "content": context.system
                                + "\n\n"
                                + (PROMPT_ROOT / "step.md").read_text(encoding="utf-8"),
                            },
                            *context.messages,
                            {"role": "user", "content": step_payload},
                        ]
                        step_result = None
                        async for event in execute_model_loop(
                            provider,
                            step_messages,
                            schemas,
                            allowed_tools,
                            run_id,
                            conversation_id,
                            approval_mode=approval_mode,
                            max_turns=settings.planner_step_max_turns,
                            tool_budget=tool_budget,
                        ):
                            if event.type == "executor.completed":
                                step_result = event.data
                            elif event.type != "message.delta":
                                yield AgentEvent(event.type, event.data)
                        if step_result is None:
                            raise RuntimeError("步骤 Executor 未返回结果")
                        step_usage = step_result["usage"]
                        usage["prompt_tokens"] += int(step_usage.get("prompt_tokens", 0))
                        usage["completion_tokens"] += int(step_usage.get("completion_tokens", 0))
                        output = str(step_result.get("content") or "").strip()
                        if step_result.get("blocked") or not output:
                            error = "当前步骤缺少可用结果或所需工具执行失败"
                            await anyio.to_thread.run_sync(
                                finish_step, step.id, "blocked", output, error
                            )
                            blocked = {"title": step.title, "error": error, "output_summary": output[:500]}
                            yield AgentEvent(
                                "plan.step.blocked",
                                {
                                    "plan_id": plan.id,
                                    **_step_event(step),
                                    "status": "blocked",
                                    "error": error,
                                },
                            )
                            break
                        summary = output[:2000]
                        await anyio.to_thread.run_sync(
                            finish_step, step.id, "completed", summary, ""
                        )
                        completed.append({"title": step.title, "output_summary": summary})
                        _trim_observations(completed, settings.planner_observation_tokens_budget)
                        yield AgentEvent(
                            "plan.step.completed",
                            {
                                "plan_id": plan.id,
                                **_step_event(step),
                                "status": "completed",
                                "output_summary": summary,
                            },
                        )

                    if blocked is None:
                        await anyio.to_thread.run_sync(finish_plan, plan.id, "completed", "")
                        yield AgentEvent("plan.completed", {"plan_id": plan.id})
                        break
                    if plan.replan_count >= settings.planner_max_replans:
                        run_status = "failed"
                        run_error = blocked["error"]
                        await anyio.to_thread.run_sync(finish_plan, plan.id, "failed", run_error)
                        yield AgentEvent("plan.failed", {"plan_id": plan.id, "error": run_error})
                        break
                    draft = await generate_replan(
                        provider,
                        plan.goal,
                        completed,
                        blocked,
                        allowed_tools,
                        list_tools(),
                        settings.planner_max_steps,
                    )
                    plan, steps = await anyio.to_thread.run_sync(apply_replan, plan.id, draft)
                    yield AgentEvent(
                        "plan.replanned",
                        {
                            "plan_id": plan.id,
                            "version": plan.current_version,
                            "steps": [_step_event(row) for row in steps],
                        },
                    )

                synthesis_payload = json.dumps(
                    {
                        "goal": plan.goal,
                        "status": run_status,
                        "completed_steps": completed,
                        "error": run_error,
                    },
                    ensure_ascii=False,
                )
                synthesis_messages = [
                    {
                        "role": "system",
                        "content": context.system
                        + "\n\n"
                        + (PROMPT_ROOT / "synthesize.md").read_text(encoding="utf-8"),
                    },
                    {"role": "user", "content": synthesis_payload},
                ]
                synthesis = None
                async for event in execute_model_loop(
                    provider,
                    synthesis_messages,
                    None,
                    set(),
                    run_id,
                    conversation_id,
                    approval_mode=approval_mode,
                    max_turns=1,
                    tool_budget=ToolCallBudget(0),
                ):
                    if event.type == "executor.completed":
                        synthesis = event.data
                    else:
                        yield AgentEvent(event.type, event.data)
                if synthesis is None:
                    raise RuntimeError("最终汇总未返回结果")
                reply = str(synthesis["content"])
                synth_usage = synthesis["usage"]
                usage["prompt_tokens"] += int(synth_usage.get("prompt_tokens", 0))
                usage["completion_tokens"] += int(synth_usage.get("completion_tokens", 0))
            else:
                result = None
                async for event in execute_model_loop(
                    provider,
                    messages,
                    schemas,
                    allowed_tools,
                    run_id,
                    conversation_id,
                    approval_mode=approval_mode,
                    max_turns=settings.agent_max_steps,
                    tool_budget=ToolCallBudget(remaining=100_000),
                ):
                    if event.type == "executor.completed":
                        result = event.data
                    else:
                        yield AgentEvent(event.type, event.data)
                if result is None:
                    raise RuntimeError("Executor 未返回结果")
                reply = str(result["content"])
                usage = dict(result["usage"])

        allowed_citations = {item["citation_id"].lower() for item in context.sources}
        cited = {item.lower() for item in re.findall(r"\[(c\d+)\]", reply, flags=re.IGNORECASE)}
        unknown = cited - allowed_citations
        if unknown:
            logger.warning("模型返回未知引用：%s", ", ".join(sorted(unknown)))
        used_sources = [
            item for item in context.sources if item["citation_id"].lower() in cited
        ]
        await _finish_run(
            run_id, conversation_id, reply, used_sources, usage, run_status, run_error
        )
    except asyncio.CancelledError:
        cancel_run_approvals(run_id)
        await anyio.to_thread.run_sync(cancel_plan_for_run, run_id)
        await _fail_run(run_id, "cancelled", "客户端已中止连接")
        raise
    except GeneratorExit:
        cancel_run_approvals(run_id)
        await anyio.to_thread.run_sync(cancel_plan_for_run, run_id)
        await _fail_run(run_id, "cancelled", "客户端已中止连接")
        raise
    except TimeoutError:
        cancel_run_approvals(run_id)
        await anyio.to_thread.run_sync(cancel_plan_for_run, run_id)
        await _fail_run(run_id, "failed", "Agent Run 超时")
        yield AgentEvent("run.failed", {"run_id": run_id, "error": "运行超时"})
        return
    except Exception as exc:
        cancel_run_approvals(run_id)
        if plan_id:
            try:
                await anyio.to_thread.run_sync(finish_plan, plan_id, "failed", str(exc))
            except Exception:
                logger.exception("Plan 失败状态写入失败")
        await _fail_run(run_id, "failed", str(exc))
        if plan_id:
            failure_reply = "规划执行未完成，系统已安全停止后续步骤。请重试或切换直接模式。"
            try:
                await _save_failure_message(conversation_id, failure_reply)
                yield AgentEvent("message.delta", {"content": failure_reply})
                yield AgentEvent("message.completed", {})
            except Exception:
                logger.exception("Plan 失败说明写入失败")
        yield AgentEvent("run.failed", {"run_id": run_id, "error": str(exc)})
        return
    finally:
        reset_active_skills(skill_token)

    if used_sources:
        yield AgentEvent("rag.retrieved", {"sources": used_sources})
    yield AgentEvent("message.completed", {})
    if settings.memory_enabled and activity_id is None and run_status == "completed":
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
    if settings.memory_enabled:
        try:
            await update_conversation_summary(
                provider,
                conversation_id,
                settings.summary_trigger_messages,
                settings.summary_keep_recent_messages,
            )
        except Exception:
            logger.exception("会话摘要失败，聊天结果已正常保存")
    if run_status == "failed":
        yield AgentEvent("run.failed", {"run_id": run_id, "error": run_error})
    else:
        yield AgentEvent("run.completed", {"run_id": run_id, "token_usage": usage})


def _step_event(step) -> dict:
    return {
        "step_id": step.id,
        "version": step.version,
        "position": step.position,
        "title": step.title,
        "status": step.status,
        "tool_hints": step.tool_hints or [],
    }


def _trim_observations(items: list[dict], token_budget: int) -> None:
    max_chars = token_budget * 2
    while len(json.dumps(items, ensure_ascii=False)) > max_chars and items:
        if len(items) == 1:
            items[0]["output_summary"] = str(items[0]["output_summary"])[:max_chars]
            break
        items.pop(0)


async def _finish_run(
    run_id: str,
    conversation_id: str,
    reply: str,
    sources: list[dict],
    usage: dict,
    status: str = "completed",
    error: str = "",
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
                run.status = status
                run.error = error[:MAX_SUMMARY_CHARS] or None
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


async def _save_failure_message(conversation_id: str, content: str) -> None:
    def _save() -> None:
        with SessionLocal() as session:
            session.add(
                Message(conversation_id=conversation_id, role="assistant", content=content)
            )
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.updated_at = datetime.now(timezone.utc)
            session.commit()

    await anyio.to_thread.run_sync(_save)
