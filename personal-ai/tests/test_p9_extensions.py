from pathlib import Path

import pytest

from core.capabilities.mcp_manager import McpManager
from core.capabilities.plugins import PluginError, PluginManager
from core.capabilities.skill_registry import SkillRegistry
from core.capabilities.skills import parse_skill_document
from core.execution.tools import TOOLS


@pytest.mark.asyncio
async def test_mcp_manager_persists_disabled_config_and_masks_secrets(tmp_path):
    config_file = tmp_path / "mcp.yaml"
    manager = McpManager(config_file, cwd=Path.cwd(), runtime_enabled=False)
    await manager.startup()
    await manager.upsert_user(
        "notes",
        {
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "scripts.mcp_demo_server"],
            "env": {"TOKEN": "secret"},
            "enabled": False,
        },
    )
    rows = manager.list_status()
    assert rows[0]["name"] == "notes"
    assert rows[0]["env_keys"] == ["TOKEN"]
    assert "secret" not in str(rows[0])

    reloaded = McpManager(config_file, cwd=Path.cwd(), runtime_enabled=False)
    await reloaded.startup()
    assert reloaded.list_status()[0]["enabled"] is False


@pytest.mark.asyncio
async def test_mcp_manager_hot_toggle_registers_and_removes_tools(tmp_path):
    config_file = tmp_path / "mcp.yaml"
    manager = McpManager(config_file, cwd=Path.cwd())
    await manager.startup()
    await manager.upsert_user(
        "p9demo",
        {
            "command": "python",
            "args": ["-m", "scripts.mcp_demo_server"],
            "enabled": True,
            "allowed_tools": ["echo"],
            "default_risk_level": "low",
        },
    )
    try:
        assert manager.list_status()[0]["status"] == "connected"
        assert "mcp_p9demo_echo" in TOOLS
        await manager.set_enabled("p9demo", False)
        assert "mcp_p9demo_echo" not in TOOLS
    finally:
        await manager.shutdown()


def _plugin_entries() -> list[tuple[str, bytes]]:
    return [
        (
            "hello-plugin/plugin.yaml",
            b"id: hello-plugin\nname: Hello\ndescription: Demo plugin\nversion: 1.0.0\nenabled: true\n",
        ),
        (
            "hello-plugin/skills/hello/SKILL.md",
            b"---\nname: hello\ndescription: Say hello\nrequired_tools: []\nenabled: true\n---\nSay hello clearly.\n",
        ),
    ]


@pytest.mark.asyncio
async def test_plugin_import_defaults_off_then_hot_enables_skill(tmp_path):
    mcp = McpManager(tmp_path / "mcp.yaml", runtime_enabled=False)
    await mcp.startup()
    registry = SkillRegistry()
    plugins = PluginManager(registry, mcp, tmp_path / "plugins", tmp_path / "trash")
    installed = await plugins.install_folder(_plugin_entries())
    assert installed["enabled"] is False
    assert registry.snapshot().records == ()

    enabled = await plugins.set_enabled("hello-plugin", True)
    assert enabled["status"] == "enabled"
    assert [item.id for item in registry.snapshot().records] == ["hello"]

    destination = await plugins.remove("hello-plugin")
    assert destination.is_dir()
    assert registry.snapshot().records == ()


@pytest.mark.asyncio
async def test_plugin_import_rejects_executable_code(tmp_path):
    mcp = McpManager(tmp_path / "mcp.yaml", runtime_enabled=False)
    await mcp.startup()
    plugins = PluginManager(SkillRegistry(), mcp, tmp_path / "plugins", tmp_path / "trash")
    entries = _plugin_entries() + [("hello-plugin/run.py", b"print('unsafe')")]
    with pytest.raises(PluginError, match="不允许"):
        await plugins.install_folder(entries)


@pytest.mark.asyncio
async def test_plugin_required_secret_is_masked_and_blocks_enable(tmp_path):
    plugin_root = tmp_path / "plugins" / "search-plugin"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.yaml").write_text(
        """id: search-plugin
name: Search
description: Search the web
version: 1.0.0
enabled: false
settings:
  - key: api_key
    label: API Key
    type: secret
    required: true
""",
        encoding="utf-8",
    )
    configured: dict[str, str] = {}
    mcp = McpManager(tmp_path / "mcp.yaml", runtime_enabled=False)
    await mcp.startup()
    plugins = PluginManager(
        SkillRegistry(),
        mcp,
        tmp_path / "plugins",
        tmp_path / "trash",
        settings_provider=lambda plugin_id: configured if plugin_id == "search-plugin" else {},
    )
    await plugins.refresh()
    public = plugins.get("search-plugin")
    assert public["config_ready"] is False
    assert public["settings"][0]["configured"] is False
    with pytest.raises(PluginError, match="请先配置"):
        await plugins.set_enabled("search-plugin", True)

    configured["api_key"] = "super-secret"
    await plugins.refresh()
    public = plugins.get("search-plugin")
    assert public["config_ready"] is True
    assert public["settings"][0]["configured"] is True
    assert "super-secret" not in str(public)


def test_web_search_has_moved_to_dedicated_settings(client):
    assert all(item['id'] != 'web-search' for item in client.get('/api/plugins').json())
    assert client.get('/api/settings/web-search').json()['enabled'] is False


def test_p9_management_routes_are_available(client):
    mcp_response = client.get("/api/mcp-servers")
    assert mcp_response.status_code == 200
    assert isinstance(mcp_response.json(), list)
    plugin_response = client.get("/api/plugins")
    assert plugin_response.status_code == 200
    assert isinstance(plugin_response.json(), list)
