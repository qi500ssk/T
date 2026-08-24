import asyncio
import json

import pytest

from core.chat.agent import merge_tool_call_deltas, run_chat
from core.chat.gateway import MockProvider, StreamChunk
from core.execution.permissions import APPROVAL_WAITERS, resolve_approval
from core.execution.executor import ProtocolLeakFilter, ToolCallBudget, execute_model_loop
from core.chat.run_control import cancel_chat_run, register_chat_run, unregister_chat_run
from core.capabilities.skills import load_skills
from core.execution.tool_pipeline import register_pre_tool_hook
from infrastructure.config import settings
from infrastructure.database import AgentRun, Conversation, Memory, Message, SessionLocal, ToolRun


def _conversation() -> str:
    with SessionLocal() as session:
        row = Conversation(title="P3 test")
        session.add(row)
        session.commit()
        return row.id


async def _run(message: str, approve: bool | None = None):
    events = []
    async for event in run_chat(
        MockProvider(delay=0),
        _conversation(),
        message,
        embedding_provider=None,
        skills=load_skills(),
    ):
        events.append(event)
        if event.type == "approval.required" and approve is not None:
            assert resolve_approval(event.data["approval_id"], approve)
    return events


def test_streaming_tool_calls_are_assembled_by_index():
    target = {}
    merge_tool_call_deltas(
        target,
        [
            {"index": 1, "id": "call-2", "function": {"name": "read_", "arguments": "{\"pa"}},
            {"index": 0, "id": "call-1", "function": {"name": "get_", "arguments": "{"}},
        ],
    )
    merge_tool_call_deltas(
        target,
        [
            {"index": 0, "function": {"name": "time", "arguments": "}"}},
            {"index": 1, "function": {"name": "file", "arguments": "th\":\"notes.md\"}"}},
        ],
    )
    assert target[0]["function"] == {"name": "get_time", "arguments": "{}"}
    assert json.loads(target[1]["function"]["arguments"]) == {"path": "notes.md"}


def test_protocol_filter_hides_split_internal_rag_markup():
    protocol_filter = ProtocolLeakFilter()
    visible = [
        protocol_filter.feed("先说结论。<sou"),
        protocol_filter.feed('rce id="c1">内部检索正文'),
        protocol_filter.feed("和协议 JSON</source>最后答案。"),
        protocol_filter.finish(),
    ]
    assert "".join(visible) == "先说结论。最后答案。"


def test_protocol_filter_preserves_normal_markdown_code():
    text = "示例：\n```python\nprint('<source is text>')\n```"
    protocol_filter = ProtocolLeakFilter()
    visible = protocol_filter.feed(text) + protocol_filter.finish()
    assert visible == text


@pytest.mark.asyncio
async def test_executor_never_streams_internal_rag_protocol():
    class ProtocolEchoProvider:
        async def stream(self, messages, temperature=0.7, tools=None):
            yield StreamChunk(text="答案开头<sou")
            yield StreamChunk(text='rce id="c1">内部资料</source>答案结尾')

    events = []
    async for event in execute_model_loop(
        ProtocolEchoProvider(),
        [{"role": "user", "content": "问题"}],
        None,
        set(),
        "0" * 32,
        "1" * 32,
        max_turns=1,
        tool_budget=ToolCallBudget(0),
    ):
        events.append(event)
    streamed = "".join(
        event.data["content"] for event in events if event.type == "message.delta"
    )
    assert streamed == "答案开头答案结尾"
    assert events[-1].data["content"] == streamed


