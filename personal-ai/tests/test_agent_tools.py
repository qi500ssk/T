import json

import pytest

from core.agent import merge_tool_call_deltas, run_chat
from core.gateway import MockProvider, StreamChunk
from core.permissions import APPROVAL_WAITERS, resolve_approval
from core.skills import load_skills
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
