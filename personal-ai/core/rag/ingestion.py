"""文档安全落盘与同步索引管线。"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.rag.chunking import split_into_chunks
from core.rag.parsers import ParseError, ResourceLimitError, parse_document
from infrastructure.database import Document, DocumentChunk, SessionLocal


class UnsupportedFileError(ValueError):
    pass


_MIME_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
}


def validate_file(data: bytes, filename: str, mime_type: str, settings) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in settings.file_allowed_extension_set:
        raise UnsupportedFileError(f"不支持的扩展名：{extension or '无'}")
    normalized_mime = (mime_type or "application/octet-stream").split(";", 1)[0].lower()
    if normalized_mime not in _MIME_TYPES[extension]:
        raise UnsupportedFileError(f"文件 MIME 与扩展名不匹配：{normalized_mime}")
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise UnsupportedFileError("文件头不是有效的 PDF")
    if extension == ".docx" and not data.startswith(b"PK"):
        raise UnsupportedFileError("文件头不是有效的 DOCX")
    if extension in {".txt", ".md"}:
        if b"\x00" in data[:4096]:
            raise UnsupportedFileError("文本文件包含二进制内容")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                data.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise UnsupportedFileError("文本文件编码不受支持") from exc
    return extension


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_root(settings) -> Path:
    root = Path(settings.file_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_file(data: bytes, extension: str, settings) -> str:
    filename = f"{uuid.uuid4().hex}{extension}"
    path = storage_root(settings) / filename
    path.write_bytes(data)
    return filename


def resolve_stored_file(stored_filename: str, settings) -> Path:
    root = storage_root(settings)
    path = (root / stored_filename).resolve()
    if path.parent != root or not path.is_file():
        raise FileNotFoundError("原文件不存在")
    return path


def _set_document_status(document_id: str, status: str, error: str | None = None, chunk_count: int = 0) -> None:
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            return
        document.status = status
        document.error = error[:1000] if error else None
        document.chunk_count = chunk_count
        document.updated_at = datetime.now(timezone.utc)
        session.commit()


def index_document(document_id: str, embedding_provider, settings) -> str:
    """在线程池内执行 parse → chunk → embed → persist，返回最终状态。"""
    started = time.monotonic()

    def check_timeout() -> None:
        if time.monotonic() - started > settings.index_timeout_seconds:
            raise ResourceLimitError(f"索引时间超过限制：{settings.index_timeout_seconds:g} 秒")

    _set_document_status(document_id, "indexing")
    try:
        with SessionLocal() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise ParseError("document not found")
            path = resolve_stored_file(document.stored_filename, settings)
            extension = document.file_type

        result = parse_document(path, extension, settings)
        check_timeout()
        if result.needs_ocr:
            _set_document_status(document_id, "needs_ocr", "扫描件或可提取文本过少")
            return "needs_ocr"
        drafts = split_into_chunks(result.blocks, embedding_provider.count_tokens, settings)
        if not drafts:
            raise ParseError("文档没有可索引文本")
        check_timeout()

        vectors: list[list[float]] = []
        contents = [draft.content for draft in drafts]
        for start in range(0, len(contents), settings.embedding_batch_size):
            vectors.extend(
                embedding_provider.embed_documents(contents[start : start + settings.embedding_batch_size])
            )
            check_timeout()

        with SessionLocal() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise ParseError("document not found")
            session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
            for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
                session.add(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=index,
                        section=draft.section,
                        content=draft.content,
                        page_start=draft.page_start,
                        page_end=draft.page_end,
                        char_start=draft.char_start,
                        char_end=draft.char_end,
                        embedding=vector,
                    )
                )
            document.status = "indexed"
            document.error = None
            document.chunk_count = len(drafts)
            document.updated_at = datetime.now(timezone.utc)
            session.commit()
        return "indexed"
    except Exception as exc:
        _set_document_status(document_id, "failed", str(exc), 0)
        return "failed"
