"""聊天域 Context Engine：按预算组装记忆、RAG、摘要和最近对话。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from core.chat.memory import mark_memories_used, retrieve_memories
from core.rag.retrieval import retrieve, should_retrieve_knowledge
from infrastructure.config import settings
from infrastructure.database import ChatImage, Conversation, Message
from core.chat.images import image_data_url


logger = logging.getLogger(__name__)

IMAGE_TOKEN_ESTIMATE = 1024


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文 1 字约 1 token，其余按 4 字符约 1 token。"""
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    return cjk + (len(text) - cjk) // 4 + 1


def _truncate_to_budget(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    low, high, best = 0, len(text), 0
    while low <= high:
        middle = (low + high) // 2
        if estimate_tokens(text[:middle]) <= token_budget:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return text[:best].rstrip()


def _content_token_estimate(content: str | list[dict]) -> int:
    if isinstance(content, str):
        return estimate_tokens(content)
    text_cost = sum(
        estimate_tokens(str(item.get("text") or ""))
        for item in content
        if item.get("type") == "text"
    )
    image_cost = sum(IMAGE_TOKEN_ESTIMATE for item in content if item.get("type") == "image_url")
    return text_cost + image_cost


def _multimodal_content(text: str, images: list[ChatImage]) -> str | list[dict]:
    if not images:
        return text
    content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": image_data_url(image.stored_filename, image.mime_type)},
        }
        for image in images
    ]
    content.append({"type": "text", "text": text})
    return content


@dataclass
class Context:
    system: str
    messages: list[dict] = field(default_factory=list)
    token_estimate: int = 0
    max_tokens: int = 0
    token_breakdown: dict[str, int] = field(default_factory=dict)
    conversation_token_estimate: int = 0
    memory_ids: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    memory_candidate_count: int = 0
    memory_exclusions: list[dict] = field(default_factory=list)
    knowledge_candidate_count: int = 0
    knowledge_exclusions: list[dict] = field(default_factory=list)


