"""POST /api/chat：SSE 流式聊天（Agent Event Protocol）。"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.chat.agent import run_chat, sse_packet
from infrastructure.config import settings
from infrastructure.database import AgentRun, Conversation, SessionLocal

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    execution_mode: Literal["direct", "planned"] = "direct"


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
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

    async def event_stream():
        async for event in run_chat(
            request.app.state.provider,
            req.conversation_id,
            req.message,
            embedding_provider=request.app.state.embedding_provider,
            skills=request.app.state.skills,
            execution_mode=req.execution_mode,
        ):
            yield sse_packet(event.type, event.data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
