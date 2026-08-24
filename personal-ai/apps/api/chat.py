"""聊天 SSE 与显式 Run 取消接口。"""

import re
import uuid
from types import SimpleNamespace
from typing import Literal

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.chat.agent import run_chat, sse_packet
from core.chat.checkpoints import interrupt_run
from core.chat.continuation import is_continuation_request
from core.chat.gateway import build_provider
from core.chat.images import model_supports_images
from core.chat.run_control import cancel_chat_run, register_chat_run, unregister_chat_run
from infrastructure.config import settings
from infrastructure.database import AgentRun, ChatImage, Checkpoint, Conversation, Message, SessionLocal

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    run_id: str | None = Field(default=None, min_length=32, max_length=32)
    conversation_id: str
    message: str
    execution_mode: Literal["direct", "planned"] = "direct"
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    model_id: str | None = Field(default=None, max_length=100)
    image_ids: list[str] = Field(default_factory=list, max_length=10)
    require_plan_approval: bool = False


def _valid_run_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", value))


@router.post("/chat/{run_id}/cancel")
async def cancel_chat(run_id: str):
    if not _valid_run_id(run_id):
        raise HTTPException(422, "run_id 格式无效")
    if cancel_chat_run(run_id):
        return {"ok": True, "status": "cancelling", "run_id": run_id}
    # 页面刷新后进程内注册表可能已经丢失，但数据库仍可能留着 running。
    # 这时仍允许用户停止，避免会话永久被 409 锁住。
    with SessionLocal() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status != "running":
            raise HTTPException(404, "Run 不存在或已经结束")
    await anyio.to_thread.run_sync(
        interrupt_run, run_id, "用户已停止失联的运行；发送“继续”可从中断位置接续"
    )
    return {"ok": True, "status": "interrupted", "run_id": run_id}


@router.post("/chat/{run_id}/resume")
async def resume_chat(run_id: str, request: Request):
    if not _valid_run_id(run_id):
        raise HTTPException(422, "run_id 格式无效")
    with SessionLocal() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.status != "interrupted" or run.execution_mode != "planned":
            raise HTTPException(409, "只有 interrupted 的规划 Run 可以恢复")
        message = session.get(Message, run.input_message_id) if run.input_message_id else None
        if message is None:
            message = (
                session.query(Message)
                .filter(Message.conversation_id == run.conversation_id, Message.role == "user")
                .order_by(Message.created_at.desc())
                .first()
            )
        if message is None:
            raise HTTPException(409, "找不到原始用户消息")
        conversation_id = run.conversation_id
        original_message = message.content

    async def event_stream():
        register_chat_run(run_id, conversation_id)
        try:
            async for event in run_chat(
                request.app.state.provider,
                conversation_id,
                original_message,
                embedding_provider=request.app.state.embedding_provider,
                skills=request.app.state.skills,
                execution_mode="planned",
                agent_profile=request.app.state.agent_profile,
                mcp_clients=request.app.state.mcp_clients,
                context_window_tokens=settings.llm_context_window_tokens,
                max_output_tokens=settings.llm_max_output_tokens,
                run_id=run_id,
                resume=True,
            ):
                yield sse_packet(event.type, event.data)
        finally:
            unregister_chat_run(run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    run_id = req.run_id or uuid.uuid4().hex
    if not _valid_run_id(run_id):
        raise HTTPException(422, "run_id 格式无效")
    resume_run_id: str | None = None
    with SessionLocal() as session:
        if session.get(Conversation, req.conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        if (
            session.query(AgentRun)
            .filter(
                AgentRun.conversation_id == req.conversation_id,
                AgentRun.status == "running",
            )
            .first()
        ):
            raise HTTPException(409, "conversation already has a running agent run")
        if (
            is_continuation_request(req.message)
            and not req.document_ids
            and not req.image_ids
        ):
            latest_run = (
                session.query(AgentRun)
                .filter(AgentRun.conversation_id == req.conversation_id)
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .first()
            )
            if (
                latest_run
                and latest_run.status == "interrupted"
                and latest_run.execution_mode == "planned"
                and session.query(Checkpoint.id)
                .filter(Checkpoint.run_id == latest_run.id)
                .first()
            ):
                resume_run_id = latest_run.id
    effective_run_id = resume_run_id or run_id
    effective_execution_mode = "planned" if resume_run_id else req.execution_mode
    # 新聊天的规划模式只生成 Markdown 文档，不依赖步骤 Planner。
    # 只有恢复旧的可执行计划才需要 Planner 开关。
    if resume_run_id and not settings.planner_enabled:
        raise HTTPException(409, "planner is disabled")
    if len(req.image_ids) > settings.chat_image_max_count:
        raise HTTPException(422, f"一次最多发送 {settings.chat_image_max_count} 张图片")

    provider = request.app.state.provider
    owns_provider = False
    store = request.app.state.runtime_settings_store
    models = store.snapshot()["models"]
    environment_error = getattr(request.app.state, "environment_model_error", None)
    environment_locked = bool(getattr(request.app.state, "environment_model_locked", False))
    selected_model = settings.llm_model if environment_locked else ""
    selected_context_window = settings.llm_context_window_tokens
    selected_max_output = settings.llm_max_output_tokens
    if environment_error:
        raise HTTPException(409, f".env 模型配置不完整：{environment_error}")
    if not environment_locked and not models["items"]:
        raise HTTPException(409, "尚未配置可用模型，请先前往模型设置")
    if not environment_locked:
        requested_model_id = req.model_id or models["default_model_id"]
        profile = next((item for item in models["items"] if item["id"] == requested_model_id), None)
        if profile is None:
            raise HTTPException(404, "所选模型配置不存在，请重新选择")
        selected_model = str(profile.get("llm_model") or profile.get("model") or "")
        selected_context_window = int(profile["llm_context_window_tokens"])
        selected_max_output = int(profile["llm_max_output_tokens"])
        if requested_model_id != models["default_model_id"]:
            provider = build_provider(SimpleNamespace(**profile))
            owns_provider = True
    if req.image_ids:
        if len(set(req.image_ids)) != len(req.image_ids):
            raise HTTPException(422, "图片列表包含重复项")
        if not model_supports_images(selected_model):
            raise HTTPException(422, f"当前模型 {selected_model or '未配置'} 不支持图片，请选择 qwen3.8-max")
        with SessionLocal() as session:
            images = session.query(ChatImage).filter(ChatImage.id.in_(req.image_ids)).all()
            if len(images) != len(req.image_ids) or any(image.message_id is not None for image in images):
                raise HTTPException(422, "图片不存在、已失效或已经发送，请重新上传")

    async def event_stream():
        register_chat_run(effective_run_id, req.conversation_id)
        try:
            async for event in run_chat(
                provider,
                req.conversation_id,
                req.message,
                embedding_provider=request.app.state.embedding_provider,
                skills=request.app.state.skills,
                execution_mode=effective_execution_mode,
                agent_profile=request.app.state.agent_profile,
                document_ids=req.document_ids,
                image_ids=req.image_ids,
                mcp_clients=request.app.state.mcp_clients,
                context_window_tokens=selected_context_window,
                max_output_tokens=selected_max_output,
                run_id=effective_run_id,
                require_plan_approval=req.require_plan_approval,
                resume=resume_run_id is not None,
            ):
                yield sse_packet(event.type, event.data)
        finally:
            unregister_chat_run(effective_run_id)
            if owns_provider:
                await provider.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
