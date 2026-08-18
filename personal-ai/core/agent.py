"""Agent Runtime：一次 Agent Run 的最小循环（P0 无工具调用，单次 LLM 流式回答）。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

import anyio

from core.character import load_character, render_system_prompt
from core.context import build_context
from core.memory import extract_memories, save_memories
from core.summary import update_conversation_summary
from infrastructure.config import settings
from infrastructure.database import AgentRun, Conversation, Message, SessionLocal


logger = logging.getLogger(__name__)


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
) -> AsyncIterator[AgentEvent]:
    """执行一次 Agent Run，产出 SSE 事件流（Agent Event Protocol 基础事件）。"""
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

    try:
        async with asyncio.timeout(settings.agent_timeout_seconds):
            character = await anyio.to_thread.run_sync(load_character, settings.character_file)
            system_prompt = await anyio.to_thread.run_sync(
                render_system_prompt, character, settings.system_prompt_file
            )

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
                    )

            context = await anyio.to_thread.run_sync(_build)
            messages = [{"role": "system", "content": context.system}] + context.messages
            if context.sources:
                yield AgentEvent("rag.retrieved", {"sources": context.sources})

            parts: list[str] = []
            usage: dict = {}
            async for chunk in provider.stream(messages):
                if chunk.text:
                    parts.append(chunk.text)
                    yield AgentEvent("message.delta", {"content": chunk.text})
                if chunk.usage:
                    usage = chunk.usage
            reply = "".join(parts)

        allowed_citations = {item["citation_id"] for item in context.sources}
        cited = {item.lower() for item in re.findall(r"\[(c\d+)\]", reply, flags=re.IGNORECASE)}
        unknown = cited - allowed_citations
        if unknown:
            logger.warning("模型返回未知引用：%s", ", ".join(sorted(unknown)))

        def _finish_run():
            with SessionLocal() as session:
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=reply,
                        citations=context.sources or None,
                    )
                )
                run = session.get(AgentRun, run_id)
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                run.input_tokens = usage.get("prompt_tokens", 0)
                run.output_tokens = usage.get("completion_tokens", 0)
                conversation = session.get(Conversation, conversation_id)
                conversation.updated_at = datetime.now(timezone.utc)
                session.commit()

        await anyio.to_thread.run_sync(_finish_run)
    except Exception as e:
        def _fail_run():
            with SessionLocal() as session:
                run = session.get(AgentRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.error = str(e)[:500]
                    run.completed_at = datetime.now(timezone.utc)
                    session.commit()

        await anyio.to_thread.run_sync(_fail_run)
        yield AgentEvent("run.failed", {"run_id": run_id, "error": str(e)})
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
