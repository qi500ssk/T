from core.chat.continuation import find_continuation_context, is_continuation_request
from infrastructure.database import AgentRun, Conversation, Message, SessionLocal


def test_continuation_request_is_deliberately_narrow():
    assert is_continuation_request("继续")
    assert is_continuation_request("从中断处继续。")
    assert is_continuation_request("resume")
    assert not is_continuation_request("继续介绍一个全新的主题")
    assert not is_continuation_request("这个功能要继续保留")


def test_continuation_does_not_reopen_a_stale_interrupted_run():
    with SessionLocal() as session:
        conversation = Conversation(title="Continuation guard")
        session.add(conversation)
        session.flush()
        original = Message(
            conversation_id=conversation.id,
            role="user",
            content="旧任务",
        )
        session.add(original)
        session.flush()
        session.add(
            AgentRun(
                conversation_id=conversation.id,
                input_message_id=original.id,
                execution_mode="direct",
                status="interrupted",
            )
        )
        session.flush()
        latest = AgentRun(
            conversation_id=conversation.id,
            execution_mode="direct",
            status="completed",
        )
        session.add(latest)
        session.commit()

        assert (
            find_continuation_context(
                session,
                conversation.id,
                exclude_run_id="f" * 32,
            )
            is None
        )
