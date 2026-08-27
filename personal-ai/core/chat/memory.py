"""聊天域长期记忆：提取事实、按作用域去重写入并按当前问题召回。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from infrastructure.database import Memory


logger = logging.getLogger(__name__)


_PROMPT_FILE = Path(__file__).resolve().parents[2] / "prompts" / "memory" / "extract.md"
_KINDS = {"episodic", "semantic", "profile"}
_SCOPES = {"global", "agent", "project", "conversation"}
EXTRACTION_VERSION = "extract-v2"
_NEAR_DUPLICATE_DISTANCE = 0.02
_OPT_OUT_PATTERN = re.compile(
    r"(?:不要|别|请勿)(?:再)?(?:记住|记录|保存|存储|写入记忆)|"
    r"(?:do not|don't|dont|never)\s+(?:remember|store|save)",
    re.IGNORECASE,
)
_SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"(?:password|passwd|pwd|密码|口令|api[_ -]?key|secret|token|令牌)"
        r"\s*(?:是|为|[:=])\s*\S{4,}",
        re.IGNORECASE,
    ),
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)"),
)


@dataclass(frozen=True)
class MemoryCandidate:
    key: str
    kind: str
    content: str
    importance: int
    confidence: float
    scope_type: str = "conversation"


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def normalize_memory_key(value: str, content: str) -> str:
    raw = value.strip().lower() or content.strip().lower()
    return re.sub(r"[^\w.\u4e00-\u9fff]+", "", raw)[:200]


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def contains_sensitive_information(text: str) -> bool:
    """拦截凭据、财务和可直接识别个人身份的信息。"""
    return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)


def memory_opted_out(text: str) -> bool:
    """用户明确要求不记录时，本轮不执行记忆提取。"""
    return bool(_OPT_OUT_PATTERN.search(text))


async def extract_memories(provider, user_input: str, assistant_response: str) -> list[MemoryCandidate]:
    if memory_opted_out(user_input):
        return []
    prompt = _PROMPT_FILE.read_text(encoding="utf-8")
    payload = json.dumps(
        {"user_input": user_input, "assistant_response": assistant_response},
        ensure_ascii=False,
    )
    result = _parse_json(
        await provider.complete(
            [{"role": "system", "content": prompt}, {"role": "user", "content": payload}],
            temperature=0.0,
        )
    )
    candidates: list[MemoryCandidate] = []
    for item in result.get("memories", []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", ""))
        content = str(item.get("content", "")).strip()
        try:
            importance = max(1, min(5, int(item.get("importance", 0))))
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0))))
        except (TypeError, ValueError):
            continue
        scope_type = str(item.get("scope", ""))
        # 自动提取永远属于当前好友；公共记忆只允许用户在管理页显式创建。
        if scope_type == "global":
            scope_type = "agent"
        if scope_type not in _SCOPES:
            scope_type = "conversation"
        key = normalize_memory_key(str(item.get("key", "")), content)
        if kind in _KINDS and content and key and not contains_sensitive_information(content):
            candidates.append(
                MemoryCandidate(key, kind, content[:2000], importance, confidence, scope_type)
            )
    return candidates


def _resolve_scope(
    scope_type: str,
    conversation_id: str,
    project_id: str | None,
    agent_id: str | None,
) -> tuple[str, str]:
    """无法判断或 project 缺少上下文时，一律保守降级到 conversation scope。"""
    if scope_type not in _SCOPES:
        scope_type = "conversation"
    if scope_type == "project" and not project_id:
        scope_type = "conversation"
    if scope_type == "agent" and not agent_id:
        scope_type = "conversation"
    scope_key = {
        "global": "global",
        "agent": agent_id or "",
        "project": project_id or "",
        "conversation": conversation_id,
    }[scope_type]
    return scope_type, scope_key


def _recall_filters(
    user_id: str,
    conversation_id: str | None,
    project_id: str | None,
    agent_id: str | None,
    now: datetime,
) -> list:
    """召回硬过滤：用户、状态、有效期和作用域，向量候选与词法候选共用。"""
    scope_conditions = [and_(Memory.scope_type == "global", Memory.scope_key == "global")]
    if agent_id:
        scope_conditions.append(
            and_(Memory.scope_type == "agent", Memory.scope_key == agent_id)
        )
    if conversation_id:
        scope_conditions.append(
            and_(Memory.scope_type == "conversation", Memory.scope_key == conversation_id)
        )
    if project_id:
        scope_conditions.append(and_(Memory.scope_type == "project", Memory.scope_key == project_id))
    return [
        Memory.user_id == user_id,
        Memory.is_active.is_(True),
        Memory.status == "active",
        or_(Memory.expires_at.is_(None), Memory.expires_at > now),
        or_(*scope_conditions),
    ]


def save_memories(
    session: Session,
    candidates: list[MemoryCandidate],
    user_id: str,
    conversation_id: str,
    min_importance: int,
    min_confidence: float,
    embedding_provider=None,
    project_id: str | None = None,
    agent_id: str | None = None,
) -> int:
    saved = 0
    accepted = [
        candidate
        for candidate in candidates
        if candidate.importance >= min_importance
        and candidate.confidence >= min_confidence
        and not contains_sensitive_information(candidate.content)
    ]
    embeddings: list[list[float] | None] = [None] * len(accepted)
    if accepted and embedding_provider is not None:
        try:
            embeddings = embedding_provider.embed_documents(
                [candidate.content for candidate in accepted]
            )
        except Exception:
            logger.exception("长期记忆向量生成失败，保留文本记忆并使用关键词召回")
    now = datetime.now(timezone.utc)
    seen_in_batch: set[tuple[str, str, str]] = set()
    for candidate, embedding in zip(accepted, embeddings, strict=True):
        scope_type, scope_key = _resolve_scope(
            candidate.scope_type, conversation_id, project_id, agent_id
        )
        # 同一批候选里的重复 key 直接跳过：改名释放槽位依赖已提交状态。
        if (scope_type, scope_key, candidate.key) in seen_in_batch:
            continue
        seen_in_batch.add((scope_type, scope_key, candidate.key))
        content_hash = _content_hash(candidate.content)
        exact_duplicate = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.scope_type == scope_type,
                Memory.scope_key == scope_key,
                Memory.content_hash == content_hash,
                Memory.status == "active",
            )
            .first()
        )
        if exact_duplicate is not None:
            # content_hash 去重独立于 key 和 embedding；停用记录也不被自动复活。
            continue
        existing = (
            session.query(Memory)
            .filter(
                Memory.user_id == user_id,
                Memory.scope_type == scope_type,
                Memory.scope_key == scope_key,
                Memory.normalized_key == candidate.key,
            )
            .first()
        )
        if existing is not None and not existing.is_active:
            # 用户手动停用的 key 不允许被后台提取流程换一种说法重新启用。
            continue
        if existing is None and embedding is not None:
            near_duplicate = (
                session.query(Memory)
                .filter(
                    Memory.user_id == user_id,
                    Memory.scope_type == scope_type,
                    Memory.scope_key == scope_key,
                    Memory.is_active.is_(True),
                    Memory.status == "active",
                    or_(Memory.expires_at.is_(None), Memory.expires_at > now),
                    Memory.embedding.is_not(None),
                    Memory.embedding_model == embedding_provider.model_name,
                    Memory.embedding_dim == embedding_provider.dimension,
                    Memory.embedding.cosine_distance(embedding)
                    < _NEAR_DUPLICATE_DISTANCE,
                )
                .first()
            )
            if near_duplicate is not None:
                continue
        supersedes_id = None
        if existing is not None:
            # 释放 normalized_key 唯一槽位并保留替换链，旧记忆不再直接覆盖。
            supersedes_id = existing.id
            existing.status = "superseded"
            existing.normalized_key = f"superseded.{existing.id}"
            existing.updated_at = now
        session.add(
            Memory(
                user_id=user_id,
                kind=candidate.kind,
                content=candidate.content,
                normalized_key=candidate.key,
                source_conversation_id=conversation_id,
                importance=candidate.importance,
                confidence=candidate.confidence,
                scope_type=scope_type,
                scope_key=scope_key,
                content_hash=content_hash,
                supersedes_id=supersedes_id,
                extraction_version=EXTRACTION_VERSION,
                embedding=embedding,
                embedding_model=(embedding_provider.model_name if embedding is not None else None),
                embedding_dim=(embedding_provider.dimension if embedding is not None else None),
                embedding_version=(embedding_provider.model_name if embedding is not None else None),
                embedded_at=(now if embedding is not None else None),
            )
        )
        saved += 1
    if saved:
        session.commit()
    return saved


def revise_memory(
    session: Session,
    memory: Memory,
    *,
    content: str | None = None,
    kind: str | None = None,
    importance: int | None = None,
    scope_type: str | None = None,
    scope_key: str | None = None,
    is_active: bool | None = None,
    embedding_provider=None,
) -> Memory:
    """纠正记忆并保留替换链；纯开关/重要度调整不制造新版本。"""
    if memory.status != "active":
        raise ValueError("只有当前有效的记忆可以修改")
    next_content = (content if content is not None else memory.content).strip()
    next_kind = kind or memory.kind
    next_importance = importance if importance is not None else memory.importance
    next_scope_type = scope_type or memory.scope_type
    next_scope_key = scope_key or memory.scope_key
    next_is_active = is_active if is_active is not None else memory.is_active
    if not next_content or len(next_content) > 2000:
        raise ValueError("记忆内容长度必须为 1-2000 个字符")
    if next_kind not in _KINDS:
        raise ValueError("记忆类型无效")
    if next_scope_type not in _SCOPES:
        raise ValueError("记忆作用域无效")
    if not 1 <= int(next_importance) <= 5:
        raise ValueError("记忆重要度必须为 1-5")
    if contains_sensitive_information(next_content):
        raise ValueError("记忆内容包含敏感信息，已拒绝保存")

    structural_change = any(
        (
            next_content != memory.content,
            next_kind != memory.kind,
            next_scope_type != memory.scope_type,
            next_scope_key != memory.scope_key,
        )
    )
    if not structural_change:
        memory.importance = int(next_importance)
        memory.is_active = bool(next_is_active)
        memory.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(memory)
        return memory

    duplicate = (
        session.query(Memory)
        .filter(
            Memory.id != memory.id,
            Memory.user_id == memory.user_id,
            Memory.scope_type == next_scope_type,
            Memory.scope_key == next_scope_key,
            Memory.normalized_key == memory.normalized_key,
            Memory.status == "active",
        )
        .first()
    )
    if duplicate is not None:
        raise ValueError("目标作用域中已有同一条有效记忆")

    now = datetime.now(timezone.utc)
    embedding = None
    if embedding_provider is not None:
        try:
            embedding = embedding_provider.embed_documents([next_content])[0]
        except Exception:
            logger.exception("记忆修订向量生成失败，保留文本记忆")
    original_key = memory.normalized_key
    memory.status = "superseded"
    memory.normalized_key = f"superseded.{memory.id}"
    memory.updated_at = now
    replacement = Memory(
        user_id=memory.user_id,
        kind=next_kind,
        content=next_content,
        normalized_key=original_key,
        source_conversation_id=memory.source_conversation_id,
        importance=int(next_importance),
        confidence=1.0,
        is_active=bool(next_is_active),
        scope_type=next_scope_type,
        scope_key=next_scope_key,
        status="active",
        supersedes_id=memory.id,
        content_hash=_content_hash(next_content),
        extraction_version=memory.extraction_version,
        embedding=embedding,
        embedding_model=(embedding_provider.model_name if embedding is not None else None),
        embedding_dim=(embedding_provider.dimension if embedding is not None else None),
        embedding_version=(embedding_provider.model_name if embedding is not None else None),
        embedded_at=(now if embedding is not None else None),
    )
    session.add(replacement)
    session.commit()
    session.refresh(replacement)
    return replacement


def memory_history(session: Session, memory: Memory) -> list[Memory]:
    """返回一条记忆所在的完整替换链，最新版本在前。"""
    oldest = memory
    ancestry_seen = {oldest.id}
    while oldest.supersedes_id:
        previous = session.get(Memory, oldest.supersedes_id)
        if previous is None or previous.id in ancestry_seen:
            break
        ancestry_seen.add(previous.id)
        oldest = previous
    chain = [oldest]
    forward_seen = {oldest.id}
    while True:
        newer = (
            session.query(Memory)
            .filter(Memory.supersedes_id == chain[-1].id)
            .order_by(Memory.created_at.asc())
            .first()
        )
        if newer is None or newer.id in forward_seen:
            break
        forward_seen.add(newer.id)
        chain.append(newer)
    return list(reversed(chain))


def _terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    terms.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return terms


def retrieve_memories(
    session: Session,
    user_id: str,
    query: str,
    limit: int,
    embedding_provider=None,
    min_vector_similarity: float = 0.3,
    conversation_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
) -> list[Memory]:
    """向量 + 词法双通道召回：先做作用域与状态硬过滤，再统一排序。"""
    now = datetime.now(timezone.utc)
    filters = _recall_filters(user_id, conversation_id, project_id, agent_id, now)
    stripped = query.strip()
    normalized = normalize_memory_key(stripped, stripped) if stripped else ""

    lexical_conditions = []
    if len(normalized) >= 2:
        lexical_conditions.append(Memory.normalized_key == normalized)
    if len(stripped) >= 2:
        lexical_conditions.append(Memory.content.ilike(f"%{stripped}%"))
        lexical_conditions.append(Memory.content.op("%")(stripped))  # pg_trgm 相似
        term_patterns = [f"%{term}%" for term in sorted(_terms(stripped))[:32]]
        if term_patterns:
            # 词元（英文词 + 中文二元组）命中任意一个即可成为候选，
            # 替代旧的“最近 200 条全量进池”，短查询也能召回。
            lexical_conditions.append(
                or_(*[Memory.content.ilike(pattern) for pattern in term_patterns])
            )
    lexical_rows = (
        session.query(Memory)
        .filter(*filters, or_(*lexical_conditions))
        .order_by(Memory.updated_at.desc())
        .limit(50)
        .all()
        if lexical_conditions
        else []
    )

    vector_scores: dict[str, float] = {}
    vector_rows: list[Memory] = []
    if embedding_provider is not None:
        query_vector = embedding_provider.embed_query(query)
        distance = Memory.embedding.cosine_distance(query_vector).label("distance")
        matches = (
            session.query(Memory, distance)
            .filter(
                *filters,
                Memory.embedding.is_not(None),
                Memory.embedding_model == embedding_provider.model_name,
                Memory.embedding_dim == embedding_provider.dimension,
            )
            .order_by(distance.asc())
            .limit(max(limit * 4, 20))
            .all()
        )
        for memory, cosine_distance in matches:
            similarity = 1.0 - float(cosine_distance)
            if similarity >= min_vector_similarity:
                vector_rows.append(memory)
                vector_scores[memory.id] = similarity

    rows_by_id = {memory.id: memory for memory in [*lexical_rows, *vector_rows]}
    query_terms = _terms(query)

    def score(memory: Memory) -> float:
        overlap = len(query_terms & _terms(memory.content))
        exact = 3 if stripped and stripped in memory.content else 0
        key_exact = 3 if normalized and memory.normalized_key == normalized else 0
        semantic = vector_scores.get(memory.id, 0.0) * 2
        return (
            overlap * 2
            + exact
            + key_exact
            + semantic
            + memory.importance * 0.1
            + memory.confidence * 0.5
        )

    ranked = [(score(memory), memory) for memory in rows_by_id.values()]
    ranked = [item for item in ranked if item[0] >= 1]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in ranked[:limit]]


def mark_memories_used(session: Session, memory_ids: list[str]) -> int:
    """只有真正装入上下文的记忆计一次使用。"""
    if not memory_ids:
        return 0
    updated = (
        session.query(Memory)
        .filter(Memory.id.in_(memory_ids))
        .update(
            {
                Memory.usage_count: Memory.usage_count + 1,
                Memory.last_used_at: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
    )
    session.commit()
    return updated
