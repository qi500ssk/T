"""QQ 音乐可执行文件发现与安全校验。"""

from __future__ import annotations

import os
import re
from pathlib import Path


class DesktopMediaError(ValueError):
    """可安全返回给 MCP Client 的桌面媒体错误。"""


def _version_key(path: Path) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", path.parent.name)
    return tuple(int(item) for item in numbers) or (0,)


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    configured = os.getenv("QQMUSIC_EXE", "").strip()
    if configured:
        candidates.append(Path(configured))

    roots = {
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("LOCALAPPDATA", "")),
    }
    for root in roots:
        if not str(root) or not root.is_dir():
            continue
        candidates.extend(root.glob("Tencent/QQMusic/QQMusic*/QQMusic.exe"))
        candidates.extend(root.glob("QQMusic/QQMusic*/QQMusic.exe"))
        candidates.extend(root.glob("QQMusic/QQMusic.exe"))
    return candidates


def validate_qqmusic_executable(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DesktopMediaError(f"QQ 音乐程序不存在：{candidate}") from exc
    if not resolved.is_file() or resolved.name.lower() != "qqmusic.exe":
        raise DesktopMediaError("只允许启动经过校验的 QQMusic.exe")
    return resolved


def discover_qqmusic_executable() -> Path:
    configured = os.getenv("QQMUSIC_EXE", "").strip()
    if configured:
        return validate_qqmusic_executable(configured)

    valid: list[Path] = []
    for candidate in _candidate_paths():
        try:
            valid.append(validate_qqmusic_executable(candidate))
        except DesktopMediaError:
            continue
    if not valid:
        raise DesktopMediaError(
            "未找到 QQMusic.exe；请在 MCP 环境变量中设置 QQMUSIC_EXE 的完整路径"
        )
    return max(dict.fromkeys(valid), key=_version_key)
