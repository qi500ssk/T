"""MCP Manager API：配置、连通性测试、启停与热刷新。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from apps.api.skills import refresh_skill_runtime


router = APIRouter(prefix="/api/mcp-servers", tags=["mcp-servers"])


class McpServerBody(BaseModel):
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    transport: Literal["stdio", "streamable_http"] = "stdio"
    command: str = Field(default="", max_length=500)
    args: list[str] = Field(default_factory=list, max_length=50)
    url: str = Field(default="", max_length=2000)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = False
    default_risk_level: Literal["low", "medium", "high"] = "high"
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    tool_risk_levels: dict[str, Literal["low", "medium", "high"]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_transport_fields(self):
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("stdio Server 必须填写 command")
        if self.transport == "streamable_http" and not self.url.strip():
            raise ValueError("Streamable HTTP Server 必须填写 URL")
        return self

    def manager_document(self) -> dict:
        return self.model_dump(exclude={"name"})


class McpToggleBody(BaseModel):
    enabled: bool


def _manager(request: Request):
    manager = getattr(request.app.state, "mcp_manager", None)
    if manager is None:
        raise HTTPException(503, "MCP Manager 尚未初始化")
    return manager


def _sync_runtime(request: Request) -> None:
    manager = _manager(request)
    request.app.state.mcp_clients = manager.clients
    refresh_skill_runtime(request.app)


def _find_status(manager, name: str) -> dict:
    return next(item for item in manager.list_status() if item["name"] == name)


@router.get("")
def list_mcp_servers(request: Request):
    return _manager(request).list_status()


@router.post("/test")
async def test_mcp_server(body: McpServerBody, request: Request):
    try:
        return await _manager(request).test_config(body.name, body.manager_document())
    except Exception as exc:
        raise HTTPException(422, f"连接测试失败：{exc}") from exc


@router.post("")
async def save_mcp_server(body: McpServerBody, request: Request):
    manager = _manager(request)
    try:
        await manager.upsert_user(body.name, body.manager_document())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (TypeError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    _sync_runtime(request)
    return _find_status(manager, body.name)


@router.patch("/{name}")
async def toggle_mcp_server(name: str, body: McpToggleBody, request: Request):
    manager = _manager(request)
    try:
        await manager.set_enabled(name, body.enabled)
    except KeyError:
        raise HTTPException(404, "MCP Server 不存在") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _sync_runtime(request)
    return _find_status(manager, name)


@router.delete("/{name}")
async def delete_mcp_server(name: str, request: Request):
    manager = _manager(request)
    try:
        await manager.remove_user(name)
    except KeyError:
        raise HTTPException(404, "MCP Server 不存在") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    _sync_runtime(request)
    return {"ok": True}


@router.post("/refresh")
async def refresh_mcp_servers(request: Request):
    manager = _manager(request)
    await manager.refresh_user_configs()
    _sync_runtime(request)
    return manager.list_status()
