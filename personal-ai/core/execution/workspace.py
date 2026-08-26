"""Run 级编码文件夹上下文，避免并行对话共享可变的全局目录。"""

from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path

from infrastructure.config import settings


_UNBOUND = object()
_WORKSPACE: ContextVar[str | None | object] = ContextVar(
    "coding_workspace", default=_UNBOUND
)


def bind_coding_workspace(path: str | None) -> Token:
    """把当前对话所属文件夹固定到本次 Run。None 表示未选择文件夹。"""
    return _WORKSPACE.set(str(Path(path).resolve()) if path else None)


def reset_coding_workspace(token: Token) -> None:
    _WORKSPACE.reset(token)


def current_coding_workspace() -> Path | None:
    """返回本次 Run 的文件夹；Run 外保留旧配置作为内部兼容回退。"""
    value = _WORKSPACE.get()
    if value is _UNBOUND:
        return Path(settings.coding_workspace_dir).resolve()
    if value is None:
        return None
    return Path(str(value)).resolve()
