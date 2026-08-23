"""聊天 SSE 与显式 Run 取消接口。"""

import re
import uuid
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.chat.agent import run_chat, sse_packet
from core.chat.gateway import build_provider
from core.chat.images import model_supports_images
from core.chat.run_control import cancel_chat_run, register_chat_run, unregister_chat_run
from infrastructure.config import settings
from infrastructure.database import AgentRun, ChatImage, Conversation, SessionLocal

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
    if not cancel_chat_run(run_id):
        raise HTTPException(404, "Run 不存在或已经结束")
    return {"ok": True, "status": "cancelling", "run_id": run_id}


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    run_id = req.run_id or uuid.uuid4().hex
    if not _valid_run_id(run_id):
        raise HTTPException(422, "run_id 格式无效")
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
    if req.execution_mode == "planned" and not settings.planner_enabled:
        raise HTTPException(409, "planner is disabled")
    if req.image_ids and req.execution_mode == "planned":
        raise HTTPException(422, "图片识别当前仅支持直接回答模式")
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
        register_chat_run(run_id, req.conversation_id)
        try:
            async for event in run_chat(
                provider,
                req.conversation_id,
                req.message,
                embedding_provider=request.app.state.embedding_provider,
                skills=request.app.state.skills,
                execution_mode=req.execution_mode,
                agent_profile=request.app.state.agent_profile,
                document_ids=req.document_ids,
                image_ids=req.image_ids,
                mcp_clients=request.app.state.mcp_clients,
                context_window_tokens=selected_context_window,
                max_output_tokens=selected_max_output,
                run_id=run_id,
                require_plan_approval=req.require_plan_approval,
            ):
                yield sse_packet(event.type, event.data)
        finally:
            unregister_chat_run(run_id)
            if owns_provider:
                await provider.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
