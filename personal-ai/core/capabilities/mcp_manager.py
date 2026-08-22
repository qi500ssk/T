"""能力域 MCP Server 配置、连接状态、热重载与持久化管理。"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

import anyio
import yaml

from core.capabilities.mcp import McpClient, McpServerConfig, _parse_server_config, load_mcp_configs


T = TypeVar("T")


def config_to_document(config: McpServerConfig) -> dict:
    raw: dict = {
        "transport": config.transport,
        "enabled": config.enabled,
        "default_risk_level": config.default_risk_level,
    }
    if config.transport == "stdio":
        raw["command"] = config.command
        raw["args"] = list(config.args)
        if config.env:
            raw["env"] = dict(config.env)
    else:
        raw["url"] = config.url
        if config.headers:
            raw["headers"] = dict(config.headers)
    if config.allowed_tools:
        raw["allowed_tools"] = list(config.allowed_tools)
    if config.tool_risk_levels:
        raw["tool_risk_levels"] = dict(config.tool_risk_levels)
    return raw


def public_config(config: McpServerConfig) -> dict:
    """不向设置页返回环境变量或认证 Header 的值。"""
    return {
        "name": config.name,
        "transport": config.transport,
        "command": config.command,
        "args": list(config.args),
        "url": config.url,
        "enabled": config.enabled,
        "default_risk_level": config.default_risk_level,
        "allowed_tools": list(config.allowed_tools),
        "tool_risk_levels": dict(config.tool_risk_levels),
        "env_keys": sorted(config.env),
        "header_keys": sorted(config.headers),
    }


class McpManager:
    def __init__(
        self,
        config_file: str | Path,
        cwd: str | Path | None = None,
        runtime_enabled: bool = True,
    ):
        self.config_file = Path(config_file)
        self.cwd = Path(cwd or Path.cwd())
        self.runtime_enabled = runtime_enabled
        self._lock = asyncio.Lock()
        self._configs: dict[str, McpServerConfig] = {}
        self._sources: dict[str, str] = {}
        self._clients: dict[str, McpClient] = {}
        self._errors: dict[str, str] = {}
        self._lifecycle_queue: asyncio.Queue | None = None
        self._lifecycle_task: asyncio.Task | None = None

    @property
    def clients(self) -> list[McpClient]:
        return list(self._clients.values())

    async def startup(self) -> None:
        self._ensure_lifecycle_worker()
        async with self._lock:
            configs = {item.name: item for item in load_mcp_configs(self.config_file)}
            self._configs = configs
            self._sources = {name: "user" for name in configs}
            for config in configs.values():
                if config.enabled:
                    await self._connect(config)

    async def shutdown(self) -> None:
        async with self._lock:
            for name in list(reversed(self._clients)):
                await self._disconnect(name)
        await self._stop_lifecycle_worker()

    async def refresh_user_configs(self) -> None:
        async with self._lock:
            new_configs = {item.name: item for item in load_mcp_configs(self.config_file)}
            user_names = {name for name, source in self._sources.items() if source == "user"}
            for name in user_names:
                await self._disconnect(name)
                self._configs.pop(name, None)
                self._sources.pop(name, None)
                self._errors.pop(name, None)
            for name, config in new_configs.items():
                if name in self._configs:
                    self._errors[name] = "名称与插件提供的 MCP Server 冲突"
                    continue
                self._configs[name] = config
                self._sources[name] = "user"
                if config.enabled:
                    await self._connect(config)

    async def upsert_user(self, name: str, raw: dict) -> McpServerConfig:
        config = _parse_server_config(name, raw)
        async with self._lock:
            source = self._sources.get(name)
            if source and source != "user":
                raise ValueError("名称已被插件提供的 MCP Server 使用")
            existing = self._configs.get(name)
            # 设置页不会回显密钥；编辑时留空即保留原认证信息。
            if existing is not None and source == "user":
                config = replace(
                    config,
                    env=config.env or existing.env,
                    headers=config.headers or existing.headers,
                )
            await self._disconnect(name)
            self._configs[name] = config
            self._sources[name] = "user"
            self._errors.pop(name, None)
            await self._save_user_configs()
            if config.enabled:
                await self._connect(config)
        return config

    async def set_enabled(self, name: str, enabled: bool) -> McpServerConfig:
        async with self._lock:
            config = self._configs.get(name)
            if config is None:
                raise KeyError(name)
            if self._sources.get(name) != "user":
                raise ValueError("插件提供的 MCP Server 请通过插件开关管理")
            await self._disconnect(name)
            config = replace(config, enabled=enabled)
            self._configs[name] = config
            self._errors.pop(name, None)
            await self._save_user_configs()
            if enabled:
                await self._connect(config)
            return config

    async def remove_user(self, name: str) -> None:
        async with self._lock:
            if name not in self._configs:
                raise KeyError(name)
            if self._sources.get(name) != "user":
                raise ValueError("插件提供的 MCP Server 不能在此删除")
            await self._disconnect(name)
            self._configs.pop(name, None)
            self._sources.pop(name, None)
            self._errors.pop(name, None)
            await self._save_user_configs()

    async def test_config(self, name: str, raw: dict) -> dict:
        config = replace(_parse_server_config(name, raw), enabled=False)
        client = McpClient(config, cwd=self.cwd)
        try:
            await client.connect()
            return {
                "ok": True,
                "server_info": client.server_info,
                "tools": [
                    {
                        "name": str(tool.name),
                        "description": str(tool.description or ""),
                    }
                    for tool in await client.list_tools()
                ],
            }
        finally:
            await client.close()

    async def replace_external(
        self, source: str, configs: list[McpServerConfig]
    ) -> None:
        """替换一个插件贡献的临时配置，不写入用户 YAML。"""
        async with self._lock:
            old_names = {name for name, item_source in self._sources.items() if item_source == source}
            for name in old_names:
                await self._disconnect(name)
                self._configs.pop(name, None)
                self._sources.pop(name, None)
                self._errors.pop(name, None)
            for config in configs:
                if config.name in self._configs:
                    self._errors[config.name] = f"{source} 与已有 MCP Server 名称冲突"
                    continue
                self._configs[config.name] = config
                self._sources[config.name] = source
                if config.enabled:
                    await self._connect(config)

    def list_status(self) -> list[dict]:
        rows: list[dict] = []
        for name in sorted(self._configs):
            config = self._configs[name]
            client = self._clients.get(name)
            rows.append(
                {
                    **public_config(config),
                    "source": self._sources.get(name, "user"),
                    "connected": client is not None,
                    "status": (
                        "connected" if client else "error" if self._errors.get(name) else "disabled"
                    ),
                    "error": self._errors.get(name),
                    "server_info": client.server_info if client else None,
                    "tools": sorted(client.registered_names) if client else [],
                }
            )
        return rows

    async def _connect(self, config: McpServerConfig) -> None:
        await self._run_lifecycle(lambda: self._connect_direct(config))

    async def _connect_direct(self, config: McpServerConfig) -> None:
        if not self.runtime_enabled:
            self._errors[config.name] = "MCP 功能已被全局配置关闭"
            return
        client = McpClient(config, cwd=self.cwd)
        try:
            await client.connect()
            client.register_tools()
            self._clients[config.name] = client
            self._errors.pop(config.name, None)
        except Exception as exc:
            self._errors[config.name] = str(exc)
            await client.close()

    async def _disconnect(self, name: str) -> None:
        await self._run_lifecycle(lambda: self._disconnect_direct(name))

    async def _disconnect_direct(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client is not None:
            await client.close()

    def _ensure_lifecycle_worker(self) -> None:
        if self._lifecycle_task is not None and not self._lifecycle_task.done():
            return
        self._lifecycle_queue = asyncio.Queue()
        self._lifecycle_task = asyncio.create_task(
            self._lifecycle_worker(), name="mcp-lifecycle"
        )

    async def _run_lifecycle(self, action: Callable[[], Awaitable[T]]) -> T:
        self._ensure_lifecycle_worker()
        if asyncio.current_task() is self._lifecycle_task:
            return await action()
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        assert self._lifecycle_queue is not None
        await self._lifecycle_queue.put((action, result))
        return await result

    async def _lifecycle_worker(self) -> None:
        assert self._lifecycle_queue is not None
        while True:
            action, result = await self._lifecycle_queue.get()
            if action is None:
                if not result.done():
                    result.set_result(None)
                return
            try:
                value = await action()
            except BaseException as exc:
                if not result.done():
                    result.set_exception(exc)
            else:
                if not result.done():
                    result.set_result(value)

    async def _stop_lifecycle_worker(self) -> None:
        task = self._lifecycle_task
        queue = self._lifecycle_queue
        if task is None or queue is None:
            return
        loop = asyncio.get_running_loop()
        result = loop.create_future()
        await queue.put((None, result))
        await result
        await task
        self._lifecycle_task = None
        self._lifecycle_queue = None

    async def _save_user_configs(self) -> None:
        document = {
            "mcp_servers": {
                name: config_to_document(config)
                for name, config in sorted(self._configs.items())
                if self._sources.get(name) == "user"
            }
        }

        def _write() -> None:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.config_file.parent,
                prefix=".mcp-",
                suffix=".yaml",
                delete=False,
            ) as handle:
                handle.write(text)
                temporary = Path(handle.name)
            temporary.replace(self.config_file)

        await anyio.to_thread.run_sync(_write)
