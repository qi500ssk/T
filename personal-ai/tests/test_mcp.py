import asyncio
import json
from pathlib import Path

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

from core.chat.agent import run_chat
from core.chat.gateway import StreamChunk
from core.capabilities.mcp import (
    McpServerConfig,
    McpClient,
    _model_tool_name,
    close_mcp_servers,
    connect_mcp_servers,
    load_mcp_configs,
    mcp_result_to_text,
)
from core.execution.permissions import resolve_approval
from core.capabilities.skills import allowed_tool_names, load_skills
from core.execution.tools import TOOLS, Tool, execute_tool
from infrastructure.config import settings
from infrastructure.database import Conversation, SessionLocal, ToolRun


def test_config_parse_and_invalid_server_is_skipped(tmp_path):
    config = tmp_path / "servers.yaml"
    config.write_text(
        """
mcp_servers:
  demo:
    command: python
    args: [\"-m\", \"scripts.mcp_demo_server\"]
    default_risk_level: high
    allowed_tools: [echo]
    tool_risk_levels: {echo: low}
  bad.name:
    command: python
""",
        encoding="utf-8",
    )
    configs = load_mcp_configs(config)
    assert len(configs) == 1
    assert configs[0].name == "demo"
    assert configs[0].allowed_tools == ("echo",)
    assert configs[0].tool_risk_levels == {"echo": "low"}


def test_missing_config_is_non_fatal(tmp_path):
    assert load_mcp_configs(tmp_path / "missing.yaml") == []


def test_model_tool_name_is_valid():
    assert _model_tool_name("demo", "echo") == "mcp_demo_echo"
    with pytest.raises(ValueError):
        _model_tool_name("a" * 60, "echo")


def test_result_text_blocks_are_joined_and_structured_serialized():
    result = CallToolResult(
        content=[
            TextContent(type="text", text="first"),
            TextContent(type="text", text="second"),
        ],
        structuredContent={"ok": True},
    )
    text = mcp_result_to_text(result)
    assert "first\nsecond" in text
    assert json.loads(text.splitlines()[-1]) == {"ok": True}

    image_result = CallToolResult(
        content=[ImageContent(type="image", data="abc", mimeType="image/png")]
    )
    assert "图片" in mcp_result_to_text(image_result)


def test_mcp_error_becomes_failed_tool_result():
    result = CallToolResult(
        content=[TextContent(type="text", text="remote failure")], isError=True
    )
    with pytest.raises(ValueError, match="remote failure"):
        mcp_result_to_text(result)


@pytest.mark.asyncio
async def test_demo_server_connect_list_and_echo(tmp_path):
    configs = load_mcp_configs("config/mcp_servers.yaml")
    client = McpClient(configs[0], cwd=Path.cwd())
    try:
        await client.connect()
        names = {tool.name for tool in await client.list_tools()}
        assert {"echo", "random_number"} <= names
        echo_result = await client.call_tool("echo", {"text": "p4"})
        assert echo_result.startswith("p4")
        value = await client.call_tool("random_number", {"min": 3, "max": 3})
        assert value.startswith("3")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_tool_registration_and_shutdown_cleanup():
    configs = load_mcp_configs("config/mcp_servers.yaml")
    clients = await connect_mcp_servers(configs)
    try:
        assert "mcp_demo_echo" in TOOLS
        assert TOOLS["mcp_demo_echo"].risk_level == "low"
        assert "mcp_demo_random_number" in TOOLS
        allowed = {"mcp_demo_echo"}
        result = await execute_tool("mcp_demo_echo", {"text": "through router"}, allowed)
        assert result.status == "completed"
        assert result.content.startswith("through router")
    finally:
        await close_mcp_servers(clients)
    assert "mcp_demo_echo" not in TOOLS
    assert "mcp_demo_random_number" not in TOOLS


