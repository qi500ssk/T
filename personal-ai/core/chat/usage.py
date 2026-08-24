"""Agent Run token usage aggregation."""

from sqlalchemy import func

from infrastructure.database import AgentRun


def conversation_cache_stats(session, conversation_id: str) -> dict:
    """Return a token-weighted prompt cache average for one conversation.

    Runs whose provider did not report cache usage keep ``cached_input_tokens``
    as NULL and are excluded instead of being incorrectly counted as misses.
    """

    row = (
        session.query(
            func.count(AgentRun.id),
            func.coalesce(func.sum(AgentRun.input_tokens), 0),
            func.coalesce(func.sum(AgentRun.cached_input_tokens), 0),
        )
        .filter(
            AgentRun.conversation_id == conversation_id,
            AgentRun.status == "completed",
            AgentRun.input_tokens > 0,
            AgentRun.cached_input_tokens.isnot(None),
        )
        .one()
    )
    run_count = int(row[0] or 0)
    input_tokens = int(row[1] or 0)
    cached_input_tokens = int(row[2] or 0)
    return {
        "eligible_run_count": run_count,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "average_cache_hit_rate": (
            round(cached_input_tokens / input_tokens * 100, 1)
            if input_tokens > 0
            else None
        ),
    }
