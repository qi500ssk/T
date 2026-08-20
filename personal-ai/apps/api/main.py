"""FastAPI 应用装配：会话 / 记忆 CRUD + Chat SSE（P0）。"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from apps.api.chat import router as chat_router
from apps.api.documents import router as documents_router
from core.embedding import build_embedding_provider
from core.gateway import build_provider
from core.memory import contains_sensitive_information, normalize_memory_key
from core.permissions import reject_all_approvals, resolve_approval
from core.skills import load_skills
from core.tools import list_tools as registered_tools
from infrastructure.config import settings
from infrastructure.database import Conversation, Memory, Message, SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    Path(settings.sandbox_dir).mkdir(parents=True, exist_ok=True)
    app.state.provider = build_provider(settings)
    app.state.embedding_provider = build_embedding_provider(settings)
    app.state.skills = load_skills()
    try:
        yield
    finally:
        reject_all_approvals()
        await app.state.provider.close()
        app.state.embedding_provider.close()


app = FastAPI(title="Personal AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat_router)
app.include_router(documents_router)


class ApprovalRequest(BaseModel):
    approval_id: str = Field(min_length=32, max_length=32)
    approved: bool


@app.post("/api/approval")
def submit_approval(body: ApprovalRequest):
    if not resolve_approval(body.approval_id, body.approved):
        raise HTTPException(404, "approval not found or expired")
    return {"ok": True}


@app.get("/api/tools")
def get_tools():
    return registered_tools()


def _conv_dict(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "summary": c.summary,
    }


def _message_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "citations": m.citations or [],
        "created_at": m.created_at.isoformat(),
    }


def _memory_dict(m: Memory) -> dict:
    return {
        "id": m.id,
        "kind": m.kind,
        "content": m.content,
        "importance": m.importance,
        "confidence": m.confidence,
        "is_active": m.is_active,
        "source_conversation_id": m.source_conversation_id,
        "created_at": m.created_at.isoformat(),
        "updated_at": (m.updated_at or m.created_at).isoformat(),
    }


# ---------- Conversations ----------

class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationRename(BaseModel):
    title: str


@app.get("/api/conversations")
def list_conversations():
    with SessionLocal() as session:
        rows = session.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        return [_conv_dict(c) for c in rows]


@app.post("/api/conversations")
def create_conversation(body: ConversationCreate):
    with SessionLocal() as session:
        conv = Conversation(title=body.title)
        session.add(conv)
        session.commit()
        return _conv_dict(conv)


@app.patch("/api/conversations/{conv_id}")
def rename_conversation(conv_id: str, body: ConversationRename):
    with SessionLocal() as session:
        conv = session.get(Conversation, conv_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        conv.title = body.title
        session.commit()
        return _conv_dict(conv)


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    with SessionLocal() as session:
        conv = session.get(Conversation, conv_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        session.query(Message).filter(Message.conversation_id == conv_id).delete()
        session.delete(conv)
        session.commit()
        return {"ok": True}


@app.get("/api/conversations/{conv_id}/messages")
def list_messages(conv_id: str):
    with SessionLocal() as session:
        if session.get(Conversation, conv_id) is None:
            raise HTTPException(404, "conversation not found")
        rows = (
            session.query(Message)
            .filter(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [_message_dict(m) for m in rows]


# ---------- Memories（P0：手动管理，自动提取在 P1） ----------

class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["episodic", "semantic", "profile"] = "semantic"
    importance: int = Field(default=3, ge=1, le=5)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: Literal["episodic", "semantic", "profile"] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None


@app.get("/api/memories")
def list_memories():
    with SessionLocal() as session:
        rows = session.query(Memory).order_by(Memory.created_at.desc()).all()
        return [_memory_dict(m) for m in rows]


@app.post("/api/memories")
def create_memory(body: MemoryCreate):
    content = body.content.strip()
    if contains_sensitive_information(content):
        raise HTTPException(422, "记忆内容包含敏感信息，已拒绝保存")
    with SessionLocal() as session:
        mem = Memory(
            kind=body.kind,
            content=content,
            normalized_key=normalize_memory_key("", content),
            importance=body.importance,
            confidence=1.0,
        )
        session.add(mem)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "相同记忆已存在") from None
        return _memory_dict(mem)


@app.patch("/api/memories/{mem_id}")
def update_memory(mem_id: str, body: MemoryUpdate):
    with SessionLocal() as session:
        mem = session.get(Memory, mem_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        changes = body.model_dump(exclude_unset=True)
        if "content" in changes and contains_sensitive_information(changes["content"]):
            raise HTTPException(422, "记忆内容包含敏感信息，已拒绝保存")
        for field, value in changes.items():
            setattr(mem, field, value.strip() if field == "content" else value)
        if "content" in changes:
            mem.normalized_key = normalize_memory_key("", changes["content"])
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "相同记忆已存在") from None
        return _memory_dict(mem)


@app.post("/api/memories/{mem_id}/disable")
def disable_memory(mem_id: str):
    with SessionLocal() as session:
        mem = session.get(Memory, mem_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        mem.is_active = False
        session.commit()
        return _memory_dict(mem)


@app.delete("/api/memories/{mem_id}")
def delete_memory(mem_id: str):
    with SessionLocal() as session:
        mem = session.get(Memory, mem_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        session.delete(mem)
        session.commit()
        return {"ok": True}
