"""长期记忆工具：把聊天中的显式记忆管理连接到统一 memories 表。"""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone

import anyio
from sqlalchemy import and_, or_

from core.chat.memory import (
    MemoryCandidate,
    contains_sensitive_information,
    normalize_memory_key,
    retrieve_memories,
    revise_memory,
    save_memories,
)
from infrastructure.database import Conversation, Memory, SessionLocal


MEMORY_TOOL_NAMES = {
    "memory_list",
    "memory_create",
    "memory_update",
    "memory_forget",
}


@dataclass(frozen=True)
class MemoryToolContext:
    user_id: str
    conversation_id: str
    embedding_provider: object | None


_MEMORY_CONTEXT: ContextVar[MemoryToolContext | None] = ContextVar(
    "memory_tool_context", default=None
)


def bind_memory_tool_context(
    user_id: str,
    conversation_id: str,
    embedding_provider=None,
) -> Token:
    return _MEMORY_CONTEXT.set(
        MemoryToolContext(user_id, conversation_id, embedding_provider)
    )


def reset_memory_tool_context(token: Token) -> None:
    _MEMORY_CONTEXT.reset(token)


def _context() -> MemoryToolContext:
    value = _MEMORY_CONTEXT.get()
    if value is None:
        raise ValueError("当前 Run 没有绑定记忆上下文")
    return value


def _scope_for_context(
    requested: str,
    conversation: Conversation,
) -> tuple[str, str]:
    if requested == "global":
        return "global", "global"
    if requested == "project" and conversation.project_id:
        return "project", conversation.project_id
    return "conversation", conversation.id


def _visible(memory: Memory, conversation: Conversation) -> bool:
    return (
        (memory.scope_type == "global" and memory.scope_key == "global")
        or (
            memory.scope_type == "project"
            and conversation.project_id is not None
            and memory.scope_key == conversation.project_id
        )
        or (
            memory.scope_type == "conversation"
            and memory.scope_key == conversation.id
        )
    )


def _memory_payload(memory: Memory) -> dict:
    return {
        "id": memory.id,
        "content": memory.content,
        "kind": memory.kind,
        "scope_type": memory.scope_type,
        "scope_key": memory.scope_key,
        "importance": memory.importance,
        "is_active": memory.is_active,
        "status": memory.status,
    }


def _list_sync(args: dict) -> str:
    context = _context()
    query = str(args.get("query") or "").strip()
    limit = max(1, min(20, int(args.get("limit") or 10)))
    with SessionLocal() as session:
        conversation = session.get(Conversation, context.conversation_id)
        if conversation is None:
            raise ValueError("当前会话不存在")
        if query:
            rows = retrieve_memories(
                session,
                context.user_id,
                query,
                limit,
                embedding_provider=context.embedding_provider,
                conversation_id=conversation.id,
                project_id=conversation.project_id,
            )
        else:
            scope = [
                and_(Memory.scope_type == "global", Memory.scope_key == "global"),
                and_(
                    Memory.scope_type == "conversation",
                    Memory.scope_key == conversation.id,
                ),
            ]
            if conversation.project_id:
                scope.append(
                    and_(
                        Memory.scope_type == "project",
                        Memory.scope_key == conversation.project_id,
                    )
                )
            rows = (
                session.query(Memory)
                .filter(
                    Memory.user_id == context.user_id,
                    Memory.status == "active",
                    Memory.is_active.is_(True),
                    or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now(timezone.utc)),
                    or_(*scope),
                )
                .order_by(Memory.importance.desc(), Memory.updated_at.desc())
                .limit(limit)
                .all()
            )
        return json.dumps(
            {"count": len(rows), "memories": [_memory_payload(row) for row in rows]},
            ensure_ascii=False,
        )


async def memory_list(args: dict) -> str:
    return await anyio.to_thread.run_sync(_list_sync, args)


