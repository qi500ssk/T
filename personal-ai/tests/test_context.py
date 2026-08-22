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
