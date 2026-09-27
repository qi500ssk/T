"""所有文件夹入口共用的目录限制：环境根目录及本机系统选择器明确授权的目录。"""

import json
import threading
from pathlib import Path
from infrastructure.config import settings


def workspace_root() -> Path:
    return Path(settings.workspace_root_dir).expanduser().resolve()


_grant_lock = threading.Lock()


def _grants() -> list[str]:
    path = Path(settings.workspace_grants_file)
    if not path.exists():
        return []
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError("文件夹授权记录无效")
    return values


def _real_directory(raw: str | Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("请选择绝对文件夹路径")
    # resolve 前检查整条路径，拒绝通过符号链接或 Windows junction 进入。
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or (getattr(part, "is_junction", lambda: False)()):
            raise ValueError("工作区不允许符号链接或目录联接")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("只能选择已配置工作区根目录内的文件夹") from exc
    if not resolved.is_dir():
        raise ValueError("选择的路径不是文件夹")
    return resolved


def authorize_selected_folder(raw: str) -> Path:
    """Only called with the result of the OS picker, never request JSON."""
    resolved = _real_directory(raw)
    with _grant_lock:
        values = _grants()
        if str(resolved) not in values:
            values.append(str(resolved))
            path = Path(settings.workspace_grants_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
    return resolved


def resolve_workspace(raw: str | Path) -> Path:
    resolved = _real_directory(raw)
    roots = [workspace_root(), *(Path(p) for p in _grants())]
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError("只能选择已配置工作区根目录或本机明确授权的文件夹")
    return resolved