def _create_sync(args: dict) -> str:
    context = _context()
    content = str(args.get("content") or "").strip()
    if not content or len(content) > 2000:
        raise ValueError("记忆内容长度必须为 1-2000 个字符")
    if contains_sensitive_information(content):
        raise ValueError("记忆内容包含敏感信息，已拒绝保存")
    kind = str(args.get("kind") or "semantic")
    importance = int(args.get("importance") or 3)
    requested_scope = str(args.get("scope_type") or "conversation")
    key = normalize_memory_key(str(args.get("key") or ""), content)
    with SessionLocal() as session:
        conversation = session.get(Conversation, context.conversation_id)
        if conversation is None:
            raise ValueError("当前会话不存在")
        actual_scope, actual_key = _scope_for_context(requested_scope, conversation)
        saved = save_memories(
            session,
            [MemoryCandidate(key, kind, content, importance, 1.0, actual_scope)],
            context.user_id,
            conversation.id,
            1,
            0.0,
            context.embedding_provider,
            project_id=conversation.project_id,
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        memory = (
            session.query(Memory)
            .filter(
                Memory.user_id == context.user_id,
                Memory.scope_type == actual_scope,
                Memory.scope_key == actual_key,
                Memory.content_hash == content_hash,
                Memory.status == "active",
            )
            .order_by(Memory.created_at.desc())
            .first()
        )
        if memory is None:
            raise ValueError("记忆没有成功写入")
        return json.dumps(
            {
                "result": "created" if saved else "already_exists",
                "memory": _memory_payload(memory),
            },
            ensure_ascii=False,
        )


async def memory_create(args: dict) -> str:
    return await anyio.to_thread.run_sync(_create_sync, args)


def _get_manageable_memory(session, memory_id: str, context: MemoryToolContext) -> tuple[Memory, Conversation]:
    conversation = session.get(Conversation, context.conversation_id)
    memory = session.get(Memory, memory_id)
    if conversation is None:
        raise ValueError("当前会话不存在")
    if memory is None or memory.user_id != context.user_id or not _visible(memory, conversation):
        raise ValueError("记忆不存在或不在当前可见作用域")
    return memory, conversation


def _update_sync(args: dict) -> str:
    context = _context()
    memory_id = str(args.get("memory_id") or "").strip()
    if not memory_id:
        raise ValueError("缺少 memory_id；请先调用 memory_list 查找")
    with SessionLocal() as session:
        memory, conversation = _get_manageable_memory(session, memory_id, context)
        requested_scope = args.get("scope_type")
        actual_scope = None
        actual_key = None
        if requested_scope is not None:
            actual_scope, actual_key = _scope_for_context(str(requested_scope), conversation)
        replacement = revise_memory(
            session,
            memory,
            content=(str(args["content"]).strip() if "content" in args else None),
            kind=(str(args["kind"]) if "kind" in args else None),
            importance=(int(args["importance"]) if "importance" in args else None),
            scope_type=actual_scope,
            scope_key=actual_key,
            embedding_provider=context.embedding_provider,
        )
        return json.dumps(
            {"result": "updated", "memory": _memory_payload(replacement)},
            ensure_ascii=False,
        )


async def memory_update(args: dict) -> str:
    return await anyio.to_thread.run_sync(_update_sync, args)


def _forget_sync(args: dict) -> str:
    context = _context()
    memory_id = str(args.get("memory_id") or "").strip()
    if not memory_id:
        raise ValueError("缺少 memory_id；请先调用 memory_list 查找")
    with SessionLocal() as session:
        memory, _ = _get_manageable_memory(session, memory_id, context)
        if memory.status != "active":
            raise ValueError("该记忆已经失效")
        memory.is_active = False
        memory.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(memory)
        return json.dumps(
            {"result": "forgotten", "memory": _memory_payload(memory)},
            ensure_ascii=False,
        )


async def memory_forget(args: dict) -> str:
    return await anyio.to_thread.run_sync(_forget_sync, args)
