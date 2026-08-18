"""会话摘要：按消息阈值增量压缩旧对话，同时保留最近消息原文。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from infrastructure.database import Conversation, Message, SessionLocal


_PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "memory" / "summary.md"


async def update_conversation_summary(
    provider,
    conversation_id: str,
    trigger_messages: int,
    keep_recent_messages: int,
) -> bool:
    with SessionLocal() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            return False
        messages = (
            session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        previous_count = conversation.summary_message_count
        unsummarized = len(messages) - previous_count
        if unsummarized < trigger_messages:
            return False
        target_count = max(previous_count, len(messages) - keep_recent_messages)
        selected = messages[previous_count:target_count]
        if not selected:
            return False
        previous_summary = conversation.summary or ""

    payload = json.dumps(
        {
            "previous_summary": previous_summary,
            "new_messages": [{"role": message.role, "content": message.content} for message in selected],
        },
        ensure_ascii=False,
    )
    summary = (
        await provider.complete(
            [
                {"role": "system", "content": _PROMPT_FILE.read_text(encoding="utf-8")},
                {"role": "user", "content": payload},
            ],
            temperature=0.0,
        )
    ).strip()
    if not summary:
        return False

    with SessionLocal() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.summary_message_count != previous_count:
            return False
        conversation.summary = summary[:8000]
        conversation.summary_message_count = target_count
        conversation.summary_updated_at = datetime.now(timezone.utc)
        session.commit()
    return True
