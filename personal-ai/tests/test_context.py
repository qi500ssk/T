from sqlalchemy import text

import core.chat.context as context_module
from core.chat.context import build_context, estimate_tokens
from infrastructure.database import Conversation, Memory, Message, SessionLocal


def test_estimate_tokens():
    assert estimate_tokens("你好") == 3  # 2 个中文字 + 1
    assert estimate_tokens("hello world") == 3  # 11 字符 // 4 + 1


def test_build_context_obeys_hard_budget():
    """单条历史超过剩余预算时不注入，本次输入必保且总量不超限。"""
    with SessionLocal() as session:
        for i in range(5):
            session.add(
                Message(
                    conversation_id="c1",
                    role="user" if i % 2 == 0 else "assistant",
                    content="很长的消息内容" * 50,  # 约 350 tokens/条
                )
            )
        session.commit()

    with SessionLocal() as session:
        ctx = build_context(session, "SYSTEM_PROMPT", "c1", "新消息", max_tokens=200, recent_count=40)

    assert ctx.messages[-1] == {"role": "user", "content": "新消息"}
    assert len(ctx.messages) == 1
    assert 0 < ctx.token_estimate <= 200
    assert ctx.max_tokens == 200
    assert sum(ctx.token_breakdown.values()) == ctx.token_estimate
    assert ctx.conversation_token_estimate > ctx.token_estimate


def test_build_context_recent_limit():
    """超过 recent_count 的历史不会进入上下文。"""
    with SessionLocal() as session:
        for i in range(20):
            session.add(
                Message(conversation_id="c2", role="user", content=f"短消息{i}")
            )
        session.commit()

    with SessionLocal() as session:
        ctx = build_context(session, "SYSTEM_PROMPT", "c2", "新消息", max_tokens=10_000, recent_count=5)

    assert len(ctx.messages) == 6  # 最近 5 条历史 + 本次输入


def test_interrupted_assistant_draft_is_not_added_to_model_context():
    with SessionLocal() as session:
        session.add_all(
            [
                Message(
                    conversation_id="draft-context",
                    role="assistant",
                    content="半截且可能错误的结论",
                    status="interrupted",
                ),
                Message(
                    conversation_id="draft-context",
                    role="user",
                    content="已经完成的历史消息",
                ),
            ]
        )
        session.commit()

    with SessionLocal() as session:
        ctx = build_context(
            session,
            "SYSTEM",
            "draft-context",
            "重新回答",
            max_tokens=2_000,
            recent_count=10,
        )

    assert not any("半截且可能错误" in str(item["content"]) for item in ctx.messages)
    assert any("已经完成的历史消息" in str(item["content"]) for item in ctx.messages)


def test_build_context_injects_relevant_active_memory():
    with SessionLocal() as session:
        session.add(Conversation(id="c3", summary="用户正在规划早餐。"))
        session.add_all(
            [
                Memory(user_id="default", content="用户喜欢无糖拿铁", normalized_key="coffee", importance=4),
                Memory(
                    user_id="default",
                    content="用户喜欢红茶",
                    normalized_key="tea",
                    importance=5,
                    is_active=False,
                ),
            ]
        )
        session.commit()

    with SessionLocal() as session:
        ctx = build_context(session, "SYSTEM", "c3", "我喜欢喝什么？", 2000, 40)

    assert "用户喜欢无糖拿铁" in ctx.system
    assert "用户喜欢红茶" not in ctx.system
    assert "用户正在规划早餐" in ctx.system


def test_build_context_marks_memory_usage_and_respects_scope():
    """装入上下文的记忆计一次使用；其他项目的 project 记忆不可见。"""
    with SessionLocal() as session:
        session.add(Conversation(id="c-scope-usage"))
        session.add_all(
            [
                Memory(
                    user_id="default",
                    content="用户喜欢无糖拿铁",
                    normalized_key="coffee",
                    importance=4,
                ),
                Memory(
                    user_id="default",
                    content="JQ 项目数据库使用 PostgreSQL",
                    normalized_key="db.engine",
                    importance=5,
                    scope_type="project",
                    scope_key="proj-other",
                ),
            ]
        )
        session.commit()

    with SessionLocal() as session:
        ctx = build_context(session, "SYSTEM", "c-scope-usage", "我喜欢喝什么？", 2000, 40)

    assert "用户喜欢无糖拿铁" in ctx.system
    assert "JQ 项目数据库使用 PostgreSQL" not in ctx.system

    with SessionLocal() as session:
        memory = session.query(Memory).filter(Memory.normalized_key == "coffee").one()
        assert memory.usage_count == 1
        assert memory.last_used_at is not None


def test_context_observability_distinguishes_candidates_usage_and_trimmed_items():
    with SessionLocal() as session:
        session.add(Conversation(id="c-observability"))
        session.add_all(
            [
                Memory(
                    user_id="default",
                    content=f"咖啡偏好候选 {index}",
                    normalized_key=f"coffee.{index}",
                    importance=5 - index,
                )
                for index in range(3)
            ]
        )
        session.commit()

    with SessionLocal() as session:
        context = build_context(
            session,
            "SYSTEM",
            "c-observability",
            "咖啡偏好",
            2000,
            40,
            memory_limit=1,
        )

    assert context.memory_candidate_count == 3
    assert len(context.memory_ids) == 1
    assert sum(item["reason"] == "recall_limit" for item in context.memory_exclusions) == 2
    with SessionLocal() as session:
        rows = session.query(Memory).order_by(Memory.normalized_key).all()
        assert sum(row.usage_count for row in rows) == 1


def test_usage_feedback_failure_rolls_back_and_context_still_builds(monkeypatch):
    with SessionLocal() as session:
        session.add(Conversation(id="c-usage-failure"))
        session.add(
            Memory(
                user_id="default",
                content="用户喜欢无糖拿铁",
                normalized_key="coffee",
                importance=4,
            )
        )
        session.commit()

    def fail_feedback(session, _memory_ids):
        session.execute(text("SELECT * FROM intentionally_missing_usage_table"))

    monkeypatch.setattr(context_module, "mark_memories_used", fail_feedback)
    with SessionLocal() as session:
        context = build_context(
            session,
            "SYSTEM",
            "c-usage-failure",
            "我喜欢喝什么？",
            2000,
            40,
        )
    assert "用户喜欢无糖拿铁" in context.system


def test_build_context_excludes_current_persisted_message():
    with SessionLocal() as session:
        session.add(Conversation(id="c4"))
        current = Message(conversation_id="c4", role="user", content="本轮输入")
        session.add(current)
        session.commit()
        current_id = current.id

    with SessionLocal() as session:
        ctx = build_context(
            session,
            "SYSTEM",
            "c4",
            "本轮输入",
            2000,
            40,
            exclude_message_id=current_id,
        )

    assert ctx.messages == [{"role": "user", "content": "本轮输入"}]


def test_build_context_truncates_oversized_current_question():
    with SessionLocal() as session:
        ctx = build_context(session, "SYSTEM", "missing", "超长问题" * 500, 100, 40)

    assert ctx.token_estimate <= 100
    assert ctx.messages[-1]["content"]
    assert len(ctx.messages[-1]["content"]) < len("超长问题" * 500)
