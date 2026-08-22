"""能力域 MCP Client：stdio/HTTP 连接、发现、调用与 Tool 适配。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path

import yaml
import httpx
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from core.execution.tools import TOOLS, Tool
from infrastructure.config import settings


logger = logging.getLogger(__name__)
VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")
VALID_MODEL_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
VALID_RISKS = {"low", "medium", "high"}
VALID_TRANSPORTS = {"stdio", "streamable_http"}
UNSUPPORTED_CONTENT_MESSAGES = {
    "image": "工具返回了图片，P4 暂不展示",
    "audio": "工具返回了音频，P4 暂不播放",
    "resource": "工具返回了资源，P4 暂不展开",
    "resource_link": "工具返回了资源链接，P4 暂不展开",
}


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    default_risk_level: str = "high"
    allowed_tools: tuple[str, ...] = ()
    tool_risk_levels: dict[str, str] = field(default_factory=dict)


def load_mcp_configs(path: str | Path) -> list[McpServerConfig]:
    config_path = Path(path)
    if not config_path.exists():
        logger.warning("MCP 配置文件不存在，跳过加载：%s", config_path)
        return []
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        logger.error("MCP 配置文件读取失败，跳过加载：%s", exc)
        return []
    servers = document.get("mcp_servers", {})
    if not isinstance(servers, dict):
        logger.error("MCP 配置 mcp_servers 必须是对象")
        return []

    configs: list[McpServerConfig] = []
    for name, raw in servers.items():
        try:
            configs.append(_parse_server_config(str(name), raw))
        except (TypeError, ValueError) as exc:
            logger.error("跳过无效 MCP Server %s：%s", name, exc)
    return configs


def _parse_server_config(name: str, raw: object) -> McpServerConfig:
    if not VALID_NAME.fullmatch(name):
        raise ValueError("Server 名只能包含字母、数字、下划线和连字符")
    if not isinstance(raw, dict):
        raise TypeError("Server 配置必须是对象")
    transport = str(raw.get("transport", "stdio")).strip().lower()
    if transport not in VALID_TRANSPORTS:
        raise ValueError("transport 必须是 stdio 或 streamable_http")
    command = raw.get("command", "")
    url = raw.get("url", "")
    if transport == "stdio" and (not isinstance(command, str) or not command.strip()):
        raise ValueError("stdio Server 的 command 必须是非空字符串")
    if transport == "streamable_http":
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Streamable HTTP Server 的 url 必须是非空字符串")
        if not re.fullmatch(r"https?://[^\s]+", url.strip()):
            raise ValueError("MCP URL 必须使用 http 或 https")
    args = _string_tuple(raw.get("args", ()), "args")
    allowed_tools = _string_tuple(raw.get("allowed_tools", ()), "allowed_tools")
    for tool_name in allowed_tools:
        _validate_remote_name(tool_name)
        _model_tool_name(name, tool_name)

    default_risk = str(raw.get("default_risk_level", "high"))
    if default_risk not in VALID_RISKS:
        raise ValueError("default_risk_level 必须是 low、medium 或 high")
    raw_risks = raw.get("tool_risk_levels", {}) or {}
    if not isinstance(raw_risks, dict):
        raise TypeError("tool_risk_levels 必须是对象")
    risks: dict[str, str] = {}
    for tool_name, risk in raw_risks.items():
        remote_name = str(tool_name)
        _validate_remote_name(remote_name)
        if risk not in VALID_RISKS:
            raise ValueError(f"工具 {remote_name} 的风险等级无效")
        risks[remote_name] = str(risk)

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise TypeError("enabled 必须是布尔值")
    env = _string_map(raw.get("env", {}), "env")
    headers = _string_map(raw.get("headers", {}), "headers")
    return McpServerConfig(
        name=name,
        transport=transport,
        command=command.strip() if isinstance(command, str) else "",
        args=args,
        url=url.strip() if isinstance(url, str) else "",
        env=env,
        headers=headers,
        enabled=enabled,
        default_risk_level=default_risk,
        allowed_tools=allowed_tools,
        tool_risk_levels=risks,
    )


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{field_name} 必须是字符串列表")
    return tuple(value)


def _string_map(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise TypeError(f"{field_name} 必须是字符串键值对象")
    return {key: item for key, item in value.items()}


def _safe_subprocess_env(extra: dict[str, str]) -> dict[str, str]:
    """只继承启动进程所需的系统变量，不把模型/API 密钥泄露给 MCP。"""
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME",
        "LANG", "LC_ALL",
    }
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(extra)
    return result


def _validate_remote_name(name: str) -> None:
    if not VALID_NAME.fullmatch(name):
        raise ValueError(f"MCP 工具名不合法：{name}")


def _model_tool_name(server_name: str, remote_name: str) -> str:
    name = f"mcp_{server_name}_{remote_name}"
    if not VALID_MODEL_TOOL_NAME.fullmatch(name):
        raise ValueError(f"模型工具名不合法或超过 64 字符：{name}")
    return name


def mcp_result_to_text(result: CallToolResult) -> str:
    if result.isError:
        details = "\n".join(
            item.text for item in result.content if isinstance(item, TextContent)
        ).strip()
        raise ValueError(details or "MCP 工具返回错误")

    parts: list[str] = []
    for item in result.content:
        if isinstance(item, TextContent):
            if item.text:
                parts.append(item.text)
            continue
        message = UNSUPPORTED_CONTENT_MESSAGES.get(item.type)
        if message and message not in parts:
            parts.append(message)
    if result.structuredContent is not None:
        structured = json.dumps(result.structuredContent, ensure_ascii=False, sort_keys=True)
        if structured not in parts:
            parts.append(structured)
    return "\n".join(parts) or "工具执行成功，但没有文本结果"


def _is_expected_transport_close_error(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return all(_is_expected_transport_close_error(item) for item in exc.exceptions)
    return isinstance(
        exc,
        (anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream),
    )


class McpClient:
    def __init__(self, config: McpServerConfig, cwd: str | Path | None = None):
        self.config = config
        self.cwd = Path(cwd or Path.cwd())
        self.remote_tools: list = []
        self.registered_names: set[str] = set()
        self._registered_tools: dict[str, Tool] = {}
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self.server_info: dict | None = None
        self.session_id: str | None = None

    async def connect(self, timeout: float | None = None) -> None:
        if self._stack is not None:
            raise RuntimeError("MCP Client 已连接")
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(timeout or settings.tool_timeout_seconds):
                if self.config.transport == "stdio":
                    command = (
                        sys.executable
                        if self.config.command.lower() in {"python", "python3", "py"}
                        else self.config.command
                    )
                    params = StdioServerParameters(
                        command=command,
                        args=list(self.config.args),
                        env=_safe_subprocess_env(self.config.env),
                        cwd=self.cwd,
                        encoding="utf-8",
                        encoding_error_handler="replace",
                    )
                    read_stream, write_stream = await stack.enter_async_context(
                        stdio_client(params)
                    )
                else:
                    http_client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=self.config.headers,
                            timeout=settings.tool_timeout_seconds,
                            follow_redirects=False,
                        )
                    )
                    read_stream, write_stream, get_session_id = await stack.enter_async_context(
                        streamable_http_client(self.config.url, http_client=http_client)
                    )
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                initialized = await session.initialize()
                listed = await session.list_tools()
            self._stack = stack
            self._session = session
            self.remote_tools = list(listed.tools)
            self.server_info = initialized.serverInfo.model_dump(mode="json")
            if self.config.transport == "streamable_http":
                self.session_id = get_session_id()
        except BaseException:
            await stack.aclose()
            raise

    async def list_tools(self) -> list:
        if self._session is None:
            raise RuntimeError("MCP Client 未连接")
        return list(self.remote_tools)

    async def call_tool(self, remote_name: str, args: dict) -> str:
        if self._session is None:
            raise ValueError("MCP Server 未连接")
        try:
            result = await self._session.call_tool(remote_name, args)
            return mcp_result_to_text(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ValueError(f"MCP 工具调用失败：{exc}") from exc

    def register_tools(self) -> set[str]:
        allowed = set(self.config.allowed_tools)
        for remote_tool in self.remote_tools:
            remote_name = str(remote_tool.name)
            if allowed and remote_name not in allowed:
                continue
            try:
                _validate_remote_name(remote_name)
                model_name = _model_tool_name(self.config.name, remote_name)
            except ValueError as exc:
                logger.error("跳过 MCP 工具 %s.%s：%s", self.config.name, remote_name, exc)
                continue
            if model_name in TOOLS:
                logger.error("MCP 工具注册冲突，未覆盖现有工具：%s", model_name)
                continue
            risk = self.config.tool_risk_levels.get(
                remote_name, self.config.default_risk_level
            )

            async def runner(args: dict, name: str = remote_name) -> str:
                return await self.call_tool(name, args)

            schema = remote_tool.inputSchema or {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
            adapter = Tool(
                name=model_name,
                description=f"{remote_tool.description or remote_name}（来自 MCP Server {self.config.name}）",
                input_schema=schema,
                risk_level=risk,
                timeout=settings.tool_timeout_seconds,
                runner=runner,
            )
            TOOLS[model_name] = adapter
            self.registered_names.add(model_name)
            self._registered_tools[model_name] = adapter
        return set(self.registered_names)

    def unregister_tools(self) -> None:
        for name in self.registered_names:
            # 热重载时只移除自己注册的适配器，避免误删同名的新连接工具。
            if TOOLS.get(name) is self._registered_tools.get(name):
                TOOLS.pop(name, None)
        self.registered_names.clear()
        self._registered_tools.clear()

    async def close(self) -> None:
        self.unregister_tools()
        stack, self._stack = self._stack, None
        self._session = None
        self.remote_tools = []
        self.server_info = None
        self.session_id = None
        if stack is not None:
            try:
                await stack.aclose()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                if not _is_expected_transport_close_error(exc):
                    raise
                logger.debug("MCP 传输已先于客户端关闭：%s", self.config.name)


async def connect_mcp_servers(
    configs: list[McpServerConfig], cwd: str | Path | None = None
) -> list[McpClient]:
    clients: list[McpClient] = []
    for config in configs:
        if not config.enabled:
            continue
        client = McpClient(config, cwd=cwd)
        try:
            await client.connect()
            client.register_tools()
            clients.append(client)
            logger.info(
                "MCP Server 已连接：%s，注册工具 %s 个",
                config.name,
                len(client.registered_names),
            )
        except Exception as exc:
            logger.error("MCP Server %s 连接失败，已跳过：%s", config.name, exc)
            try:
                await client.close()
            except Exception:
                logger.warning("MCP Server %s 失败后的清理未完成", config.name, exc_info=True)
    return clients


async def close_mcp_servers(clients: list[McpClient]) -> None:
    for client in reversed(clients):
        try:
            await client.close()
        except Exception:
            logger.warning("关闭 MCP Server %s 失败", client.config.name, exc_info=True)