@pytest.mark.asyncio
async def test_user_stop_persists_partial_reply_as_interrupted(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    ready = asyncio.Event()
    run_id = "e" * 32
    conversation_id = _conversation()

    class PartialProvider:
        async def stream(self, messages, temperature=0.7, tools=None):
            yield StreamChunk(text="这是一段已经显示的部分回答。")
            await asyncio.Event().wait()

        async def complete(self, messages, temperature=0.0):
            return ""

    async def worker():
        register_chat_run(run_id, conversation_id)
        try:
            async for event in run_chat(
                PartialProvider(),
                conversation_id,
                "你好",
                skills=[],
                run_id=run_id,
            ):
                if event.type == "message.delta":
                    ready.set()
        finally:
            unregister_chat_run(run_id)

    task = asyncio.create_task(worker())
    await asyncio.wait_for(ready.wait(), timeout=2)
    assert cancel_chat_run(run_id)
    with pytest.raises(asyncio.CancelledError):
        await task

    with SessionLocal() as session:
        run = session.get(AgentRun, run_id)
        draft = (
            session.query(Message)
            .filter(Message.run_id == run_id, Message.role == "assistant")
            .one()
        )
        assert run.status == "interrupted"
        assert draft.status == "interrupted"
        assert draft.content == "这是一段已经显示的部分回答。"


@pytest.mark.asyncio
async def test_continue_creates_new_reply_from_latest_interrupted_draft(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    conversation_id = _conversation()
    with SessionLocal() as session:
        original = Message(
            conversation_id=conversation_id,
            role="user",
            content="写一个三段的小故事",
        )
        session.add(original)
        session.flush()
        interrupted_run = AgentRun(
            conversation_id=conversation_id,
            input_message_id=original.id,
            execution_mode="direct",
            status="interrupted",
        )
        session.add(interrupted_run)
        session.flush()
        interrupted = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="第一段已经写到这里，主角推开了门。",
            run_id=interrupted_run.id,
            status="interrupted",
        )
        session.add(interrupted)
        session.commit()
        interrupted_ids = interrupted_run.id, interrupted.id

    class ContinuationProvider:
        def __init__(self):
            self.messages = []

        async def stream(self, messages, temperature=0.7, tools=None):
            self.messages = messages
            yield StreamChunk(text="门后是故事的下一幕。", finish_reason="stop")

        async def complete(self, messages, temperature=0.0):
            return ""

    provider = ContinuationProvider()
    events = []
    async for event in run_chat(
        provider,
        conversation_id,
        "继续",
        skills=[],
        run_id="f" * 32,
    ):
        events.append(event)

    system_text = "\n".join(
        str(item.get("content") or "")
        for item in provider.messages
        if item.get("role") == "system"
    )
    assert "写一个三段的小故事" in system_text
    assert "第一段已经写到这里，主角推开了门。" in system_text
    assert "避免重复已经显示的部分" in system_text
    assert [event.type for event in events][-2:] == ["message.completed", "run.completed"]

    with SessionLocal() as session:
        old_draft = session.get(Message, interrupted_ids[1])
        replies = (
            session.query(Message)
            .filter(Message.conversation_id == conversation_id, Message.role == "assistant")
            .order_by(Message.created_at.asc())
            .all()
        )
        assert old_draft.status == "interrupted"
        assert len(replies) == 2
        assert replies[-1].content == "门后是故事的下一幕。"
        assert replies[-1].status == "completed"
        assert replies[-1].run_id != interrupted_ids[0]


@pytest.mark.asyncio
async def test_mock_tool_flow_and_tool_run_record(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    events = await _run("现在几点")
    types = [event.type for event in events]
    assert "tool.proposed" in types
    assert "tool.started" in types
    assert "tool.completed" in types
    assert types.index("tool.proposed") < types.index("tool.started")
    assert types[-2:] == ["message.completed", "run.completed"]
    with SessionLocal() as session:
        row = session.query(ToolRun).one()
        assert row.tool == "get_time"
        assert row.step_index == 0
        assert row.status == "completed"
        run = session.query(AgentRun).one()
        assert len(run.capability_version) == 64
        # 意图只推荐候选，所有由用户启用的工具仍保留在本轮能力边界内。
        assert "get_time" in run.capability_snapshot["tools"]
        assert "calculate" in run.capability_snapshot["tools"]
    started = next(event for event in events if event.type == "run.started")
    assert started.data["capability_version"]
    assert "file-notes" in started.data["enabled_skills"]
    proposed = next(event for event in events if event.type == "tool.proposed")
    assert proposed.data["risk_level"] == "low"
    assert proposed.data["effect"]


@pytest.mark.asyncio
async def test_pre_tool_pipeline_can_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)

    async def deny_time(invocation):
        return "测试策略拒绝" if invocation.name == "get_time" else None

    dispose = register_pre_tool_hook(deny_time)
    try:
        events = await _run("现在几点")
    finally:
        dispose()
    assert not any(event.type == "tool.started" for event in events)
    completed = next(event for event in events if event.type == "tool.completed")
    assert completed.data["status"] == "rejected"
    assert "测试策略拒绝" in completed.data["result_summary"]


@pytest.mark.asyncio
async def test_write_approval_approved_and_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "sandbox_dir", str(tmp_path))

    approved_events = await _run("保存笔记：批准后的内容", approve=True)
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "批准后的内容"
    approved_types = [event.type for event in approved_events]
    assert approved_types.index("approval.completed") < approved_types.index("tool.started")

    (tmp_path / "notes.md").write_text("unchanged", encoding="utf-8")
    rejected_events = await _run("保存笔记：不能写入", approve=False)
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "unchanged"
    assert not any(event.type == "tool.started" for event in rejected_events)
    with SessionLocal() as session:
        statuses = [row.status for row in session.query(ToolRun).order_by(ToolRun.created_at)]
        assert statuses == ["completed", "rejected"]


