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

from core.chat.character import apply_agent_profile, load_character, render_system_prompt
from core.chat.context import build_context, estimate_tokens
from core.chat.continuation import find_continuation_context, is_continuation_request
from core.chat.memory import extract_memories, save_memories
from core.chat.intent import IntentResult, narrow_allowed_tools, route_intent
from core.chat.checkpoints import (
    checkpoint_dict,
    create_checkpoint,
    interrupt_run,
    latest_checkpoint,
)
from core.chat.run_control import consume_user_cancellation
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
from core.execution.permissions import (
    cancel_run_approvals,
    create_approval,
    wait_for_approval,
)
from core.capabilities.registry import (
    build_run_capability_snapshot,
    connected_mcp_tool_names,
)
from core.capabilities.skills import Skill, allowed_tool_names, render_skill_instructions
from core.chat.summary import update_conversation_summary
from core.chat.usage import conversation_cache_stats
from core.execution.tools import bind_active_skills, list_tools, reset_active_skills, tool_schemas
from infrastructure.config import settings
from infrastructure.database import (
    AgentRun,
    ChatImage,
    Conversation,
    Message,
    Plan,
    PlanStep,
    SessionLocal,
    ToolRun,
)


logger = logging.getLogger(__name__)
MAX_SUMMARY_CHARS = 500


def _mcp_tool_guidance(mcp_clients: list | None) -> str:
    names = {str(client.config.name) for client in (mcp_clients or [])}
    lines: list[str] = []
    if "desktop-media" in names:
        lines.append(
            "- mcp_desktop-media_* 只操作 Windows QQ 音乐；工具结果已经包含最终验证，"
            "失败时不要猜测用户未提供的歌手。"
        )
    if "playwright" in names:
        lines.append(
            "- mcp_playwright_* 只操作 Playwright 打开的网页，不得用于等待、验证或控制桌面软件。"
        )
    return "[MCP 工具边界]\n" + "\n".join(lines) if lines else ""


@dataclass
class AgentEvent:
    type: str
    data: dict = field(default_factory=dict)


