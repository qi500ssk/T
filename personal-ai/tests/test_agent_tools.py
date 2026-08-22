import json

import pytest

from core.chat.agent import merge_tool_call_deltas, run_chat
from core.chat.gateway import MockProvider, StreamChunk
from core.execution.permissions import APPROVAL_WAITERS, resolve_approval
from core.capabilities.skills import load_skills
from core.execution.tool_pipeline import register_pre_tool_hook
from infrastructure.config import settings
from infrastructure.database import AgentRun, Conversation, SessionLocal, ToolRun


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


@pytest.mark.asyncio
async def test_mock_tool_flow_and_tool_run_record(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    events = await _run("现在几点")
    types = [event.type for event in events]
    assert "tool.started" in types
    assert "tool.completed" in types
    assert types[-2:] == ["message.completed", "run.completed"]
    with SessionLocal() as session:
        row = session.query(ToolRun).one()
        assert row.tool == "get_time"
        assert row.step_index == 0
        assert row.status == "completed"
        run = session.query(AgentRun).one()
        assert len(run.capability_version) == 64
        assert "skill_load" in run.capability_snapshot["tools"]
    started = next(event for event in events if event.type == "run.started")
    assert started.data["capability_version"]
    assert "file-notes" in started.data["enabled_skills"]


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
