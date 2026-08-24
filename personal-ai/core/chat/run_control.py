"""交互式聊天 Run 的进程内取消注册表。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveChatRun:
    conversation_id: str
    task: asyncio.Task


ACTIVE_CHAT_RUNS: dict[str, ActiveChatRun] = {}
USER_CANCELLED_RUNS: set[str] = set()


def register_chat_run(run_id: str, conversation_id: str) -> None:
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("聊天 Run 必须在 asyncio Task 中执行")
    existing = ACTIVE_CHAT_RUNS.get(run_id)
    if existing is not None and not existing.task.done():
        raise RuntimeError("run_id 已被正在运行的任务使用")
    ACTIVE_CHAT_RUNS[run_id] = ActiveChatRun(conversation_id=conversation_id, task=task)


def unregister_chat_run(run_id: str) -> None:
    ACTIVE_CHAT_RUNS.pop(run_id, None)


def cancel_chat_run(run_id: str) -> bool:
    active = ACTIVE_CHAT_RUNS.get(run_id)
    if active is None or active.task.done():
        return False
    USER_CANCELLED_RUNS.add(run_id)
    active.task.cancel()
    return True


def consume_user_cancellation(run_id: str) -> bool:
    if run_id not in USER_CANCELLED_RUNS:
        return False
    USER_CANCELLED_RUNS.discard(run_id)
    return True
