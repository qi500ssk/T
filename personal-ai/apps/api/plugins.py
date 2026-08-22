"""声明式插件管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from apps.api.skills import refresh_skill_runtime
from core.capabilities.plugins import (
    MAX_FILE_BYTES,
    PluginConflictError,
    PluginError,
)


router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginToggleBody(BaseModel):
    enabled: bool


class PluginSettingsBody(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    clear_keys: list[str] = Field(default_factory=list)


def _manager(request: Request):
    manager = getattr(request.app.state, "plugin_manager", None)
    if manager is None:
        raise HTTPException(503, "Plugin Manager 尚未初始化")
    return manager


def _sync_runtime(request: Request) -> None:
    request.app.state.mcp_clients = request.app.state.mcp_manager.clients
    refresh_skill_runtime(request.app)


@router.get("")
def list_plugins(request: Request):
    return _manager(request).list()


@router.post("/refresh")
async def refresh_plugins(request: Request):
    rows = await _manager(request).refresh()
    _sync_runtime(request)
    return rows


@router.post("/import-folder")
async def import_plugin_folder(
    request: Request,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
):
    if len(files) != len(paths):
        raise HTTPException(422, "文件与相对路径数量不一致")
    entries: list[tuple[str, bytes]] = []
    for path, upload in zip(paths, files, strict=True):
        entries.append((path, await upload.read(MAX_FILE_BYTES + 1)))
    try:
        row = await _manager(request).install_folder(entries)
    except PluginConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except PluginError as exc:
        raise HTTPException(422, str(exc)) from exc
    _sync_runtime(request)
    return row


@router.patch("/{plugin_id}")
async def toggle_plugin(plugin_id: str, body: PluginToggleBody, request: Request):
    try:
        row = await _manager(request).set_enabled(plugin_id, body.enabled)
    except KeyError:
        raise HTTPException(404, "插件不存在") from None
    except PluginError as exc:
        raise HTTPException(409, str(exc)) from exc
    _sync_runtime(request)
    return row


@router.patch("/{plugin_id}/settings")
async def update_plugin_settings(
    plugin_id: str,
    body: PluginSettingsBody,
    request: Request,
):
    manager = _manager(request)
    try:
        record = manager.get(plugin_id)
    except KeyError:
        raise HTTPException(404, "插件不存在") from None
    allowed = {item["key"] for item in record["settings"]}
    supplied = set(body.values) | set(body.clear_keys)
    unknown = sorted(supplied - allowed)
    if unknown:
        raise HTTPException(422, f"插件设置不存在：{', '.join(unknown)}")
    if any(len(value) > 2000 for value in body.values.values()):
        raise HTTPException(422, "插件设置值不能超过 2000 个字符")

    store = request.app.state.runtime_settings_store
    all_settings = store.snapshot()["plugin_settings"]
    current = dict(all_settings.get(plugin_id, {}))
    for key, value in body.values.items():
        if value.strip():
            current[key] = value.strip()
    for key in body.clear_keys:
        current.pop(key, None)
    if current:
        all_settings[plugin_id] = current
    else:
        all_settings.pop(plugin_id, None)
    store.update("plugin_settings", all_settings)
    await manager.refresh()
    _sync_runtime(request)
    return manager.get(plugin_id)


@router.delete("/{plugin_id}")
async def delete_plugin(plugin_id: str, request: Request):
    try:
        destination = await _manager(request).remove(plugin_id)
    except KeyError:
        raise HTTPException(404, "插件不存在") from None
    except PluginError as exc:
        raise HTTPException(409, str(exc)) from exc
    store = request.app.state.runtime_settings_store
    all_settings = store.snapshot()["plugin_settings"]
    if plugin_id in all_settings:
        all_settings.pop(plugin_id, None)
        store.update("plugin_settings", all_settings)
    _sync_runtime(request)
    return {"ok": True, "recoverable": True, "trash_name": destination.name}
