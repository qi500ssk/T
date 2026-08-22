"""能力域只读 Capability Registry。"""

import hashlib
import json

from core.capabilities.skills import Skill, allowed_tool_names
from core.execution.tools import TOOLS


def build_run_capability_snapshot(skills: list[Skill], allowed_tools: set[str]) -> tuple[str, dict]:
    """生成可持久化的 Run 能力快照；正文只保存摘要哈希。"""
    snapshot = {
        "skills": [
            {
                "id": skill.id,
                "name": skill.name,
                "required_tools": list(skill.required_tools),
                "instruction_sha256": hashlib.sha256(
                    skill.instructions.encode("utf-8")
                ).hexdigest(),
            }
            for skill in sorted(skills, key=lambda item: item.id)
        ],
        "tools": sorted(allowed_tools),
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), snapshot


def build_capability_registry(skills: list[Skill], mcp_clients: list) -> list[dict]:
    source_by_tool: dict[str, str] = {}
    active_tools = allowed_tool_names(skills)
    items: list[dict] = []
    for client in mcp_clients:
        source = f"mcp:{client.config.name}"
        for name in client.registered_names:
            source_by_tool[name] = source
        items.append(
            {
                "kind": "mcp_server",
                "name": client.config.name,
                "description": "已连接的 stdio MCP Server",
                "source": source,
                "risk_level": client.config.default_risk_level,
                "required_tools": sorted(client.registered_names),
                "enabled": True,
                "available": True,
            }
        )
    for tool in TOOLS.values():
        items.append(
            {
                "kind": "tool",
                "name": tool.name,
                "description": tool.description,
                "source": source_by_tool.get(tool.name, "native"),
                "risk_level": tool.risk_level,
                "required_tools": [],
                "enabled": tool.name in active_tools,
                "available": True,
            }
        )
    for skill in skills:
        items.append(
            {
                "kind": "skill",
                "name": skill.name,
                "description": skill.description,
                "source": "local",
                "risk_level": None,
                "required_tools": list(skill.required_tools),
                "enabled": True,
                "available": all(name in TOOLS for name in skill.required_tools),
            }
        )
    return sorted(items, key=lambda item: (item["kind"], item["name"]))
