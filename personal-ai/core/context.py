"""Context Engine：按总预算组装 System、记忆、RAG、摘要和最近对话。"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from core.memory import retrieve_memories
from core.rag.retrieval import retrieve
from infrastructure.config import settings
from infrastructure.database import Conversation, Message


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


@dataclass
class Context:
    system: str
    messages: list[dict] = field(default_factory=list)
    token_estimate: int = 0
    memory_ids: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


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
) -> Context:
    """按 Memory → RAG → Summary → Recent 的优先级组装且不超过总预算。"""
    config = rag_settings or settings
    context_message = _truncate_to_budget(message, max_tokens)
    query_cost = estimate_tokens(context_message)
    system_budget = max(0, max_tokens - query_cost)
    combined_system = system_prompt
    if system_addendum:
        combined_system += "\n\n" + system_addendum
    base_system = _truncate_to_budget(combined_system, system_budget)
    system_parts = [base_system] if base_system else []
    memory_ids: list[str] = []
    sources: list[dict] = []

    def effective_system(parts: list[str] | None = None) -> str:
        return "\n\n".join(parts if parts is not None else system_parts)

    def total_cost(parts: list[str] | None = None, messages: list[dict] | None = None) -> int:
        text = effective_system(parts)
        text_cost = estimate_tokens(text) if text else 0
        return text_cost + sum(estimate_tokens(item["content"]) for item in (messages or [])) + query_cost

    memories = retrieve_memories(session, user_id, message, memory_limit) if memory_limit else []
    memory_lines: list[str] = []
    for item in memories:
        candidate_lines = [*memory_lines, f"- {item.content}"]
        section = "[相关用户记忆]\n" + "\n".join(candidate_lines)
        if estimate_tokens(section) > config.memory_tokens_budget:
            break
        if total_cost([*system_parts, section]) > max_tokens:
            break
        memory_lines = candidate_lines
        memory_ids.append(item.id)
    if memory_lines:
        system_parts.append("[相关用户记忆]\n" + "\n".join(memory_lines))

    if embedding_provider is not None and config.rag_enabled:
        results = retrieve(session, embedding_provider, message, config, user_id)
        rag_prompt = Path(config.rag_context_prompt_file).read_text(encoding="utf-8").strip()
        source_blocks: list[str] = []
        for result in results:
            citation_id = f"c{len(sources) + 1}"
            block = (
                f'<source citation_id="{citation_id}" file="{escape(result.filename, quote=True)}" '
                f'section="{escape(result.section, quote=True)}">'
                f"{escape(result.content, quote=True)}</source>"
            )
            candidate_blocks = [*source_blocks, block]
            section = rag_prompt + "\n\n" + "\n\n".join(candidate_blocks)
            if estimate_tokens(section) > config.rag_tokens_budget:
                break
            if total_cost([*system_parts, section]) > max_tokens:
                break
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
            system_parts.append(rag_prompt + "\n\n" + "\n\n".join(source_blocks))

    conversation = session.get(Conversation, conversation_id)
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
                system_parts.append(section)

    query = session.query(Message).filter(Message.conversation_id == conversation_id)
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
    picked_desc: list[dict] = []
    for row in recent:
        candidate = [*picked_desc, {"role": row.role, "content": row.content}]
        if total_cost(messages=candidate) > max_tokens:
            break
        picked_desc = candidate

    messages = list(reversed(picked_desc))
    messages.append({"role": "user", "content": context_message})
    system = effective_system()
    final_cost = (estimate_tokens(system) if system else 0) + sum(
        estimate_tokens(item["content"]) for item in messages
    )
    return Context(
        system=system,
        messages=messages,
        token_estimate=final_cost,
        memory_ids=memory_ids,
        sources=sources,
    )
