"""Import user-owned local books and export portable reading formats."""
from urllib.parse import quote
from zipfile import BadZipFile
import anyio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from core.story.books import convert, as_txt, as_epub
from core.story.novel_reading import save_source
from core.story.reader import read_book
from infrastructure.config import settings
from infrastructure.database import Document, SessionLocal

router = APIRouter(prefix="/api/worldbooks", tags=["books"])


@router.post("/import")
async def import_book(files: list[UploadFile] = File(...), title: str = Form(""), preview: bool = Form(True)):
    if len(files) > 5000:
        raise HTTPException(413, "最多支持5000个章节文件")
    payload, size = [], 0
    try:
        for file in files:
            data = await file.read(max(0, settings.file_max_bytes - size) + 1)
            size += len(data)
            if size > settings.file_max_bytes:
                raise ValueError("上传文件总大小超过限制")
            payload.append((file.filename or "小说.txt", data))
        book = await anyio.to_thread.run_sync(convert, payload, settings.file_max_bytes, settings.file_max_parsed_chars)
        name = title.strip() or book["title"]
        if len(name) > 100:
            raise ValueError("书名不能超过100字")
        result = {"title": name, "chapters": [{"title": s["title"], "characters": len(s["text"])} for s in book["sections"]],
            "characters": sum(len(s["text"]) for s in book["sections"]), "ignored_files": book["ignored_files"],
            "excerpt": book["sections"][0]["text"][:800]}
        if not preview:
            text = as_txt(book["sections"])
            if len(text) > settings.file_max_parsed_chars or len(text.encode()) > settings.file_max_bytes:
                raise ValueError("转换后正文超过保存上限，未截断")
            result["document_id"] = await anyio.to_thread.run_sync(save_source, text, name)
        return result
    except (ValueError, OSError, BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        for file in files:
            await file.close()


@router.get("/{document_id}/export/{format}")
def export_book(document_id: str, format: str):
    if format not in {"txt", "epub"}:
        raise HTTPException(404, "不支持的导出格式")
    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            raise HTTPException(404, "书籍不存在")
        book = read_book(doc, settings)
    data = as_txt(book["sections"]).encode("utf-8") if format == "txt" else as_epub(book["title"], book["sections"])
    name = quote(book["title"] + "." + format, safe="")
    return Response(data, media_type="text/plain; charset=utf-8" if format == "txt" else "application/epub+zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
