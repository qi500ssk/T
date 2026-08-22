"""执行域 Tool Hook：扩展安全策略和结果规范化。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping

from core.execution.tools import ToolExecution


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolInvocation:
    run_id: str
    conversation_id: str
    step_index: int
    name: str
    arguments: Mapping[str, object]
    risk_level: str

    @classmethod
    def create(
        cls,
        run_id: str,
        conversation_id: str,
        step_index: int,
        name: str,
        arguments: dict,
        risk_level: str,
    ) -> "ToolInvocation":
        return cls(
            run_id=run_id,
            conversation_id=conversation_id,
            step_index=step_index,
            name=name,
            arguments=MappingProxyType(dict(arguments)),
            risk_level=risk_level,
        )


PreToolHook = Callable[[ToolInvocation], Awaitable[str | None]]
PostToolHook = Callable[[ToolInvocation, ToolExecution], Awaitable[ToolExecution]]
_pre_hooks: list[PreToolHook] = []
_post_hooks: list[PostToolHook] = []


def register_pre_tool_hook(hook: PreToolHook) -> Callable[[], None]:
    _pre_hooks.append(hook)

    def dispose() -> None:
        if hook in _pre_hooks:
            _pre_hooks.remove(hook)

    return dispose


def register_post_tool_hook(hook: PostToolHook) -> Callable[[], None]:
    _post_hooks.append(hook)

    def dispose() -> None:
        if hook in _post_hooks:
            _post_hooks.remove(hook)

    return dispose


async def run_pre_tool_hooks(invocation: ToolInvocation) -> str | None:
    """返回拒绝原因；策略异常采用 fail-closed。"""
    for hook in tuple(_pre_hooks):
        try:
            reason = await hook(invocation)
        except Exception:
            logger.exception("工具前置安全策略异常：%s", invocation.name)
            return "工具安全策略执行失败，已拒绝调用"
        if reason:
            return reason
    return None


async def run_post_tool_hooks(
    invocation: ToolInvocation, execution: ToolExecution
) -> ToolExecution:
    """按注册顺序处理结果；观察器异常不抹掉已经产生的权威结果。"""
    current = execution
    for hook in tuple(_post_hooks):
        try:
            current = await hook(invocation, current)
            if not isinstance(current, ToolExecution):
                raise TypeError("post hook 必须返回 ToolExecution")
        except Exception:
            logger.exception("工具后置处理异常：%s", invocation.name)
    return current