@pytest.mark.asyncio
async def test_closing_stream_at_approval_cleans_state(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "memory_enabled", False)
    monkeypatch.setattr(settings, "sandbox_dir", str(tmp_path))
    stream = run_chat(
        MockProvider(delay=0),
        _conversation(),
        "保存笔记：不会写入",
        skills=load_skills(),
    )
    approval_id = ""
    async for event in stream:
        if event.type == "approval.required":
            approval_id = event.data["approval_id"]
            break
    await stream.aclose()
    assert approval_id not in APPROVAL_WAITERS
    assert not (tmp_path / "notes.md").exists()
    with SessionLocal() as session:
        assert session.query(AgentRun).one().status == "cancelled"
        assert session.query(ToolRun).one().status == "failed"


class RecordingProvider:
    def __init__(self):
        self.calls = []

    async def stream(self, messages, temperature=0.7, tools=None):
        self.calls.append(messages.copy())
        if len(self.calls) == 1:
            yield StreamChunk(
                tool_calls_delta=[
                    {
                        "index": 0,
                        "id": "call-recorded",
                        "type": "function",
                        "function": {"name": "get_time", "arguments": "{}"},
                    }
                ],
                finish_reason="tool_calls",
            )
        else:
            yield StreamChunk(text="done", finish_reason="stop")

    async def complete(self, messages, temperature=0.0):
        return ""