def sse_packet(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _add_token_usage(target: dict, source: dict) -> None:
    target["prompt_tokens"] += int(source.get("prompt_tokens", 0))
    target["completion_tokens"] += int(source.get("completion_tokens", 0))
    if "cached_prompt_tokens" in source:
        target["cached_prompt_tokens"] = int(target.get("cached_prompt_tokens", 0)) + int(
            source.get("cached_prompt_tokens", 0)
        )


def _reason_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        reason = str(item.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


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
    agent_profile: dict | None = None,
    document_ids: list[str] | None = None,
    image_ids: list[str] | None = None,
    mcp_clients: list | None = None,
    context_window_tokens: int | None = None,
    max_output_tokens: int | None = None,
    run_id: str | None = None,
    require_plan_approval: bool = False,
    resume: bool = False,
) -> AsyncIterator[AgentEvent]:
    """执行一次 Agent Run，产出 SSE Agent Event Protocol 事件。"""
    run_id = run_id or uuid.uuid4().hex
    requested_execution_mode = execution_mode
    active_skills = list(skills or []) if settings.tools_enabled else []
    allowed_tools = allowed_tool_names(active_skills, settings.tools_enabled)
    if settings.tools_enabled:
        # MCP Server 的启用状态就是工具授权入口；Skill 只再提供可选用法说明。
        allowed_tools.update(connected_mcp_tool_names(mcp_clients))
    if resume:
        with SessionLocal() as session:
            stored_run = session.get(AgentRun, run_id)
            stored_intent = stored_run.intent_json if stored_run else None
        intent = (
            IntentResult.from_dict(stored_intent)
            if stored_intent
            else IntentResult(
                "task_execution",
                "resume",
                True,
                False,
                True,
                True,
                (),
                "high",
                1.0,
                "legacy_resume",
            )
        )
    else:
        intent = await route_intent(message, provider)
    # 聊天中的规划模式只生成 Markdown 实施方案。活动执行和旧 Checkpoint
    # 恢复仍沿用有限步骤 Planner，避免改变已经调度或已中断任务的语义。
    planning_document_mode = bool(
        not resume and activity_id is None and execution_mode == "planned"
    )
    planning_skipped = False

    configured_tools = set(allowed_tools)
    if resume:
        # 旧 Checkpoint 必须继续使用创建时的能力边界；新增工具不能悄悄进入旧 Run。
        with SessionLocal() as session:
            stored_run = session.get(AgentRun, run_id)
            stored_tools = set((stored_run.capability_snapshot or {}).get("tools", [])) if stored_run else set()
        allowed_tools = configured_tools & stored_tools if stored_tools else configured_tools
    else:
        allowed_tools = narrow_allowed_tools(intent, configured_tools)
    capability_version, capability_snapshot = build_run_capability_snapshot(
        active_skills, allowed_tools
    )

    def _init_run() -> str:
        with SessionLocal() as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                raise ValueError("conversation not found")
            if resume:
                existing_run = session.get(AgentRun, run_id)
                if existing_run is None:
                    raise ValueError("run not found")
                if existing_run.conversation_id != conversation_id:
                    raise ValueError("run conversation mismatch")
                if existing_run.execution_mode != "planned":
                    raise RuntimeError("只有规划模式 Run 可以恢复")
                if existing_run.status != "interrupted":
                    raise RuntimeError("只有 interrupted Run 可以恢复")
                if existing_run.capability_version != capability_version:
                    raise RuntimeError("能力配置已变化，不能安全恢复旧 Run")
                conflict = (
                    session.query(AgentRun)
                    .filter(
                        AgentRun.conversation_id == conversation_id,
                        AgentRun.status == "running",
                        AgentRun.id != run_id,
                    )
                    .first()
                )
                if conflict:
                    raise RuntimeError("conversation already has a running agent run")
                if latest_checkpoint(run_id, session) is None:
                    raise RuntimeError("Run 没有可用 Checkpoint")
                existing_run.status = "running"
                existing_run.error = None
                existing_run.completed_at = None
                session.commit()
                if is_continuation_request(message):
                    continuation_message = Message(
                        conversation_id=conversation_id,
                        role="user",
                        content=message,
                        status="completed",
                    )
                    session.add(continuation_message)
                    session.commit()
                    return continuation_message.id
                if existing_run.input_message_id:
                    return existing_run.input_message_id
                fallback = (
                    session.query(Message)
                    .filter(Message.conversation_id == conversation_id, Message.role == "user")
                    .order_by(Message.created_at.desc())
                    .first()
                )
                if fallback is None:
                    raise RuntimeError("找不到原始用户消息")
                existing_run.input_message_id = fallback.id
                session.commit()
                return fallback.id
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
            requested_image_ids = list(dict.fromkeys(image_ids or []))
            images = (
                session.query(ChatImage)
                .filter(ChatImage.id.in_(requested_image_ids), ChatImage.user_id == user_id)
                .all()
                if requested_image_ids else []
            )
            if len(images) != len(requested_image_ids):
                raise ValueError("图片不存在或已失效，请重新上传")
            if any(image.message_id is not None for image in images):
                raise ValueError("图片已发送，请重新选择")
            user_message = Message(conversation_id=conversation_id, role="user", content=message)
            session.add(user_message)
            session.flush()
            for image in images:
                image.message_id = user_message.id
            session.add(
                AgentRun(
                    id=run_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    activity_id=activity_id,
                    input_message_id=user_message.id,
                    execution_mode=execution_mode,
                    capability_version=capability_version,
                    capability_snapshot=capability_snapshot,
                    intent_json=intent.to_dict(),
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
            "resumed": resume,
            "execution_mode": execution_mode,
            "requested_execution_mode": requested_execution_mode,
            "planning_skipped": planning_skipped,
            "planning_document_mode": planning_document_mode,
        },
    )
    if resume:
        yield AgentEvent("run.resumed", {"run_id": run_id, "conversation_id": conversation_id})
    yield AgentEvent("intent.completed", {"run_id": run_id, **intent.to_dict()})

    context = None
    reply = ""
    partial_reply = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    used_sources: list[dict] = []
    plan_id: str | None = None
    run_status = "completed"
    run_error = ""
    cache_stats = {"average_cache_hit_rate": None}
    skill_token = bind_active_skills(active_skills)
    try:
        async with asyncio.timeout(settings.agent_timeout_seconds):
            character = await anyio.to_thread.run_sync(load_character, settings.character_file)
            character = apply_agent_profile(character, agent_profile)
            system_prompt = await anyio.to_thread.run_sync(
                render_system_prompt, character, settings.system_prompt_file
            )
            # 规划文档不接收任何工具定义，从模型调用层保证它只能输出文本。
            schemas = (
                tool_schemas(allowed_tools)
                if allowed_tools and not planning_document_mode
                else None
            )
            model_context_window = (
                int(context_window_tokens)
                if context_window_tokens is not None
                else settings.context_max_tokens
            )
            model_max_output = int(max_output_tokens) if max_output_tokens is not None else 0
            input_budget = model_context_window - model_max_output
            schema_tokens = estimate_tokens(json.dumps(schemas, ensure_ascii=False)) if schemas else 0
            prompt_budget = input_budget - schema_tokens
            if prompt_budget <= 0:
                raise RuntimeError(
                    "模型上下文窗口过小：最大输出和工具定义已占满可用容量，请调大上下文窗口或调小最大输出"
                )
            if planning_document_mode:
                # Skill/MCP 提示包含工具用法，规划文档模式不应把这些执行指令交给模型。
                system_addendum = ""
            else:
                skill_prompt = render_skill_instructions(active_skills)
                mcp_prompt = _mcp_tool_guidance(mcp_clients)
                preferred_tools = [
                    name for name in intent.candidate_tools if name in allowed_tools
                ]
                intent_tool_prompt = (
                    "[意图路由建议]\n"
                    f"优先考虑这些工具：{', '.join(preferred_tools)}。"
                    "这只是选择建议，不限制其他已启用工具。"
                    if preferred_tools
                    else ""
                )
                system_addendum = "\n\n".join(
                    item for item in (skill_prompt, mcp_prompt, intent_tool_prompt) if item
                )
            continuation_context = None
            if is_continuation_request(message):
                with SessionLocal() as session:
                    continuation_context = find_continuation_context(
                        session,
                        conversation_id,
                        run_id=run_id if resume else None,
                        exclude_run_id=None if resume else run_id,
                    )
                if continuation_context:
                    system_addendum = "\n\n".join(
                        item
                        for item in (
                            system_addendum,
                            continuation_context.system_addendum(),
                        )
                        if item
                    )

            def _build():
                with SessionLocal() as session:
                    return build_context(
                        session,
                        system_prompt,
                        conversation_id,
                        message,
                        prompt_budget,
                        settings.context_recent_messages,
                        user_id,
                        (
                            settings.memory_recall_limit
                            if settings.memory_enabled and intent.needs_memory
                            else 0
                        ),
                        user_message_id,
                        embedding_provider,
                        settings,
                        system_addendum=system_addendum,
                        document_ids=document_ids,
                        # 未命中稳定规则时保留旧的零成本 RAG 查询门控，避免
                        # “某资料里写了什么”这类长尾表达被默认路由误伤。
                        knowledge_intent=(
                            intent.needs_knowledge if intent.source != "default" else None
                        ),
                        retrieval_query=(
                            continuation_context.original_request
                            if continuation_context and continuation_context.original_request
                            else None
                        ),
                    )

            yield AgentEvent("context.started", {"run_id": run_id})
            context = await anyio.to_thread.run_sync(_build)
            context.max_tokens = input_budget
            context.token_estimate += schema_tokens
            context.token_breakdown["tools"] = schema_tokens
            context_stats = {
                "run_id": run_id,
                "memory_count": len(context.memory_ids),
                "memory_candidate_count": context.memory_candidate_count,
                "memory_exclusion_reasons": _reason_counts(context.memory_exclusions),
                "source_count": len(context.sources),
                "knowledge_candidate_count": context.knowledge_candidate_count,
                "knowledge_exclusion_reasons": _reason_counts(context.knowledge_exclusions),
                "selected_document_count": len(document_ids or []),
                "token_estimate": context.token_estimate,
                "max_tokens": context.max_tokens,
                "context_window_tokens": model_context_window,
                "max_output_tokens": model_max_output,
                "input_budget_tokens": input_budget,
                "remaining_tokens": max(0, input_budget - context.token_estimate),
                "conversation_token_estimate": context.conversation_token_estimate,
                "token_breakdown": context.token_breakdown,
            }
            await anyio.to_thread.run_sync(
                _save_run_context_stats, run_id, context_stats
            )
            yield AgentEvent("context.completed", context_stats)
            messages = [{"role": "system", "content": context.system}] + context.messages
            if planning_document_mode:
                yield AgentEvent(
                    "planning.started", {"run_id": run_id, "phase": "document"}
                )
                document_messages = [
                    {
                        "role": "system",
                        "content": context.system
                        + "\n\n"
                        + (PROMPT_ROOT / "document.md").read_text(encoding="utf-8"),
                    },
                    *context.messages,
                ]
                result = None
                yield AgentEvent(
                    "model.started",
                    {"run_id": run_id, "phase": "planning_document"},
                )
                async for event in execute_model_loop(
                    provider,
                    document_messages,
                    None,
                    set(),
                    run_id,
                    conversation_id,
                    approval_mode="deny",
                    max_turns=1,
                    tool_budget=ToolCallBudget(0),
                ):
                    if event.type == "executor.completed":
                        result = event.data
                    else:
                        if event.type == "message.delta":
                            partial_reply += str(event.data.get("content") or "")
                        yield AgentEvent(event.type, event.data)
                if result is None:
                    raise RuntimeError("规划文档生成器未返回结果")
                reply = str(result["content"])
                usage = dict(result["usage"])
                yield AgentEvent(
                    "planning.document.completed",
                    {"run_id": run_id, "format": "markdown"},
                )
            elif execution_mode == "planned":
                if not settings.planner_enabled:
                    raise RuntimeError("Planner 已禁用")
                yield AgentEvent(
                    "planning.started", {"run_id": run_id, "phase": "resume" if resume else "create"}
                )
                if resume:
                    plan, steps, completed, used_tool_calls, checkpoint_payload = (
                        await anyio.to_thread.run_sync(_prepare_resume_plan, run_id)
                    )
                    plan_id = plan.id
                    yield AgentEvent(
                        "plan.resumed",
                        {
                            "plan_id": plan.id,
                            "goal": plan.goal,
                            "version": plan.current_version,
                            "checkpoint": checkpoint_payload,
                            "steps": [_step_event(row) for row in steps],
                        },
                    )
                else:
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
                    completed = []
                    used_tool_calls = 0
                    yield AgentEvent(
                        "plan.created",
                        {
                            "plan_id": plan.id,
                            "goal": plan.goal,
                            "version": plan.current_version,
                            "steps": [_step_event(row) for row in steps],
                        },
                    )
                    await anyio.to_thread.run_sync(
                        create_checkpoint,
                        run_id,
                        plan.id,
                        None,
                        _checkpoint_state(plan, None, completed),
                        "plan_created",
                    )
                if (
                    not resume
                    and require_plan_approval
                    and approval_mode == "interactive"
                    and activity_id is None
                ):
                    plan_approval_id = create_approval(run_id)
                    await anyio.to_thread.run_sync(
                        create_checkpoint,
                        run_id,
                        plan.id,
                        None,
                        {
                            **_checkpoint_state(plan, None, completed),
                            "pending_approval_id": plan_approval_id,
                        },
                        "awaiting_plan_approval",
                    )
                    yield AgentEvent(
                        "plan.approval.required",
                        {
                            "approval_id": plan_approval_id,
                            "run_id": run_id,
                            "plan_id": plan.id,
                            "goal": plan.goal,
                            "step_count": len(steps),
                        },
                    )
                    plan_approved = await wait_for_approval(
                        plan_approval_id, settings.approval_timeout_seconds
                    )
                    yield AgentEvent(
                        "plan.approval.completed",
                        {
                            "approval_id": plan_approval_id,
                            "run_id": run_id,
                            "plan_id": plan.id,
                            "approved": plan_approved is True,
                        },
                    )
                    if plan_approved is not True:
                        reason = (
                            "计划确认超时，未开始执行"
                            if plan_approved is None
                            else "用户取消了计划，未开始执行"
                        )
                        await anyio.to_thread.run_sync(cancel_plan_for_run, run_id)
                        await _fail_run(run_id, "cancelled", reason)
                        yield AgentEvent(
                            "run.cancelled", {"run_id": run_id, "reason": reason}
                        )
                        return
                tool_budget = ToolCallBudget(
                    remaining=max(0, settings.planner_max_tool_calls - used_tool_calls),
                    used=used_tool_calls,
                )
                while True:
                    blocked = None
                    for step in steps:
                        if step.status == "completed":
                            continue
                        await anyio.to_thread.run_sync(set_step_running, step.id)
                        await anyio.to_thread.run_sync(
                            create_checkpoint,
                            run_id,
                            plan.id,
                            step.id,
                            _checkpoint_state(plan, step, completed),
                            "step_started",
                        )
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
                            plan_id=plan.id,
                            plan_version=plan.current_version,
                            plan_step_id=step.id,
                            checkpoint_state=_checkpoint_state(plan, step, completed),
                        ):
                            if event.type == "executor.completed":
                                step_result = event.data
                            elif event.type != "message.delta":
                                yield AgentEvent(event.type, event.data)
                        if step_result is None:
                            raise RuntimeError("步骤 Executor 未返回结果")
                        step_usage = step_result["usage"]
                        _add_token_usage(usage, step_usage)
                        output = str(step_result.get("content") or "").strip()
                        if step_result.get("blocked") or not output:
                            error = "当前步骤缺少可用结果或所需工具执行失败"
                            await anyio.to_thread.run_sync(
                                finish_step, step.id, "blocked", output, error
                            )
                            await anyio.to_thread.run_sync(
                                create_checkpoint,
                                run_id,
                                plan.id,
                                step.id,
                                {
                                    **_checkpoint_state(plan, step, completed),
                                    "last_observation": output[:500] or error,
                                },
                                "step_blocked",
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
                        await anyio.to_thread.run_sync(
                            create_checkpoint,
                            run_id,
                            plan.id,
                            step.id,
                            {
                                **_checkpoint_state(plan, step, completed),
                                "last_observation": summary[:500],
                            },
                            "step_completed",
                        )
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
                        await anyio.to_thread.run_sync(
                            create_checkpoint,
                            run_id,
                            plan.id,
                            None,
                            _checkpoint_state(plan, None, completed),
                            "plan_completed",
                        )
                        yield AgentEvent("plan.completed", {"plan_id": plan.id})
                        break
                    if plan.replan_count >= settings.planner_max_replans:
                        run_status = "failed"
                        run_error = blocked["error"]
                        await anyio.to_thread.run_sync(finish_plan, plan.id, "failed", run_error)
                        await anyio.to_thread.run_sync(
                            create_checkpoint,
                            run_id,
                            plan.id,
                            None,
                            {
                                **_checkpoint_state(plan, None, completed),
                                "last_observation": run_error,
                            },
                            "plan_failed",
                        )
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
                    await anyio.to_thread.run_sync(
                        create_checkpoint,
                        run_id,
                        plan.id,
                        None,
                        _checkpoint_state(plan, None, completed),
                        "replanned",
                    )
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
                yield AgentEvent(
                    "model.started",
                    {"run_id": run_id, "phase": "synthesis"},
                )
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
                        if event.type == "message.delta":
                            partial_reply += str(event.data.get("content") or "")
                        yield AgentEvent(event.type, event.data)
                if synthesis is None:
                    raise RuntimeError("最终汇总未返回结果")
                reply = str(synthesis["content"])
                synth_usage = synthesis["usage"]
                _add_token_usage(usage, synth_usage)
            else:
                result = None
                yield AgentEvent(
                    "model.started",
                    {"run_id": run_id, "phase": "response"},
                )
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
                        if event.type == "message.delta":
                            partial_reply += str(event.data.get("content") or "")
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
        cache_stats = await _finish_run(
            run_id, conversation_id, reply, used_sources, usage, run_status, run_error
        )
    except asyncio.CancelledError:
        cancel_run_approvals(run_id)
        user_cancelled = consume_user_cancellation(run_id)
        if user_cancelled:
            await anyio.to_thread.run_sync(
                interrupt_run, run_id, "用户已停止运行；发送“继续”可从中断位置接续"
            )
            if partial_reply.strip():
                visible_sources = []
                if context is not None:
                    cited = {
                        item.lower()
                        for item in re.findall(
                            r"\[(c\d+)\]", partial_reply, flags=re.IGNORECASE
                        )
                    }
                    visible_sources = [
                        item
                        for item in context.sources
                        if item["citation_id"].lower() in cited
                    ]
                await _save_interrupted_message(
                    run_id,
                    conversation_id,
                    partial_reply,
                    visible_sources,
                )
        elif execution_mode == "planned" and not planning_document_mode:
            await anyio.to_thread.run_sync(
                interrupt_run, run_id, "连接中断，已保存恢复点"
            )
        else:
            await anyio.to_thread.run_sync(cancel_plan_for_run, run_id)
            await _fail_run(run_id, "cancelled", "用户已中止运行")
        raise
    except GeneratorExit:
        cancel_run_approvals(run_id)
        if execution_mode == "planned" and not planning_document_mode:
            await anyio.to_thread.run_sync(
                interrupt_run, run_id, "连接中断，已保存恢复点"
            )
        else:
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
            failure_reply = "规划模式未完成，系统已安全停止后续步骤。请重试或切换自主模式。"
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
                    conv = session.get(Conversation, conversation_id)
                    return save_memories(
                        session,
                        candidates,
                        user_id,
                        conversation_id,
                        settings.memory_min_importance,
                        settings.memory_min_confidence,
                        embedding_provider,
                        project_id=conv.project_id if conv else None,
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
        usage_payload = dict(usage)
        if "cached_prompt_tokens" in usage_payload and usage_payload["prompt_tokens"] > 0:
            usage_payload["cache_hit_rate"] = round(
                usage_payload["cached_prompt_tokens"] / usage_payload["prompt_tokens"] * 100,
                1,
            )
        usage_payload["average_cache_hit_rate"] = cache_stats.get(
            "average_cache_hit_rate"
        )
        yield AgentEvent("run.completed", {"run_id": run_id, "token_usage": usage_payload})


def _prepare_resume_plan(run_id: str) -> tuple[Plan, list[PlanStep], list[dict], int, dict]:
    with SessionLocal() as session:
        plan = session.query(Plan).filter(Plan.run_id == run_id).one_or_none()
        if plan is None:
            raise RuntimeError("Run 没有可恢复的 Plan")
        checkpoint = latest_checkpoint(run_id, session)
        if checkpoint is None:
            raise RuntimeError("Run 没有可恢复的 Checkpoint")
        plan.status = "running"
        plan.error = None
        plan.completed_at = None
        steps = (
            session.query(PlanStep)
            .filter(
                PlanStep.plan_id == plan.id,
                PlanStep.version == plan.current_version,
            )
            .order_by(PlanStep.position.asc())
            .all()
        )
        for step in steps:
            if step.status in {"running", "interrupted"}:
                step.status = "pending"
                step.error = None
                step.completed_at = None
        completed_rows = (
            session.query(PlanStep)
            .filter(PlanStep.plan_id == plan.id, PlanStep.status == "completed")
            .order_by(PlanStep.version.asc(), PlanStep.position.asc())
            .all()
        )
        completed = [
            {"title": row.title, "output_summary": row.output_summary or ""}
            for row in completed_rows
        ]
        used_tool_calls = session.query(ToolRun).filter(ToolRun.run_id == run_id).count()
        payload = checkpoint_dict(checkpoint)
        session.commit()
        return plan, steps, completed, used_tool_calls, payload


def _checkpoint_state(plan: Plan, step: PlanStep | None, completed: list[dict]) -> dict:
    return {
        "goal": plan.goal,
        "plan_version": plan.current_version,
        "current_step": (
            {"id": step.id, "position": step.position, "title": step.title}
            if step
            else None
        ),
        "completed_steps": [str(item.get("title") or "") for item in completed],
        "pending_approval_id": None,
        "relevant_files": [],
        "last_observation": (
            str(completed[-1].get("output_summary") or "")[:500] if completed else ""
        ),
    }


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


def _save_run_context_stats(run_id: str, context_stats: dict) -> None:
    with SessionLocal() as session:
        run = session.get(AgentRun, run_id)
        if run is not None:
            run.context_stats = context_stats
            session.commit()


async def _finish_run(
    run_id: str,
    conversation_id: str,
    reply: str,
    sources: list[dict],
    usage: dict,
    status: str = "completed",
    error: str = "",
) -> dict:
    def _finish() -> dict:
        with SessionLocal() as session:
            session.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=reply,
                    citations=sources or None,
                    run_id=run_id,
                    status="completed",
                )
            )
            run = session.get(AgentRun, run_id)
            if run:
                run.status = status
                run.error = error[:MAX_SUMMARY_CHARS] or None
                run.completed_at = datetime.now(timezone.utc)
                run.input_tokens = usage.get("prompt_tokens", 0)
                run.cached_input_tokens = (
                    int(usage.get("cached_prompt_tokens") or 0)
                    if "cached_prompt_tokens" in usage
                    else None
                )
                run.output_tokens = usage.get("completion_tokens", 0)
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.updated_at = datetime.now(timezone.utc)
            session.flush()
            stats = conversation_cache_stats(session, conversation_id)
            session.commit()
            return stats

    return await anyio.to_thread.run_sync(_finish)


async def _save_interrupted_message(
    run_id: str,
    conversation_id: str,
    content: str,
    sources: list[dict],
) -> bool:
    """只在 Run 确认中断后保存一次可见草稿，避免完成态产生重复消息。"""

    def _save() -> bool:
        with SessionLocal() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.status != "interrupted":
                return False
            existing = (
                session.query(Message)
                .filter(
                    Message.run_id == run_id,
                    Message.role == "assistant",
                    Message.status == "interrupted",
                )
                .one_or_none()
            )
            if existing is not None:
                existing.content = content.strip()
                existing.citations = sources or None
            else:
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=content.strip(),
                        citations=sources or None,
                        run_id=run_id,
                        status="interrupted",
                    )
                )
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.updated_at = datetime.now(timezone.utc)
            session.commit()
            return True

    return await anyio.to_thread.run_sync(_save)


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
