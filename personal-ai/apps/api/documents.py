"""知识库文档上传、查询、原文读取、删除与检索预览 API。"""

from __future__ import annotations

import logging
from pathlib import Path

import anyio
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError

from core.rag.ingestion import (
    UnsupportedFileError,
    content_hash,
    index_document,
    resolve_stored_file,
    save_file,
    validate_file,
)
from core.rag.retrieval import retrieve
from infrastructure.config import settings
from infrastructure.database import Document, DocumentChunk, SessionLocal


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _document_dict(document: Document) -> dict:
    # Keep local model filesystem paths out of API responses and the UI.
    model_name = document.embedding_model
    for part in reversed(Path(model_name).parts):
        if "--" in part:
            model_name = part.replace("--", "/", 1)
            break
    return {
        "id": document.id,
        "original_filename": document.original_filename,
        "mime_type": document.mime_type,
        "file_type": document.file_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "error": document.error,
        "chunk_count": document.chunk_count,
        "embedding_model": model_name,
        "embedding_dim": document.embedding_dim,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _chunk_dict(chunk: DocumentChunk) -> dict:
    return {
        "id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "section": chunk.section,
        "content": chunk.content,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
    }


@router.post("/files", status_code=201)
async def upload_file(request: Request, file: UploadFile = File(...)):
    data = await file.read(settings.file_max_bytes + 1)
    if len(data) > settings.file_max_bytes:
        raise HTTPException(413, f"文件大小超过限制：{settings.file_max_bytes} 字节")
    if not data:
        raise HTTPException(415, "文件内容为空")
    original_filename = Path(file.filename or "").name
    try:
        extension = validate_file(data, original_filename, file.content_type or "", settings)
    except UnsupportedFileError as exc:
        raise HTTPException(415, str(exc)) from exc

    digest = content_hash(data)
    with SessionLocal() as session:
        existing = (
            session.query(Document)
            .filter(Document.user_id == "default", Document.content_hash == digest)
            .first()
        )
        if existing:
            raise HTTPException(409, {"message": "相同文件已存在", "document_id": existing.id})

    stored_filename = save_file(data, extension, settings)
    provider = request.app.state.embedding_provider
    document = Document(
        user_id="default",
        original_filename=original_filename,
        stored_filename=stored_filename,
        mime_type=(file.content_type or "application/octet-stream").split(";", 1)[0],
        file_type=extension,
        size_bytes=len(data),
        status="pending",
        content_hash=digest,
        embedding_model=provider.model_name,
        embedding_dim=provider.dimension,
    )
    try:
        with SessionLocal() as session:
            session.add(document)
            session.commit()
    except IntegrityError as exc:
        path = resolve_stored_file(stored_filename, settings)
        path.unlink(missing_ok=True)
        with SessionLocal() as session:
            existing = (
                session.query(Document)
                .filter(Document.user_id == "default", Document.content_hash == digest)
                .first()
            )
        raise HTTPException(
            409,
            {"message": "相同文件已存在", "document_id": existing.id if existing else None},
        ) from exc

    await anyio.to_thread.run_sync(index_document, document.id, provider, settings)
    with SessionLocal() as session:
        indexed = session.get(Document, document.id)
        return _document_dict(indexed)


@router.get("/documents")
def list_documents():
    with SessionLocal() as session:
        rows = session.query(Document).order_by(Document.created_at.desc()).all()
        return [_document_dict(row) for row in rows]


@router.get("/documents/{document_id}")
def get_document(document_id: str):
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(404, "document not found")
        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(20)
            .all()
        )
        return {**_document_dict(document), "chunks": [_chunk_dict(chunk) for chunk in chunks]}


@router.get("/documents/{document_id}/content")
def get_document_content(document_id: str):
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(404, "document not found")
        try:
            path = resolve_stored_file(document.stored_filename, settings)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            path,
            media_type=document.mime_type,
            filename=document.original_filename,
            content_disposition_type="inline" if document.file_type in {".pdf", ".txt", ".md"} else "attachment",
        )


@router.delete("/documents/{document_id}")
def delete_document(document_id: str):
    with SessionLocal() as session:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(404, "document not found")
        stored_filename = document.stored_filename
        session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
        session.delete(document)
        session.commit()
    try:
        path = resolve_stored_file(stored_filename, settings)
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        logger.warning("文档数据库记录已删除，但原文件不存在：%s", stored_filename)
    except OSError:
        logger.exception("文档数据库记录已删除，但原文件删除失败：%s", stored_filename)
    return {"ok": True}


@router.get("/search")
async def search_documents(
    request: Request,
    q: str = Query(min_length=1, max_length=1000),
    limit: int = Query(default=5, ge=1, le=20),
):
    def _search():
        with SessionLocal() as session:
            return retrieve(session, request.app.state.embedding_provider, q, settings, final_limit=limit)

    results = await anyio.to_thread.run_sync(_search)
    return [
        {
            "chunk_id": item.chunk_id,
            "document_id": item.document_id,
            "filename": item.filename,
            "section": item.section,
            "content": item.content,
            "page_start": item.page_start,
            "page_end": item.page_end,
            "char_start": item.char_start,
            "char_end": item.char_end,
            "chunk_index": item.chunk_index,
            "vector_score": item.vector_score,
            "bm25_score": item.bm25_score,
            "rrf_score": item.rrf_score,
            "retrieval_rank": item.retrieval_rank,
        }
        for item in results
    ]
