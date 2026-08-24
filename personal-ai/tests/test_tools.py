import asyncio
import json

import pytest

from core.execution.tools import TOOLS, Tool, execute_tool
from core.execution.memory_tools import (
    bind_memory_tool_context,
    reset_memory_tool_context,
)
from infrastructure.config import settings
from infrastructure.database import Conversation, Memory, Project, SessionLocal


@pytest.mark.asyncio
async def test_calculate_safe_and_rejects_code():
    allowed = {"calculate"}
    result = await execute_tool("calculate", {"expression": "12 * (3 + 4)"}, allowed)
    assert result.status == "completed"
    assert result.content == "84"

    rejected = await execute_tool(
        "calculate", {"expression": "__import__('os').getcwd()"}, allowed
    )
    assert rejected.status == "failed"
    assert "不允许" in rejected.content


@pytest.mark.asyncio
async def test_calculate_and_argument_limits():
    too_deep = await execute_tool(
        "calculate", {"expression": "1+(1+(1+(1+(1+(1+(1+(1+(1+1))))))))"}, {"calculate"}
    )
    assert too_deep.status == "failed"

    malformed = await execute_tool("calculate", {"wrong": "1+1"}, {"calculate"})
    assert malformed.status == "failed"
    assert "未知参数" in malformed.content


@pytest.mark.asyncio
async def test_file_sandbox_read_write_and_size_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_dir", str(tmp_path))
    allowed = {"read_file", "write_file"}

    written = await execute_tool(
        "write_file", {"path": "notes.md", "content": "P3 笔记"}, allowed
    )
    assert written.status == "completed"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "P3 笔记"

    read = await execute_tool("read_file", {"path": "notes.md"}, allowed)
    assert read.status == "completed"
    assert read.content == "P3 笔记"

    escaped = await execute_tool("read_file", {"path": "../outside.md"}, allowed)
    assert escaped.status == "failed"
    assert "沙箱" in escaped.content

    oversized = await execute_tool(
        "write_file", {"path": "large.md", "content": "中" * 400_000}, allowed
    )
    assert oversized.status == "failed"
    assert not (tmp_path / "large.md").exists()


@pytest.mark.asyncio
async def test_symlink_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_dir", str(tmp_path))
    target = tmp_path / "target.md"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建符号链接")
    result = await execute_tool("read_file", {"path": "link.md"}, {"read_file"})
    assert result.status == "failed"
    assert "符号链接" in result.content


@pytest.mark.asyncio
async def test_tool_whitelist_and_timeout(monkeypatch):
    denied = await execute_tool("get_time", {}, set())
    assert denied.status == "failed"
    assert "白名单" in denied.content

    async def slow(_: dict) -> str:
        await asyncio.sleep(0.1)
        return "late"

    monkeypatch.setitem(
        TOOLS,
        "slow_test",
        Tool("slow_test", "slow", {"type": "object", "properties": {}}, "low", 0.01, slow),
    )
    timed_out = await execute_tool("slow_test", {}, {"slow_test"})
    assert timed_out.status == "timeout"


@pytest.mark.asyncio
async def test_unified_memory_tools_create_revise_list_and_forget():
    with SessionLocal() as session:
        project = Project(name="记忆测试项目")
        session.add(project)
        session.flush()
        conversation = Conversation(title="记忆测试", project_id=project.id)
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id
        project_id = project.id

    token = bind_memory_tool_context("default", conversation_id)
    try:
        created = await execute_tool(
            "memory_create",
            {
                "content": "当前项目统一使用 PostgreSQL",
                "kind": "semantic",
                "scope_type": "project",
                "importance": 4,
            },
            {"memory_create"},
        )
        assert created.status == "completed"
        memory_id = json.loads(created.content)["memory"]["id"]

        listed = await execute_tool("memory_list", {}, {"memory_list"})
        listed_payload = json.loads(listed.content)
        assert listed_payload["count"] == 1
        assert listed_payload["memories"][0]["scope_type"] == "project"
        assert listed_payload["memories"][0]["scope_key"] == project_id

        revised = await execute_tool(
            "memory_update",
            {"memory_id": memory_id, "content": "当前项目统一使用 PostgreSQL 和 pgvector"},
            {"memory_update"},
        )
        assert revised.status == "completed"
        replacement_id = json.loads(revised.content)["memory"]["id"]
        assert replacement_id != memory_id

        forgotten = await execute_tool(
            "memory_forget",
            {"memory_id": replacement_id},
            {"memory_forget"},
        )
        assert forgotten.status == "completed"
        assert json.loads(forgotten.content)["memory"]["is_active"] is False
    finally:
        reset_memory_tool_context(token)

    with SessionLocal() as session:
        old = session.get(Memory, memory_id)
        replacement = session.get(Memory, replacement_id)
        assert old is not None and old.status == "superseded"
        assert replacement is not None and replacement.supersedes_id == memory_id
