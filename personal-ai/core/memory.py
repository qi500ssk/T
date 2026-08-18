"""长期记忆：从对话提取事实、去重写入，并为当前问题召回相关内容。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from infrastructure.database import Memory


_PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "memory" / "extract.md"
_KINDS = {"episodic", "semantic", "profile"}
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
        key = normalize_memory_key(str(item.get("key", "")), content)
        if kind in _KINDS and content and key and not contains_sensitive_information(content):
            candidates.append(MemoryCandidate(key, kind, content[:2000], importance, confidence))
    return candidates


def save_memories(
    session: Session,
    candidates: list[MemoryCandidate],
    user_id: str,
    conversation_id: str,
    min_importance: int,
    min_confidence: float,
) -> int:
    saved = 0
    for candidate in candidates:
        if (
            candidate.importance < min_importance
            or candidate.confidence < min_confidence
            or contains_sensitive_information(candidate.content)
        ):
            continue
        existing = (
            session.query(Memory)
            .filter(Memory.user_id == user_id, Memory.normalized_key == candidate.key)
            .first()
        )
        if existing is None:
            session.add(
                Memory(
                    user_id=user_id,
                    kind=candidate.kind,
                    content=candidate.content,
                    normalized_key=candidate.key,
                    source_conversation_id=conversation_id,
                    importance=candidate.importance,
                    confidence=candidate.confidence,
                )
            )
        else:
            existing.kind = candidate.kind
            existing.content = candidate.content
            existing.source_conversation_id = conversation_id
            existing.importance = candidate.importance
            existing.confidence = candidate.confidence
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
        saved += 1
    if saved:
        session.commit()
    return saved


def _terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    terms.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return terms


def retrieve_memories(session: Session, user_id: str, query: str, limit: int) -> list[Memory]:
    query_terms = _terms(query)
    rows = (
        session.query(Memory)
        .filter(Memory.user_id == user_id, Memory.is_active.is_(True))
        .order_by(Memory.updated_at.desc())
        .limit(200)
        .all()
    )

    def score(memory: Memory) -> float:
        overlap = len(query_terms & _terms(memory.content))
        exact = 3 if query.strip() and query.strip() in memory.content else 0
        return overlap * 2 + exact + memory.importance * 0.1

    ranked = [(score(memory), memory) for memory in rows]
    ranked = [item for item in ranked if item[0] >= 1]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in ranked[:limit]]
