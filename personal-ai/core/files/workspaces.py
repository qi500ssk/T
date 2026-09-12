"""所有文件夹入口共用的工作区根限制。根目录只从环境配置读取，页面不能扩大授权范围。"""

from pathlib import Path
from infrastructure.config import settings


def workspace_root() -> Path:
    return Path(settings.workspace_root_dir).expanduser().resolve()


def resolve_workspace(raw: str | Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("请选择绝对文件夹路径")
    root = workspace_root()
    # resolve 前检查整条路径，拒绝通过符号链接或 Windows junction 进入。
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or (getattr(part, "is_junction", lambda: False)()):
            raise ValueError("工作区不允许符号链接或目录联接")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("只能选择已配置工作区根目录内的文件夹") from exc
    if not resolved.is_dir():
        raise ValueError("选择的路径不是文件夹")
    return resolved
