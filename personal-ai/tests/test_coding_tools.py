import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from core.capabilities.registry import build_capability_registry
from core.capabilities.skills import parse_skill_document
from core.chat.gateway import MockProvider
from core.execution.coding_tools import CHECKS
from core.execution.workspace import bind_coding_workspace, reset_coding_workspace
from core.execution.tools import TOOLS, execute_tool
from infrastructure.config import settings


READ_TOOLS = {"code_list_files", "code_search", "code_read", "code_git_diff"}
WRITE_TOOLS = {"code_create_file", "code_edit", "code_run_check"}


@pytest.mark.asyncio
async def test_coding_read_list_search_and_secret_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "coding_workspace_dir", str(tmp_path))
    source = tmp_path / "src"
    source.mkdir()
    (source / "main.py").write_text("first = 1\nanswer = 42\nlast = 3\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=hidden", encoding="utf-8")
    dependencies = tmp_path / "node_modules" / "package"
    dependencies.mkdir(parents=True)
    (dependencies / "index.js").write_text("answer = 42", encoding="utf-8")

    listing = await execute_tool("code_list_files", {"path": "."}, READ_TOOLS)
    assert listing.status == "completed"
    assert "src/main.py" in listing.content
    assert ".env" not in listing.content
    assert "node_modules" not in listing.content

    search = await execute_tool(
        "code_search", {"query": "answer", "path": "src"}, READ_TOOLS
    )
    assert search.status == "completed"
    assert "src/main.py:2: answer = 42" in search.content

    read = await execute_tool(
        "code_read", {"path": "src/main.py", "start_line": 2, "end_line": 3}, READ_TOOLS
    )
    assert read.status == "completed"
    assert "lines 2-3 / 3" in read.content
    assert "answer = 42" in read.content
    assert "first = 1" not in read.content

    escaped = await execute_tool("code_read", {"path": "../secret.txt"}, READ_TOOLS)
    secret = await execute_tool("code_read", {"path": ".env"}, READ_TOOLS)
    assert escaped.status == "failed" and "工作区" in escaped.content
    assert secret.status == "failed" and "密钥" in secret.content


@pytest.mark.asyncio
async def test_coding_create_and_exact_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "coding_workspace_dir", str(tmp_path))
    allowed = WRITE_TOOLS | {"code_read"}

    created = await execute_tool(
        "code_create_file",
        {"path": "app/main.py", "content": "value = 1\n"},
        allowed,
    )
    assert created.status == "completed"
    assert (tmp_path / "app" / "main.py").read_text(encoding="utf-8") == "value = 1\n"

    duplicate = await execute_tool(
        "code_create_file", {"path": "app/main.py", "content": "overwrite"}, allowed
    )
    assert duplicate.status == "failed"
    assert "已存在" in duplicate.content

    edited = await execute_tool(
        "code_edit",
        {"path": "app/main.py", "old_text": "value = 1", "new_text": "value = 2"},
        allowed,
    )
    assert edited.status == "completed"
    assert (tmp_path / "app" / "main.py").read_text(encoding="utf-8") == "value = 2\n"

    ambiguous_path = tmp_path / "app" / "repeated.py"
    ambiguous_path.write_text("same\nsame\n", encoding="utf-8")
    ambiguous = await execute_tool(
        "code_edit",
        {"path": "app/repeated.py", "old_text": "same", "new_text": "changed"},
        allowed,
    )
    assert ambiguous.status == "failed"
    assert "匹配 2 次" in ambiguous.content

    secret = await execute_tool(
        "code_create_file", {"path": ".env.local", "content": "TOKEN=x"}, allowed
    )
    assert secret.status == "failed"
    assert not (tmp_path / ".env.local").exists()


@pytest.mark.asyncio
async def test_coding_git_diff_is_read_only(tmp_path, monkeypatch):
    git = shutil.which("git")
    if not git:
        pytest.skip("系统未安装 Git")
    monkeypatch.setattr(settings, "coding_workspace_dir", str(tmp_path))
    subprocess.run([git, "init"], cwd=tmp_path, check=True, capture_output=True)
    path = tmp_path / "app.py"
    path.write_text("value = 1\n", encoding="utf-8")
    subprocess.run([git, "add", "app.py"], cwd=tmp_path, check=True, capture_output=True)
    path.write_text("value = 2\n", encoding="utf-8")

    result = await execute_tool("code_git_diff", {}, READ_TOOLS)
    assert result.status == "completed"
    assert "app.py" in result.content
    assert "+value = 2" in result.content
    assert "-value = 1" in result.content


