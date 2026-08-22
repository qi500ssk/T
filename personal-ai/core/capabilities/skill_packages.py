"""能力域本地 Skill 文件夹的安全导入、新建与可恢复删除。"""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from core.capabilities.skills import (
    SKILL_ID_RE,
    SkillRecord,
    parse_skill_document,
    render_skill_document,
)
from core.execution.tools import TOOLS
from infrastructure.config import settings


MAX_FOLDER_FILES = 100
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FOLDER_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".pdf", ".docx",
}


class SkillPackageError(ValueError):
    pass


class SkillConflictError(SkillPackageError):
    pass


def _slug(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")[:64]
    if len(value) < 2:
        value = f"skill-{uuid.uuid4().hex[:8]}"
    if not SKILL_ID_RE.fullmatch(value):
        raise SkillPackageError("Skill 文件夹名只能包含小写字母、数字和连字符")
    return value


def _safe_relative(raw: str) -> PurePosixPath:
    if not raw or "\\" in raw or "\x00" in raw:
        raise SkillPackageError("文件夹中存在不安全路径")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SkillPackageError("文件夹中存在不安全路径")
    if any(":" in part for part in path.parts):
        raise SkillPackageError("文件夹中存在不安全路径")
    return path


def _normalize_entries(entries: list[tuple[str, bytes]]) -> tuple[str, list[tuple[PurePosixPath, bytes]]]:
    if not entries or len(entries) > MAX_FOLDER_FILES:
        raise SkillPackageError(f"文件数量必须在 1 到 {MAX_FOLDER_FILES} 之间")
    parsed = [(_safe_relative(path), content) for path, content in entries]
    first_parts = {path.parts[0] for path, _ in parsed if len(path.parts) > 1}
    strip_root = len(first_parts) == 1 and all(len(path.parts) > 1 for path, _ in parsed)
    folder_name = next(iter(first_parts)) if strip_root else "imported-skill"
    normalized: list[tuple[PurePosixPath, bytes]] = []
    seen: set[str] = set()
    total = 0
    for path, content in parsed:
        relative = PurePosixPath(*path.parts[1:]) if strip_root else path
        key = relative.as_posix().lower()
        if key in seen:
            raise SkillPackageError("文件夹中存在重复文件")
        seen.add(key)
        if len(content) > MAX_FILE_BYTES:
            raise SkillPackageError(f"单个文件不能超过 {MAX_FILE_BYTES // 1024 // 1024}MB")
        total += len(content)
        if total > MAX_FOLDER_BYTES:
            raise SkillPackageError(f"Skill 文件夹不能超过 {MAX_FOLDER_BYTES // 1024 // 1024}MB")
        if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise SkillPackageError(f"不允许导入文件类型：{relative.suffix or '无扩展名'}")
        normalized.append((relative, content))
    skill_docs = [item for item in normalized if item[0].as_posix().lower() == "skill.md"]
    if len(skill_docs) != 1:
        raise SkillPackageError("所选文件夹根目录必须有且只能有一个 SKILL.md")
    return folder_name, normalized


def install_skill_folder(entries: list[tuple[str, bytes]]) -> SkillRecord:
    """校验浏览器上传的普通文件夹并原子安装；新 Skill 默认关闭。"""
    folder_name, normalized = _normalize_entries(entries)
    raw_skill = next(content for path, content in normalized if path.as_posix().lower() == "skill.md")
    try:
        text = raw_skill.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillPackageError("SKILL.md 必须使用 UTF-8 编码") from exc
    provisional = parse_skill_document(
        "pending",
        text,
        source_override="local",
        enabled_override=False,
        enforce_identity=False,
    )
    skill_id = _slug(folder_name if folder_name != "imported-skill" else provisional.name)
    record = replace(provisional, id=skill_id, name=skill_id)

    root = Path(settings.skills_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / skill_id
    if target.exists():
        raise SkillConflictError(f"Skill {skill_id} 已存在")
    staging = Path(tempfile.mkdtemp(prefix=".skill-import-", dir=root))
    try:
        for relative, content in normalized:
            destination = staging.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (staging / "SKILL.md").write_text(render_skill_document(record), encoding="utf-8")
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return record


def create_skill(
    skill_id: str,
    name: str,
    description: str,
    instructions: str,
    required_tools: list[str],
) -> SkillRecord:
    if not SKILL_ID_RE.fullmatch(skill_id):
        raise SkillPackageError("ID 只能包含小写字母、数字和连字符，长度 2-64")
    unknown = sorted(set(required_tools) - set(TOOLS))
    if unknown:
        raise SkillPackageError(f"不存在的工具：{', '.join(unknown)}")
    record = SkillRecord(
        id=skill_id,
        name=skill_id,
        description=description.strip(),
        required_tools=tuple(dict.fromkeys(required_tools)),
        instructions=instructions.strip(),
        source="local",
        default_enabled=False,
        available=True,
    )
    if not name.strip() or not record.description or not record.instructions:
        raise SkillPackageError("名称、说明和执行指令不能为空")
    root = Path(settings.skills_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / skill_id
    if target.exists():
        raise SkillConflictError(f"Skill {skill_id} 已存在")
    staging = Path(tempfile.mkdtemp(prefix=".skill-create-", dir=root))
    try:
        (staging / "SKILL.md").write_text(render_skill_document(record), encoding="utf-8")
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return record


def remove_local_skill(record: SkillRecord) -> Path:
    if record.source not in {"local", "online"}:
        raise SkillConflictError("内置和开发测试 Skill 不能删除")
    root = Path(settings.skills_dir).resolve()
    target = (root / record.id).resolve()
    if target.parent != root or not target.is_dir() or target.is_symlink():
        raise SkillPackageError("Skill 文件夹不存在或路径不安全")
    trash_root = Path(settings.skill_trash_dir).resolve()
    trash_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = trash_root / f"{record.id}-{stamp}-{uuid.uuid4().hex[:6]}"
    shutil.move(str(target), str(destination))
    return destination
