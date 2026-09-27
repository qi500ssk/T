"""Bounded conversation candidates, never included in automatic recall."""
from datetime import datetime, timedelta, timezone
from infrastructure.database import CandidateMemory, Memory
from core.memory.conversation import contains_sensitive_information


def retain_candidates(session, candidates, user_id, agent_id, conversation_id, min_importance, min_confidence):
    if not agent_id: return candidates
    now = datetime.now(timezone.utc)
    session.query(CandidateMemory).filter(CandidateMemory.agent_id == agent_id, CandidateMemory.user_id == user_id,
        CandidateMemory.expires_at <= now).delete(synchronize_session=False)
    dismissed = {r.normalized_key for r in session.query(CandidateMemory).filter_by(user_id=user_id,agent_id=agent_id,status="dismissed")}
    candidates = [item for item in candidates if item.key not in dismissed]
    for item in candidates:
        if contains_sensitive_information(item.content) or item.confidence < 0.5: continue
        row = session.query(CandidateMemory).filter_by(user_id=user_id, agent_id=agent_id, normalized_key=item.key).first()
        if item.importance >= min_importance and item.confidence >= min_confidence:
            if row: session.delete(row)
            continue
        if row and row.status == "dismissed": continue
        # A weak candidate must never replace an already confirmed fact.
        if session.query(Memory).filter_by(user_id=user_id,scope_type="agent",scope_key=agent_id,normalized_key=item.key).first(): continue
        if row is None:
            row = CandidateMemory(user_id=user_id,agent_id=agent_id,normalized_key=item.key)
            session.add(row)
        row.content, row.kind = item.content, item.kind
        row.importance, row.confidence = item.importance, item.confidence
        row.source_conversation_id, row.status = conversation_id, "pending"
        row.expires_at, row.updated_at = now + timedelta(days=30), now
    session.flush()
    # Keep at most 200 live candidate entries per character.
    overflow = session.query(CandidateMemory).filter_by(user_id=user_id,agent_id=agent_id).order_by(CandidateMemory.updated_at.desc(),CandidateMemory.id).offset(200).all()
    for row in overflow: session.delete(row)
    session.commit()
    return candidates