@pytest.mark.asyncio
async def test_coding_runs_only_predefined_check(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "coding_workspace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "coding_check_timeout_seconds", 30)
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8"
    )
    result = await execute_tool(
        "code_run_check", {"check": "pytest", "path": "."}, WRITE_TOOLS
    )
    assert result.status == "completed"
    assert "exit_code=0" in result.content

    denied = await execute_tool(
        "code_run_check", {"check": "shell", "path": "."}, WRITE_TOOLS
    )
    assert denied.status == "failed"
    assert "允许范围" in denied.content


def test_developer_plugin_skill_and_tool_risks():
    skill_path = Path("plugins/developer-tools/skills/coding-helper/SKILL.md")
    record = parse_skill_document(
        "coding-helper", skill_path.read_text(encoding="utf-8")
    )
    assert record.available is True
    assert set(record.required_tools) == READ_TOOLS | WRITE_TOOLS
    assert set(CHECKS) == {
        "pytest", "python-compile", "npm-test", "npm-lint", "npm-build", "npm-typecheck"
    }
    assert all(TOOLS[name].risk_level == "medium" for name in READ_TOOLS)
    assert all(TOOLS[name].risk_level == "high" for name in WRITE_TOOLS)

    disabled_registry = build_capability_registry([], [])
    disabled = {
        item["name"]: item["enabled"]
        for item in disabled_registry
        if item["kind"] == "tool" and item["name"] in READ_TOOLS | WRITE_TOOLS
    }
    assert disabled == {name: False for name in READ_TOOLS | WRITE_TOOLS}

    enabled_registry = build_capability_registry([record], [])
    enabled = {
        item["name"]: item["enabled"]
        for item in enabled_registry
        if item["kind"] == "tool" and item["name"] in READ_TOOLS | WRITE_TOOLS
    }
    assert enabled == {name: True for name in READ_TOOLS | WRITE_TOOLS}


def test_mock_provider_can_drive_basic_coding_tools():
    available = READ_TOOLS | WRITE_TOOLS
    assert MockProvider._select_tool("查看项目文件", available) == (
        "code_list_files", {"path": "."}
    )
    assert MockProvider._select_tool("读取代码：src/app.py", available) == (
        "code_read", {"path": "src/app.py"}
    )
    assert MockProvider._select_tool("搜索代码：build_context", available) == (
        "code_search", {"query": "build_context"}
    )
    assert MockProvider._select_tool(
        "创建代码文件：hello.py 内容：print('hello')", available
    ) == (
        "code_create_file", {"path": "hello.py", "content": "print('hello')"}
    )
    assert MockProvider._select_tool("运行代码检查：pytest", available) == (
        "code_run_check", {"check": "pytest"}
    )


@pytest.mark.asyncio
async def test_coding_workspace_is_isolated_per_run(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "only-first.txt").write_text("first", encoding="utf-8")
    (second / "only-second.txt").write_text("second", encoding="utf-8")

    async def listing(root: Path) -> str:
        token = bind_coding_workspace(str(root))
        try:
            result = await execute_tool("code_list_files", {"path": "."}, READ_TOOLS)
            assert result.status == "completed"
            return result.content
        finally:
            reset_coding_workspace(token)

    first_result, second_result = await asyncio.gather(listing(first), listing(second))
    assert "only-first.txt" in first_result and "only-second.txt" not in first_result
    assert "only-second.txt" in second_result and "only-first.txt" not in second_result


@pytest.mark.asyncio
async def test_coding_tools_require_a_folder_inside_run_context():
    token = bind_coding_workspace(None)
    try:
        result = await execute_tool("code_list_files", {"path": "."}, READ_TOOLS)
    finally:
        reset_coding_workspace(token)
    assert result.status == "failed"
    assert "未选择文件夹" in result.content