def build_context(
    session: Session,
    system_prompt: str,
    conversation_id: str,
    message: str,
    max_tokens: int,
    recent_count: int,
    user_id: str = "default",
    memory_limit: int = 5,
    exclude_message_id: str | None = None,
    embedding_provider=None,
    rag_settings=None,
    system_addendum: str = "",
    document_ids: list[str] | None = None,
    knowledge_intent: bool | None = None,
    retrieval_query: str | None = None,
) -> Context:
    """按 Memory → RAG → Summary → Recent 的优先级组装且不超过总预算。"""
    config = rag_settings or settings
    query_text = retrieval_query or message
    conversation = session.get(Conversation, conversation_id)
    project_id = conversation.project_id if conversation else None
    conversation_rows = (
        session.query(Message.id, Message.content)
        .filter(
            Message.conversation_id == conversation_id,
            Message.status == "completed",
        )
        .all()
    )
    conversation_message_ids = [row.id for row in conversation_rows]
    conversation_image_count = (
        session.query(ChatImage)
        .filter(ChatImage.message_id.in_(conversation_message_ids))
        .count()
        if conversation_message_ids
        else 0
    )
    conversation_token_estimate = sum(
        estimate_tokens(row.content) for row in conversation_rows
    ) + conversation_image_count * IMAGE_TOKEN_ESTIMATE
    current_images = (
        session.query(ChatImage)
        .filter(ChatImage.message_id == exclude_message_id)
        .order_by(ChatImage.created_at.asc())
        .all()
        if exclude_message_id else []
    )
    image_query_cost = len(current_images) * IMAGE_TOKEN_ESTIMATE
    context_message = _truncate_to_budget(message, max(0, max_tokens - image_query_cost))
    query_cost = estimate_tokens(context_message) + image_query_cost
    system_budget = max(0, max_tokens - query_cost)
    combined_system = system_prompt
    if system_addendum:
        combined_system += "\n\n" + system_addendum
    base_system = _truncate_to_budget(combined_system, system_budget)
    system_parts = [base_system] if base_system else []
    memory_section = ""
    knowledge_section = ""
    summary_section = ""
    memory_ids: list[str] = []
    sources: list[dict] = []

    def effective_system(parts: list[str] | None = None) -> str:
        return "\n\n".join(parts if parts is not None else system_parts)

    def total_cost(parts: list[str] | None = None, messages: list[dict] | None = None) -> int:
        text = effective_system(parts)
        text_cost = estimate_tokens(text) if text else 0
        return text_cost + sum(_content_token_estimate(item["content"]) for item in (messages or [])) + query_cost

    memories = (
        retrieve_memories(
            session,
            user_id,
            query_text,
            max(memory_limit * 3, memory_limit),
            embedding_provider=embedding_provider,
            min_vector_similarity=config.rag_min_vector_similarity,
            conversation_id=conversation_id,
            project_id=project_id,
        )
        if memory_limit
        else []
    )
    memory_lines: list[str] = []
    memory_exclusions: list[dict] = []
    for item in memories:
        if len(memory_lines) >= memory_limit:
            memory_exclusions.append({"id": item.id, "reason": "recall_limit"})
            continue
        candidate_lines = [*memory_lines, f"- {item.content}"]
        section = "[相关用户记忆]\n" + "\n".join(candidate_lines)
        if estimate_tokens(section) > config.memory_tokens_budget:
            memory_exclusions.append({"id": item.id, "reason": "memory_token_budget"})
            continue
        if total_cost([*system_parts, section]) > max_tokens:
            memory_exclusions.append({"id": item.id, "reason": "context_budget"})
            continue
        memory_lines = candidate_lines
        memory_ids.append(item.id)
    if memory_lines:
        memory_section = "[相关用户记忆]\n" + "\n".join(memory_lines)
        system_parts.append(memory_section)
    if memory_ids:
        # 只有真正装入上下文的记忆计一次使用；反馈失败不影响上下文装配。
        try:
            mark_memories_used(session, memory_ids)
        except Exception:
            session.rollback()
            logger.exception("记忆使用反馈写入失败")

    should_retrieve = bool(document_ids) or (
        knowledge_intent
        if knowledge_intent is not None
        else (not config.rag_query_gate_enabled or should_retrieve_knowledge(query_text))
    )
    knowledge_candidate_count = 0
    knowledge_exclusions: list[dict] = []
    if embedding_provider is not None and config.rag_enabled and should_retrieve:
        results = retrieve(
            session,
            embedding_provider,
            query_text,
            config,
            user_id,
            final_limit=max(config.rag_final_top_k * 3, config.rag_final_top_k),
            document_ids=document_ids,
        )
        knowledge_candidate_count = len(results)
        rag_prompt = Path(config.rag_context_prompt_file).read_text(encoding="utf-8").strip()
        source_blocks: list[str] = []
        for result in results:
            if len(sources) >= config.rag_final_top_k:
                knowledge_exclusions.append(
                    {"id": result.chunk_id, "reason": "recall_limit"}
                )
                continue
            citation_id = f"c{len(sources) + 1}"
            block = (
                f'<source citation_id="{citation_id}" file="{escape(result.filename, quote=True)}" '
                f'section="{escape(result.section, quote=True)}">'
                f"{escape(result.content, quote=True)}</source>"
            )
            candidate_blocks = [*source_blocks, block]
            section = rag_prompt + "\n\n" + "\n\n".join(candidate_blocks)
            if estimate_tokens(section) > config.rag_tokens_budget:
                knowledge_exclusions.append(
                    {"id": result.chunk_id, "reason": "rag_token_budget"}
                )
                continue
            if total_cost([*system_parts, section]) > max_tokens:
                knowledge_exclusions.append(
                    {"id": result.chunk_id, "reason": "context_budget"}
                )
                continue
            source_blocks = candidate_blocks
            sources.append(
                {
                    "citation_id": citation_id,
                    "document_id": result.document_id,
                    "chunk_id": result.chunk_id,
                    "filename": result.filename,
                    "section": result.section,
                    "page_start": result.page_start,
                    "page_end": result.page_end,
                    "char_start": result.char_start,
                    "char_end": result.char_end,
                    "chunk_index": result.chunk_index,
                    "excerpt": result.content,
                }
            )
        if source_blocks:
            knowledge_section = rag_prompt + "\n\n" + "\n\n".join(source_blocks)
            system_parts.append(knowledge_section)

    if conversation and conversation.summary:
        header = "[会话摘要]\n"
        remaining = max_tokens - total_cost()
        content_budget = min(
            config.summary_tokens_budget - estimate_tokens(header),
            remaining - estimate_tokens(header),
        )
        summary = _truncate_to_budget(conversation.summary, content_budget)
        if summary:
            section = header + summary
            if total_cost([*system_parts, section]) <= max_tokens:
                summary_section = section
                system_parts.append(section)

    query = session.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.status == "completed",
    )
    if exclude_message_id:
        query = query.filter(Message.id != exclude_message_id)
    history_count = query.count()
    summarized_count = conversation.summary_message_count if conversation else 0
    unsummarized_count = max(0, history_count - summarized_count)
    recent = (
        query.order_by(Message.created_at.desc())
        .limit(min(recent_count, unsummarized_count))
        .all()
    )
    recent_ids = [row.id for row in recent]
    recent_image_rows = (
        session.query(ChatImage)
        .filter(ChatImage.message_id.in_(recent_ids))
        .order_by(ChatImage.created_at.asc())
        .all()
        if recent_ids and config.chat_image_recent_turns else []
    )
    images_by_message: dict[str, list[ChatImage]] = {}
    for image in recent_image_rows:
        if image.message_id:
            images_by_message.setdefault(image.message_id, []).append(image)
    image_turn_ids = [
        row.id
        for row in recent
        if row.id in images_by_message and row.role == "user"
    ]
    allowed_image_turn_ids = set(image_turn_ids[: config.chat_image_recent_turns])
    picked_desc: list[dict] = []
    for row in recent:
        row_images = images_by_message.get(row.id, []) if row.id in allowed_image_turn_ids else []
        candidate = [
            *picked_desc,
            {"role": row.role, "content": _multimodal_content(row.content, row_images)},
        ]
        if total_cost(messages=candidate) > max_tokens:
            break
        picked_desc = candidate

    messages = list(reversed(picked_desc))
    messages.append({"role": "user", "content": _multimodal_content(context_message, current_images)})
    system = effective_system()
    final_cost = (estimate_tokens(system) if system else 0) + sum(
        _content_token_estimate(item["content"]) for item in messages
    )
    token_breakdown = {
        "messages": sum(_content_token_estimate(item["content"]) for item in messages),
        "system": 0,
        "memory": 0,
        "knowledge": 0,
        "summary": 0,
        "other": 0,
    }
    accounted_parts: list[str] = []
    for key, section in (
        ("system", base_system),
        ("memory", memory_section),
        ("knowledge", knowledge_section),
        ("summary", summary_section),
    ):
        if not section:
            continue
        previous_cost = estimate_tokens("\n\n".join(accounted_parts)) if accounted_parts else 0
        accounted_parts.append(section)
        token_breakdown[key] = estimate_tokens("\n\n".join(accounted_parts)) - previous_cost
    token_breakdown["other"] = max(0, final_cost - sum(token_breakdown.values()))
    return Context(
        system=system,
        messages=messages,
        token_estimate=final_cost,
        max_tokens=max_tokens,
        token_breakdown=token_breakdown,
        conversation_token_estimate=conversation_token_estimate,
        memory_ids=memory_ids,
        sources=sources,
        memory_candidate_count=len(memories),
        memory_exclusions=memory_exclusions,
        knowledge_candidate_count=knowledge_candidate_count,
        knowledge_exclusions=knowledge_exclusions,
    )
