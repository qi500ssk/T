"""文件域 Artifact：受限存储、元数据与下载定位。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from infrastructure.config import settings


ARTIFACT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
INVALID_FILENAME = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
SUPPORTED_SUFFIXES = {".docx", ".pdf", ".pptx", ".xlsx"}


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    filename: str
    path: Path
    size_bytes: int
    created_at: str

    @property
    def download_url(self) -> str:
        base = settings.artifact_public_base_url.rstrip("/")
        return f"{base}/api/artifacts/{self.id}"

    def public(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "download_url": self.download_url,
        }


def safe_filename(raw: str, suffix: str) -> str:
    suffix = suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ArtifactError("不支持的生成文件类型")
    stem = Path(str(raw or "生成文档")).stem.strip().strip(". ")
    stem = INVALID_FILENAME.sub("_", stem)
    stem = re.sub(r"\s+", " ", stem)[:100].strip()
    if not stem:
        stem = "生成文档"
    return f"{stem}{suffix}"


def allocate_artifact(filename: str, suffix: str) -> tuple[str, Path, str]:
    artifact_id = uuid.uuid4().hex
    display_name = safe_filename(filename, suffix)
    root = Path(settings.artifacts_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    folder = root / artifact_id
    folder.mkdir()
    return artifact_id, folder / f"artifact{suffix.lower()}", display_name


def discard_artifact(artifact_id: str) -> None:
    if not ARTIFACT_ID_RE.fullmatch(artifact_id):
        return
    root = Path(settings.artifacts_dir).resolve()
    target = (root / artifact_id).resolve()
    if target.parent == root:
        shutil.rmtree(target, ignore_errors=True)


def finalize_artifact(artifact_id: str, path: Path, filename: str) -> ArtifactRecord:
    if not ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise ArtifactError("生成文件 ID 无效")
    root = Path(settings.artifacts_dir).resolve()
    folder = (root / artifact_id).resolve()
    resolved = path.resolve()
    if folder.parent != root or resolved.parent != folder:
        raise ArtifactError("生成文件路径越界")
    if not resolved.is_file():
        raise ArtifactError("生成文件不存在")
    size = resolved.stat().st_size
    if size <= 0 or size > settings.artifact_max_bytes:
        raise ArtifactError("生成文件为空或超过大小限制")
    created_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "id": artifact_id,
        "filename": safe_filename(filename, resolved.suffix),
        "stored_name": resolved.name,
        "size_bytes": size,
        "created_at": created_at,
    }
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=folder, prefix=".metadata-", suffix=".json", delete=False
    ) as handle:
        json.dump(metadata, handle, ensure_ascii=False)
        temporary = Path(handle.name)
    temporary.replace(folder / "metadata.json")
    return ArtifactRecord(
        artifact_id, metadata["filename"], resolved, size, created_at
    )


def resolve_artifact(artifact_id: str) -> ArtifactRecord:
    if not ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise ArtifactError("生成文件不存在")
    root = Path(settings.artifacts_dir).resolve()
    folder = (root / artifact_id).resolve()
    if folder.parent != root or not folder.is_dir() or folder.is_symlink():
        raise ArtifactError("生成文件不存在")
    try:
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        stored_name = str(metadata["stored_name"])
        path = (folder / stored_name).resolve()
        if path.parent != folder or not path.is_file() or path.is_symlink():
            raise ArtifactError("生成文件不存在")
        size = path.stat().st_size
        return ArtifactRecord(
            artifact_id,
            safe_filename(str(metadata["filename"]), path.suffix),
            path,
            size,
            str(metadata["created_at"]),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("生成文件不存在或元数据损坏") from exc


def list_artifacts(limit: int = 100) -> list[ArtifactRecord]:
    root = Path(settings.artifacts_dir).resolve()
    if not root.exists():
        return []
    rows: list[ArtifactRecord] = []
    for folder in root.iterdir():
        if len(rows) >= limit:
            break
        try:
            rows.append(resolve_artifact(folder.name))
        except ArtifactError:
            continue
    return sorted(rows, key=lambda item: item.created_at, reverse=True)[:limit]


def artifact_tool_result(record: ArtifactRecord) -> str:
    payload = json.dumps(record.public(), ensure_ascii=False, separators=(",", ":"))
    return (
        f"ARTIFACT_JSON:{payload}\n"
        f"文件已生成：[{record.filename}]({record.download_url})。"
        "请在最终回答中保留这个 Markdown 下载链接。"
    )
