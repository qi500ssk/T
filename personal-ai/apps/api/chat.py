"""POST /api/chat：SSE 流式聊天（Agent Event Protocol）。"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.agent import run_chat, sse_packet
from infrastructure.database import Conversation, SessionLocal

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    with SessionLocal() as session:
        if session.get(Conversation, req.conversation_id) is None:
            raise HTTPException(404, "conversation not found")

    async def event_stream():
        async for event in run_chat(
            request.app.state.provider,
            req.conversation_id,
            req.message,
            embedding_provider=request.app.state.embedding_provider,
        ):
            yield sse_packet(event.type, event.data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
