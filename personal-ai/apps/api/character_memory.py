"""角色经历管理与来源可核对的异步提取。"""
import asyncio
from types import SimpleNamespace
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import anyio

from core.chat.character_memory import MemoryDraft, extract_document, fingerprint, memory_dict
from core.chat.gateway import build_provider
from infrastructure.config import settings
from infrastructure.database import CharacterMemory, CharacterExtraction, Document, DocumentChunk, SessionLocal

router = APIRouter(prefix="/api/characters", tags=["character-memory"])


def character(request, agent_id):
    profile = next((row for row in request.app.state.runtime_settings_store.snapshot()["agents"]["items"] if row["id"] == agent_id), None)
    if profile is None:
        raise HTTPException(404, "角色不存在")
    return profile


class ExtractBody(BaseModel):
    document_id: str = Field(min_length=1, max_length=32)


class SaveBody(MemoryDraft):
    status: str = "draft"


@router.get("/{agent_id}/memories")
def list_memories(agent_id: str, request: Request):
    character(request, agent_id)
    with SessionLocal() as session:
        rows = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id).order_by(CharacterMemory.created_at.desc()).all()
        jobs = session.query(CharacterExtraction).filter(CharacterExtraction.agent_id == agent_id).order_by(CharacterExtraction.created_at.desc()).limit(10).all()
        return {"memories": [memory_dict(row) for row in rows],
            "jobs": [{key: getattr(job, key) for key in ("id", "document_id", "status", "total", "processed", "rejected", "error")} for job in jobs]}


@router.post("/{agent_id}/memories", status_code=201)
async def create(agent_id: str, body: MemoryDraft, request: Request):
    character(request, agent_id)
    if not body.content.strip() or any(len(tag) > 60 for tag in body.tags):
        raise HTTPException(422, "请填写有效的记忆内容")
    provider = request.app.state.embedding_provider
    vector = None
    if provider.dimension > 0:
        try:
            vector = (await anyio.to_thread.run_sync(lambda: provider.embed_documents([body.content])))[0]
        except Exception:
            pass  # 模型暂时不可用时仍保存正文，供关键词召回。
    with SessionLocal() as session:
        digest = fingerprint(body.content)
        if session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
                CharacterMemory.fingerprint == digest, CharacterMemory.status.in_(["active", "draft"])).first():
            raise HTTPException(409, "已经有相同内容的记忆")
        row = CharacterMemory(agent_id=agent_id, status="active", source_name="用户编写",
            fingerprint=digest, embedding=vector,
            embedding_model=provider.model_name if vector is not None else None,
            embedding_dim=provider.dimension if vector is not None else None,
            **body.model_dump(exclude={"source_quote"}))
        session.add(row)
        session.commit()
        return memory_dict(row)


@router.post("/{agent_id}/extract", status_code=202)
async def extract(agent_id: str, body: ExtractBody, request: Request):
    profile = character(request, agent_id)
    state = request.app.state
    if state.character_tasks:
        raise HTTPException(409, "已有资料正在提取，请等待完成")
    if settings.llm_provider == "unconfigured":
        raise HTTPException(409, "请先在模型设置中配置用于提取的聊天模型")
    with SessionLocal() as session:
        document = session.get(Document, body.document_id)
        if document is None or document.status != "indexed":
            raise HTTPException(422, "请先上传并完成资料解析")
        if document.agent_id not in {None, agent_id}:
            raise HTTPException(409, "这份资料已属于其他角色，请使用该角色的资料")
        count = session.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).count()
        if not 1 <= count <= 300:
            raise HTTPException(422, "每次支持 1–300 个片段，请按章节拆分资料")
        try:
            provider = build_provider(SimpleNamespace(**settings.model_dump()))
        except Exception:
            raise HTTPException(422, "聊天模型初始化失败，请检查模型设置") from None
        document.agent_id = agent_id
        job = CharacterExtraction(agent_id=agent_id, document_id=document.id, total=count)
        session.add(job)
        try:
            session.commit()
        except Exception:
            await provider.close()
            raise
        job_id = job.id
    budget = max(512, settings.llm_context_window_tokens - settings.llm_max_output_tokens - 512)
    task = asyncio.create_task(extract_document(job_id, profile["name"], provider, budget))
    state.character_tasks[job_id] = task
    task.add_done_callback(lambda _: state.character_tasks.pop(job_id, None))
    return {"id": job_id}


@router.patch("/{agent_id}/memories/{memory_id}")
async def update(agent_id: str, memory_id: str, body: SaveBody, request: Request):
    character(request, agent_id)
    if body.status not in {"draft", "active", "disabled", "rejected"} or not body.content.strip() or any(len(tag) > 60 for tag in body.tags):
        raise HTTPException(422, "记忆内容或状态无效")
    with SessionLocal() as session:
        row = session.get(CharacterMemory, memory_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(404, "记忆不存在")
        if body.source_quote != row.source_quote:
            raise HTTPException(422, "来源引用不可改写，请修改记忆正文")
    provider = request.app.state.embedding_provider
    vector = None
    if body.status == "active" and provider.dimension > 0:
        try:
            vector = (await anyio.to_thread.run_sync(lambda: provider.embed_documents([body.content])))[0]
        except Exception:
            pass  # 正式文本仍可关键词检索，之后可统一重建语义索引。
    with SessionLocal() as session:
        row = session.get(CharacterMemory, memory_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(404, "记忆不存在")
        for key, value in body.model_dump(exclude={"source_quote"}).items():
            setattr(row, key, value)
        row.fingerprint = fingerprint(body.content)
        row.embedding = vector
        row.embedding_model = provider.model_name if vector is not None else None
        row.embedding_dim = provider.dimension if vector is not None else None
        session.commit()
        return memory_dict(row)


@router.delete("/{agent_id}/memories/{memory_id}")
def delete(agent_id: str, memory_id: str, request: Request):
    character(request, agent_id)
    with SessionLocal() as session:
        row = session.get(CharacterMemory, memory_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(404, "记忆不存在")
        session.delete(row)
        session.commit()
    return {"ok": True}
