"""FastAPI 应用装配：会话 / 记忆 CRUD + Chat SSE（P0）。"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from apps.api.chat import router as chat_router
from apps.api.activities import router as activities_router
from apps.api.documents import router as documents_router
from apps.api.plans import router as plans_router
from apps.api.skills import refresh_skill_runtime, router as skills_router
from apps.api.mcp_servers import router as mcp_servers_router
from apps.api.plugins import router as plugins_router
from apps.api.artifacts import router as artifacts_router
from apps.api.settings import router as settings_router
from apps.api.projects import router as projects_router
from apps.api.images import image_dict, router as images_router
from core.chat.images import resolve_image
from core.chat.context import IMAGE_TOKEN_ESTIMATE, estimate_tokens
from core.automation.activity import activity_worker, recover_interrupted_activities
from core.rag.embedding import build_embedding_provider
from core.chat.character import load_character
from core.chat.gateway import build_provider
from core.chat.memory import (
    contains_sensitive_information,
    memory_history,
    normalize_memory_key,
    revise_memory,
)
from core.chat.checkpoints import recover_interrupted_runs
from core.capabilities.mcp_manager import McpManager
from core.capabilities.plugins import PluginManager
from core.capabilities.skill_registry import build_default_skill_registry
from core.execution.permissions import reject_all_approvals, resolve_approval
from core.execution.tools import list_tools as registered_tools
from core.settings.runtime import (
    RuntimeSettingsStore,
    apply_runtime_config,
    capture_runtime_config,
)
from infrastructure.config import settings
from infrastructure.database import (
    Activity,
    AgentRun,
    Conversation,
    Memory,
    Message,
    ChatImage,
    Plan,
    PlanStep,
    Project,
    SessionLocal,
    ToolRun,
    init_db,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    reject_all_approvals()
    recover_interrupted_runs()
    original_runtime_config = capture_runtime_config(settings)
    app.state.runtime_settings_store = RuntimeSettingsStore(
        settings.runtime_settings_file,
        settings,
        load_character(settings.character_file),
    )
    runtime_snapshot = app.state.runtime_settings_store.snapshot()
    app.state.environment_model_locked = settings.environment_model_configured
    app.state.environment_model_error = settings.environment_model_error
    if app.state.environment_model_locked:
        # 环境模型具有最高优先级；仍应用工作区等其他本地运行时设置。
        runtime_snapshot["model"] = original_runtime_config["model"]
    elif app.state.environment_model_error:
        # 显式环境配置不完整时拒绝偷偷回退到前端模型。
        runtime_snapshot["model"] = {
            "llm_provider": "unconfigured",
            "llm_base_url": "",
            "llm_api_key": "",
            "llm_model": "",
            "llm_timeout_seconds": 60.0,
            "llm_context_window_tokens": settings.llm_context_window_tokens,
            "llm_max_output_tokens": settings.llm_max_output_tokens,
        }
    apply_runtime_config(settings, runtime_snapshot)
    app.state.agent_profile = runtime_snapshot["agent"]
    app.state.runtime_settings_lock = asyncio.Lock()
    Path(settings.sandbox_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.coding_workspace_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.chat_image_storage_dir).mkdir(parents=True, exist_ok=True)
    app.state.provider = build_provider(settings)
    app.state.embedding_provider = build_embedding_provider(settings)
    app.state.mcp_manager = McpManager(
        settings.mcp_config_file,
        cwd=Path.cwd(),
        runtime_enabled=settings.mcp_enabled,
    )
    await app.state.mcp_manager.startup()
    app.state.skill_registry = build_default_skill_registry()
    app.state.plugin_manager = PluginManager(
        app.state.skill_registry,
        app.state.mcp_manager,
        root=settings.plugins_dir,
        trash_root=settings.plugin_trash_dir,
        settings_provider=lambda plugin_id: app.state.runtime_settings_store.snapshot()
        ["plugin_settings"].get(plugin_id, {}),
    )
    await app.state.plugin_manager.refresh()
    app.state.mcp_clients = app.state.mcp_manager.clients
    app.state.skills = []
    refresh_skill_runtime(app)
    app.state.activity_stop_event = None
    app.state.activity_task = None
    if settings.activity_enabled:
        recover_interrupted_activities()
        app.state.activity_stop_event = asyncio.Event()
        app.state.activity_task = asyncio.create_task(
            activity_worker(
                app.state.activity_stop_event,
                app.state.provider,
                app.state.embedding_provider,
                app.state.skills,
                app.state.agent_profile,
                app.state.mcp_manager,
            ),
            name="activity-worker",
        )
    try:
        yield
    finally:
        if app.state.activity_task is not None:
            app.state.activity_stop_event.set()
            app.state.activity_task.cancel()
            try:
                await app.state.activity_task
            except asyncio.CancelledError:
                pass
        reject_all_approvals()
        await app.state.mcp_manager.shutdown()
        await app.state.provider.close()
        app.state.embedding_provider.close()
        apply_runtime_config(settings, original_runtime_config)


app = FastAPI(title="Personal AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(activities_router)
app.include_router(plans_router)
app.include_router(skills_router)
app.include_router(mcp_servers_router)
app.include_router(plugins_router)
app.include_router(artifacts_router)
app.include_router(settings_router)
app.include_router(projects_router)
app.include_router(images_router)


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
        "project_id": c.project_id,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "summary": c.summary,
    }


def _message_dict(m: Message, images: list[ChatImage] | None = None) -> dict:
    message_images = images or []
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "citations": m.citations or [],
        "run_id": m.run_id,
        "status": m.status,
        "created_at": m.created_at.isoformat(),
        "images": [image_dict(image) for image in message_images],
        "token_estimate": (
            estimate_tokens(m.content) + len(message_images) * IMAGE_TOKEN_ESTIMATE
            if m.status == "completed"
            else 0
        ),
    }


def _memory_dict(m: Memory) -> dict:
    return {
        "id": m.id,
        "kind": m.kind,
        "content": m.content,
        "importance": m.importance,
        "confidence": m.confidence,
        "is_active": m.is_active,
        "scope_type": m.scope_type,
        "scope_key": m.scope_key,
        "status": m.status,
        "supersedes_id": m.supersedes_id,
        "usage_count": m.usage_count,
        "last_used_at": m.last_used_at.isoformat() if m.last_used_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "source_conversation_id": m.source_conversation_id,
        "created_at": m.created_at.isoformat(),
        "updated_at": (m.updated_at or m.created_at).isoformat(),
    }


# ---------- Conversations ----------

class ConversationCreate(BaseModel):
    title: str = "新对话"
    project_id: str | None = None


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
        if body.project_id is not None and session.get(Project, body.project_id) is None:
            raise HTTPException(404, "project not found")
        conv = Conversation(title=body.title, project_id=body.project_id)
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
        if session.query(Activity).filter(Activity.conversation_id == conv_id).first():
            raise HTTPException(409, "请先删除引用此会话的活动")
        runs = session.query(AgentRun).filter(AgentRun.conversation_id == conv_id)
        if runs.filter(AgentRun.status == "running").first():
            raise HTTPException(409, "运行中的会话不能删除")
        run_ids = [row.id for row in runs.all()]
        plan_ids = [
            row.id for row in session.query(Plan).filter(Plan.conversation_id == conv_id).all()
        ]
        if plan_ids:
            session.query(PlanStep).filter(PlanStep.plan_id.in_(plan_ids)).delete(
                synchronize_session=False
            )
            session.query(Plan).filter(Plan.id.in_(plan_ids)).delete(synchronize_session=False)
        if run_ids:
            session.query(ToolRun).filter(ToolRun.run_id.in_(run_ids)).delete(
                synchronize_session=False
            )
            session.query(AgentRun).filter(AgentRun.id.in_(run_ids)).delete(
                synchronize_session=False
            )
        message_ids = [row.id for row in session.query(Message.id).filter(Message.conversation_id == conv_id)]
        image_rows = (
            session.query(ChatImage).filter(ChatImage.message_id.in_(message_ids)).all()
            if message_ids else []
        )
        stored_images = [row.stored_filename for row in image_rows]
        if message_ids:
            session.query(ChatImage).filter(ChatImage.message_id.in_(message_ids)).delete(
                synchronize_session=False
            )
        session.query(Message).filter(Message.conversation_id == conv_id).delete()
        session.delete(conv)
        session.commit()
        for stored_filename in stored_images:
            try:
                resolve_image(stored_filename).unlink(missing_ok=True)
            except FileNotFoundError:
                pass
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
        message_ids = [row.id for row in rows]
        images = (
            session.query(ChatImage)
            .filter(ChatImage.message_id.in_(message_ids))
            .order_by(ChatImage.created_at.asc())
            .all()
            if message_ids else []
        )
        images_by_message: dict[str, list[ChatImage]] = {}
        for image in images:
            if image.message_id:
                images_by_message.setdefault(image.message_id, []).append(image)
        return [_message_dict(m, images_by_message.get(m.id, [])) for m in rows]


# ---------- Memories（P0：手动管理，自动提取在 P1） ----------

class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["episodic", "semantic", "profile"] = "semantic"
    importance: int = Field(default=3, ge=1, le=5)
    scope_type: Literal["global", "project", "conversation"] = "global"
    scope_key: str | None = Field(default=None, min_length=1, max_length=64)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: Literal["episodic", "semantic", "profile"] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None
    scope_type: Literal["global", "project", "conversation"] | None = None
    scope_key: str | None = Field(default=None, min_length=1, max_length=64)


@app.get("/api/memories")
def list_memories(
    scope_type: Literal["global", "project", "conversation"] | None = None,
    scope_key: str | None = None,
    kind: Literal["episodic", "semantic", "profile"] | None = None,
    status: Literal["active", "superseded", "expired", "all"] = "active",
):
    with SessionLocal() as session:
        query = session.query(Memory)
        if scope_type:
            query = query.filter(Memory.scope_type == scope_type)
        if scope_key:
            query = query.filter(Memory.scope_key == scope_key)
        if kind:
            query = query.filter(Memory.kind == kind)
        if status != "all":
            query = query.filter(Memory.status == status)
        rows = query.order_by(Memory.updated_at.desc(), Memory.created_at.desc()).all()
        return [_memory_dict(m) for m in rows]


@app.post("/api/memories")
def create_memory(body: MemoryCreate, request: Request):
    content = body.content.strip()
    if contains_sensitive_information(content):
        raise HTTPException(422, "记忆内容包含敏感信息，已拒绝保存")
    if body.scope_type in {"project", "conversation"} and not body.scope_key:
        raise HTTPException(422, f"{body.scope_type} 作用域必须提供 scope_key")
    provider = request.app.state.embedding_provider
    with SessionLocal() as session:
        if body.scope_type == "project" and session.get(Project, body.scope_key) is None:
            raise HTTPException(404, "project not found")
        if body.scope_type == "conversation" and session.get(Conversation, body.scope_key) is None:
            raise HTTPException(404, "conversation not found")
        embedding = provider.embed_documents([content])[0]
        mem = Memory(
            kind=body.kind,
            content=content,
            normalized_key=normalize_memory_key("", content),
            importance=body.importance,
            confidence=1.0,
            scope_type=body.scope_type,
            scope_key=body.scope_key or "global",
            content_hash=sha256(content.encode("utf-8")).hexdigest(),
            embedding=embedding,
            embedding_model=provider.model_name,
            embedding_dim=provider.dimension,
            embedded_at=datetime.now(timezone.utc),
            embedding_version=provider.model_name,
        )
        session.add(mem)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "相同记忆已存在") from None
        return _memory_dict(mem)


@app.patch("/api/memories/{mem_id}")
def update_memory(mem_id: str, body: MemoryUpdate, request: Request):
    with SessionLocal() as session:
        mem = session.get(Memory, mem_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        changes = body.model_dump(exclude_unset=True)
        next_scope_type = changes.get("scope_type", mem.scope_type)
        next_scope_key = changes.get("scope_key")
        if next_scope_type == "global":
            next_scope_key = "global"
        elif next_scope_key is None:
            next_scope_key = mem.scope_key if next_scope_type == mem.scope_type else None
        if next_scope_type == "project":
            if not next_scope_key:
                raise HTTPException(422, "project 作用域必须提供 scope_key")
            if session.get(Project, next_scope_key) is None:
                raise HTTPException(404, "project not found")
        if next_scope_type == "conversation":
            if not next_scope_key:
                raise HTTPException(422, "conversation 作用域必须提供 scope_key")
            if session.get(Conversation, next_scope_key) is None:
                raise HTTPException(404, "conversation not found")
        try:
            updated = revise_memory(
                session,
                mem,
                content=changes.get("content"),
                kind=changes.get("kind"),
                importance=changes.get("importance"),
                is_active=changes.get("is_active"),
                scope_type=next_scope_type,
                scope_key=next_scope_key,
                embedding_provider=request.app.state.embedding_provider,
            )
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "相同记忆已存在") from None
        except ValueError as exc:
            session.rollback()
            raise HTTPException(422, str(exc)) from None
        return _memory_dict(updated)


@app.get("/api/memories/{mem_id}/history")
def get_memory_history(mem_id: str):
    with SessionLocal() as session:
        mem = session.get(Memory, mem_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        return [_memory_dict(row) for row in memory_history(session, mem)]


@app.post("/api/memories/{mem_id}/expire")
def expire_memory(mem_id: str):
    with SessionLocal() as session:
        mem = session.get(Memory, mem_id)
        if mem is None:
            raise HTTPException(404, "memory not found")
        if mem.status != "active":
            raise HTTPException(409, "记忆已经失效")
        mem.status = "expired"
        mem.expires_at = datetime.now(timezone.utc)
        session.commit()
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