@pytest.mark.asyncio
async def test_connect_failure_does_not_stop_other_servers():
    good = load_mcp_configs("config/mcp_servers.yaml")[0]
    bad = McpServerConfig(name="bad", command="missing-mcp-command-p4")
    clients = await connect_mcp_servers([bad, good])
    try:
        assert [client.config.name for client in clients] == ["demo"]
        assert "mcp_demo_echo" in TOOLS
    finally:
        await close_mcp_servers(clients)


def test_skill_can_still_declare_mcp_tools(tmp_path):
    async def echo_runner(args: dict) -> str:
        return args["text"]

    TOOLS["mcp_demo_echo"] = Tool(
        name="mcp_demo_echo",
        description="demo",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        risk_level="low",
        timeout=1,
        runner=echo_runner,
    )
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "mcp-demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: mcp-demo\ndescription: demo\nrequired_tools: [mcp_demo_echo]\nenabled: true\n---\nUse echo.",
        encoding="utf-8",
    )
    skills = load_skills(skill_root)
    assert "mcp_demo_echo" in allowed_tool_names(skills)
    assert "mcp_demo_random_number" not in allowed_tool_names(skills)
    TOOLS.pop("mcp_demo_echo", None)


@pytest.mark.asyncio
async def test_mcp_call_timeout(monkeypatch):
    class SlowSession:
        async def call_tool(self, name, args):
            await asyncio.sleep(0.1)
            return CallToolResult(content=[TextContent(type="text", text="late")])

    client = McpClient(load_mcp_configs("config/mcp_servers.yaml")[0])
    client._session = SlowSession()
    monkeypatch.setattr(settings, "tool_timeout_seconds", 0.01)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(settings.tool_timeout_seconds):
            await client.call_tool("echo", {"text": "slow"})


class McpToolProvider:
    def __init__(self, tool_name: str, arguments: dict):
        self.tool_name = tool_name
        self.arguments = arguments
        self.round = 0

    async def stream(self, messages, temperature=0.7, tools=None):
        self.round += 1
        if self.round == 1:
            assert any(item["function"]["name"] == self.tool_name for item in tools)
            yield StreamChunk(
                tool_calls_delta=[
                    {
                        "index": 0,
                        "id": "mcp-call-1",
                        "type": "function",
                        "function": {
                            "name": self.tool_name,
                            "arguments": json.dumps(self.arguments),
                        },
                    }
                ],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 3, "completion_tokens": 2},
            )
        else:
            assert messages[-1]["role"] == "tool"
            yield StreamChunk(
                text=f"MCP result: {messages[-1]['content']}",
                finish_reason="stop",
                usage={"prompt_tokens": 3, "completion_tokens": 3},
            )

    async def complete(self, messages, temperature=0.0):
        return ""


@pytest.mark.asyncio
async def test_connected_mcp_tool_is_directly_available_and_uses_approval(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", False)
    clients = await connect_mcp_servers(load_mcp_configs("config/mcp_servers.yaml"))
    try:
        with SessionLocal() as session:
            conversation = Conversation(title="MCP integration")
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id

        events = []
        provider = McpToolProvider(
            "mcp_demo_random_number", {"min": 7, "max": 7}
        )
        async for event in run_chat(
            provider,
            conversation_id,
            "生成 7 到 7 的随机整数",
            skills=[],
            mcp_clients=clients,
        ):
            events.append(event)
            if event.type == "approval.required":
                assert resolve_approval(event.data["approval_id"], True)

        event_types = [event.type for event in events]
        assert event_types.index("approval.completed") < event_types.index("tool.started")
        assert event_types[-2:] == ["message.completed", "run.completed"]
        with SessionLocal() as session:
            tool_run = session.query(ToolRun).one()
            assert tool_run.tool == "mcp_demo_random_number"
            assert tool_run.risk_level == "high"
            assert tool_run.status == "completed"
            assert tool_run.approval_id
            assert tool_run.approved_at is not None
    finally:
        await close_mcp_servers(clients)
