"""Original novels remain worldbooks; one reading task creates all requested characters."""
import asyncio
from types import SimpleNamespace

import anyio
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field, model_validator

from core.capabilities.web_search import WebSearchService, public_url
from core.chat.gateway import build_provider
from core.story.novel_reading import load_text, run_reading, save_source
from infrastructure.config import settings
from infrastructure.database import SessionLocal, NovelReading, Document

router = APIRouter(prefix="/api/novel-readings", tags=["novel-reading"])


class ReadBody(BaseModel):
    document_id: str | None = Field(default=None, max_length=32)
    search_query: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=2000)
    characters: list[str] = Field(default_factory=list, max_length=12)
    requirements: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_source(self):
        self.characters = list(dict.fromkeys(name.strip() for name in self.characters if name.strip()))
        if any(len(name) > 80 for name in self.characters):
            raise ValueError("角色名不能超过80字")
        if not self.document_id and not (self.search_query.strip() or self.url.strip()):
            raise ValueError("请选择上传的小说，或填写联网寻找的作品名")
        if self.document_id and (self.search_query or self.url):
            raise ValueError("上传与联网来源只能选择一种")
        if self.url:
            public_url(self.url)
        return self


def job_dict(row, request):
    return {"id": row.id, "document_id": row.document_id, "status": row.status, "request": row.request,
        "result": row.result, "report": {k: v for k, v in row.report.items() if k not in {"reading_state", "memory_repair_state"}}, "error": row.error,
        "running": "novel:" + row.id in request.app.state.character_tasks}


def start(job_id, request):
    state = request.app.state
    if state.character_tasks:
        raise HTTPException(409, "已有资料任务正在运行，请等待结束")
    config = SimpleNamespace(**settings.model_dump())
    config.llm_max_output_tokens = min(config.llm_max_output_tokens, 8192)
    config.llm_timeout_seconds = max(config.llm_timeout_seconds, 1800)
    provider = build_provider(config)
    if config.llm_provider in {"mock", "unconfigured"}:
        raise HTTPException(409, "请配置真实聊天模型后阅读小说")
    key = "novel:" + job_id
    task = asyncio.create_task(run_reading(job_id, provider, state.runtime_settings_store, WebSearchService(state.runtime_settings_store)))
    state.character_tasks[key] = task
    task.add_done_callback(lambda _: state.character_tasks.pop(key, None))


@router.post("/upload", status_code=201)
async def upload(request: Request, file: UploadFile = File(...)):
    # TXT/MD novels can be stored immediately; no embedding calls are required to read a book.
    from pathlib import Path
    filename = Path(file.filename or "novel.txt").name
    if Path(filename).suffix.lower() not in {".txt", ".md"}:
        raise HTTPException(415, "小说原文上传支持 TXT 和 Markdown；其他资料可用书籍的上传文件入口")
    data = await file.read(settings.file_max_bytes + 1)
    if len(data) > settings.file_max_bytes:
        raise HTTPException(413, "小说文件超过大小限制")
    from core.rag.ingestion import validate_file
    try:
        validate_file(data, filename, "text/plain" if filename.lower().endswith(".txt") else "text/markdown", settings)
        text = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeError:
                pass
        if not text or len(text) > settings.file_max_parsed_chars:
            raise ValueError("小说为空、编码无效或超过解析文字上限")
        document_id = await anyio.to_thread.run_sync(save_source, text, Path(filename).stem)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"document_id": document_id, "characters": len(text)}


@router.get("")
def list_jobs(request: Request, document_id: str | None = None):
    with SessionLocal() as session:
        query = session.query(NovelReading)
        if document_id:
            query = query.filter(NovelReading.document_id == document_id)
        return [job_dict(row, request) for row in query.order_by(NovelReading.created_at.desc()).limit(50)]


@router.post("", status_code=202)
async def create(body: ReadBody, request: Request):
    if request.app.state.character_tasks:
        raise HTTPException(409, "已有资料任务正在运行")
    if body.document_id:
        with SessionLocal() as session:
            if not session.get(Document, body.document_id):
                raise HTTPException(404, "小说不存在")
        await anyio.to_thread.run_sync(load_text, body.document_id)
    elif not body.url:
        values = request.app.state.runtime_settings_store.snapshot()["web_search"]
        if not values["enabled"] or not values["api_key"]:
            raise HTTPException(409, "请先在联网设置中开启搜索并配置密钥")
    with SessionLocal() as session:
        row = NovelReading(document_id=body.document_id, request=body.model_dump())
        session.add(row)
        session.commit()
        job_id = row.id
    try:
        start(job_id, request)
    except Exception:
        with SessionLocal() as session:
            row = session.get(NovelReading, job_id)
            row.status, row.error = "failed", "模型未能启动，请检查配置"
            session.commit()
        raise
    return {"id": job_id}


@router.post("/{job_id}/resume")
async def resume(job_id: str, request: Request):
    with SessionLocal() as session:
        row = session.get(NovelReading, job_id)
        if not row:
            raise HTTPException(404, "任务不存在")
        if row.status == "completed":
            if row.report.get("characters_checked") and row.report.get("memory_counts") and row.report.get("output_file"):
                return job_dict(row, request)
    start(job_id, request)
    return {"id": job_id}


@router.post("/{job_id}/pause")
async def pause(job_id: str, request: Request):
    task = request.app.state.character_tasks.get("novel:" + job_id)
    if not task:
        raise HTTPException(409, "任务没有在运行")
    task.cancel()
    return {"id": job_id}


@router.post("/{job_id}/check")
async def check(job_id: str, request: Request):
    if request.app.state.character_tasks:
        raise HTTPException(409, "已有资料任务正在运行")
    with SessionLocal() as session:
        row = session.get(NovelReading, job_id)
        if not row or row.status != "completed":
            raise HTTPException(409, "请先完成阅读")
        row.report = {**row.report, "characters_checked": False}
        session.commit()
    start(job_id, request)
    return {"id": job_id}