class SequencedMemoryCreateProvider:
    def __init__(self, requests: list[dict]):
        self.requests = requests
        self.calls = 0
        self.final_messages = []

    async def stream(self, messages, temperature=0.7, tools=None):
        if self.calls < len(self.requests):
            request = self.requests[self.calls]
            call_index = self.calls
            self.calls += 1
            assert any(item["function"]["name"] == "memory_create" for item in tools)
            yield StreamChunk(
                tool_calls_delta=[
                    {
                        "index": 0,
                        "id": f"memory-create-{call_index}",
                        "type": "function",
                        "function": {
                            "name": "memory_create",
                            "arguments": json.dumps(request, ensure_ascii=False),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
            return
        self.final_messages = messages
        yield StreamChunk(text="记忆处理完成", finish_reason="stop")

    async def complete(self, messages, temperature=0.0):
        return ""


def _memory_create_args(content: str, key: str) -> dict:
    return {
        "content": content,
        "key": key,
        "kind": "profile",
        "scope_type": "global",
        "importance": 3,
    }


@pytest.mark.asyncio
async def test_same_run_skips_duplicate_memory_create_for_same_scope_and_key():
    provider = SequencedMemoryCreateProvider(
        [
            _memory_create_args("用户希望被称为骑士大人。", "user.preferred_address"),
            _memory_create_args("用户希望被称为雷姆永远的骑士大人。", "user.preferred_address"),
        ]
    )
    events = []
    async for event in run_chat(
        provider,
        _conversation(),
        "请记住以后称呼我为骑士大人",
        embedding_provider=None,
        skills=load_skills(),
    ):
        events.append(event)

    memory_events = [
        event for event in events
        if event.type in {"tool.completed", "tool.reused"}
        and event.data.get("tool") == "memory_create"
    ]
    assert [event.type for event in memory_events] == ["tool.completed", "tool.reused"]
    assert "duplicate_create_skipped" in memory_events[1].data["result_summary"]
    assert "memory_update" in provider.final_messages[-1]["content"]
    with SessionLocal() as session:
        memories = session.query(Memory).all()
        tool_runs = session.query(ToolRun).filter(ToolRun.tool == "memory_create").all()
        assert len(memories) == 1
        assert memories[0].content == "用户希望被称为骑士大人。"
        assert memories[0].status == "active"
        assert len(tool_runs) == 1
        assert tool_runs[0].status == "completed"


@pytest.mark.asyncio
async def test_same_run_allows_memory_create_for_different_keys():
    provider = SequencedMemoryCreateProvider(
        [
            _memory_create_args("用户希望被称为骑士大人。", "user.preferred_address"),
            _memory_create_args("用户偏好简洁回答。", "user.response_style"),
        ]
    )
    events = []
    async for event in run_chat(
        provider,
        _conversation(),
        "请记住我的称呼和回答风格",
        embedding_provider=None,
        skills=load_skills(),
    ):
        events.append(event)

    completed = [
        event for event in events
        if event.type == "tool.completed" and event.data.get("tool") == "memory_create"
    ]
    assert len(completed) == 2
    assert not any(event.type == "tool.reused" for event in events)
    with SessionLocal() as session:
        assert session.query(Memory).count() == 2
        assert session.query(ToolRun).filter(ToolRun.tool == "memory_create").count() == 2


class SkillLoadingProvider:
    def __init__(self):
        self.calls = 0
        self.loaded_content = ""

    async def stream(self, messages, temperature=0.7, tools=None):
        self.calls += 1
        if self.calls == 1:
            assert any(item["function"]["name"] == "skill_load" for item in tools)
            yield StreamChunk(tool_calls_delta=[{
                "index": 0,
                "id": "load-notes",
                "type": "function",
                "function": {"name": "skill_load", "arguments": '{"name":"file-notes"}'},
            }], finish_reason="tool_calls")
            return
        self.loaded_content = messages[-1]["content"]
        yield StreamChunk(text="已按 Skill 处理", finish_reason="stop")

    async def complete(self, messages, temperature=0.0):
        return ""


@pytest.mark.asyncio
async def test_assistant_tool_call_message_is_returned(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    provider = RecordingProvider()
    async for _ in run_chat(provider, _conversation(), "tool", skills=[]):
        pass
    second_call = provider.calls[1]
    assert second_call[-2]["role"] == "assistant"
    assert second_call[-2]["tool_calls"][0]["id"] == "call-recorded"
    assert second_call[-1]["role"] == "tool"
    assert second_call[-1]["tool_call_id"] == "call-recorded"


@pytest.mark.asyncio
async def test_agent_can_lazy_load_enabled_skill(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    provider = SkillLoadingProvider()
    events = []
    async for event in run_chat(
        provider,
        _conversation(),
        "请读取笔记",
        skills=load_skills(),
    ):
        events.append(event)
    assert "read_file" in provider.loaded_content
    assert any(
        event.type == "tool.completed" and event.data["tool"] == "skill_load"
        for event in events
    )
