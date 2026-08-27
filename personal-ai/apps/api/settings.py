"""常规设置 API：模型、Agent 人格与编码工作区。"""

from __future__ import annotations

import asyncio
import os
import string
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.automation.activity import activity_worker
from core.chat.gateway import build_provider
from core.chat.images import InvalidChatImageError, inspect_image
from core.settings.runtime import resolve_agent_profile
from infrastructure.config import settings
from infrastructure.database import (
    AgentRun,
    Conversation,
    Memory,
    ProjectAgentAccess,
    SessionLocal,
)


router = APIRouter(prefix="/api/settings", tags=["settings"])


class ModelSettingsBody(BaseModel):
    model_id: str | None = Field(default=None, max_length=100)
    provider: Literal["mock", "openai-compatible"]
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False
    timeout_seconds: float = Field(default=60.0, ge=5, le=300)
    context_window_tokens: int = Field(default=12_096, ge=2_048, le=2_000_000)
    max_output_tokens: int = Field(default=4_096, ge=1, le=262_144)


class ModelProfileBody(ModelSettingsBody):
    name: str = Field(min_length=1, max_length=80)


class DefaultModelBody(BaseModel):
    model_id: str = Field(min_length=1, max_length=100)


class AgentSettingsBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=160)
    language: str = Field(min_length=2, max_length=30)
    tone: str = Field(min_length=1, max_length=120)
    verbosity: str = Field(min_length=1, max_length=80)
    humor: str = Field(min_length=1, max_length=80)
    formality: str = Field(min_length=1, max_length=120)
    proactivity: str = Field(min_length=1, max_length=120)
    custom_instructions: str = Field(default="", max_length=12_000)


class AgentProfileBody(AgentSettingsBody):
    profile_name: str = Field(min_length=1, max_length=80)


class ActiveAgentBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=100)


class WorkspaceSettingsBody(BaseModel):
    coding_workspace_dir: str = Field(min_length=1, max_length=1200)


def _store(request: Request):
    store = getattr(request.app.state, "runtime_settings_store", None)
    if store is None:
        raise HTTPException(503, "运行时设置尚未初始化")
    return store


_AVATAR_MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _avatar_root() -> Path:
    root = Path(settings.agent_avatar_storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_agent_id(agent_id: str) -> None:
    allowed = string.ascii_letters + string.digits + "-_"
    if not agent_id or any(character not in allowed for character in agent_id):
        raise HTTPException(404, "角色不存在")


def _avatar_path(agent_id: str) -> Path | None:
    _validate_agent_id(agent_id)
    root = _avatar_root()
    for extension in _AVATAR_MEDIA_TYPES:
        candidate = root / f"{agent_id}{extension}"
        if candidate.is_file():
            return candidate
    return None


def _avatar_url(agent_id: str) -> str | None:
    path = _avatar_path(agent_id)
    if path is None:
        return None
    return f"/api/settings/agents/{agent_id}/avatar?v={path.stat().st_mtime_ns}"


def agent_avatar_url(agent_id: str) -> str | None:
    """供其他 API 序列化角色摘要时复用头像地址。"""
    return _avatar_url(agent_id)


def _delete_avatar(agent_id: str, *, keep: Path | None = None) -> None:
    _validate_agent_id(agent_id)
    root = _avatar_root()
    for extension in _AVATAR_MEDIA_TYPES:
        candidate = root / f"{agent_id}{extension}"
        if keep is None or candidate != keep:
            candidate.unlink(missing_ok=True)


def _serialize(request: Request) -> dict:
    snapshot = _store(request).snapshot()
    locked = bool(getattr(request.app.state, "environment_model_locked", False))
    environment_error = getattr(request.app.state, "environment_model_error", None)
    model = (
        {field: getattr(settings, field) for field in (
            "llm_provider", "llm_base_url", "llm_api_key", "llm_model", "llm_timeout_seconds",
            "llm_context_window_tokens", "llm_max_output_tokens",
        )}
        if locked
        else snapshot["model"]
    )
    models = snapshot["models"]
    public_models = [
        {
            "id": item["id"],
            "name": item["name"],
            "provider": item["llm_provider"],
            "base_url": item["llm_base_url"],
            "model": item["llm_model"],
            "timeout_seconds": item["llm_timeout_seconds"],
            "context_window_tokens": item["llm_context_window_tokens"],
            "max_output_tokens": item["llm_max_output_tokens"],
            "api_key_configured": bool(item.get("llm_api_key")),
            "is_default": item["id"] == models["default_model_id"],
        }
        for item in models["items"]
    ]
    agents = snapshot["agents"]
    public_agents = [
        {
            **item,
            "avatar_url": _avatar_url(item["id"]),
            "is_active": item["id"] == agents["active_agent_id"],
        }
        for item in agents["items"]
    ]
    active_agent_id = agents["active_agent_id"]
    return {
        "model": {
            "provider": model["llm_provider"],
            "base_url": model["llm_base_url"],
            "model": model["llm_model"],
            "timeout_seconds": model["llm_timeout_seconds"],
            "context_window_tokens": model["llm_context_window_tokens"],
            "max_output_tokens": model["llm_max_output_tokens"],
            "api_key_configured": bool(model.get("llm_api_key")),
        },
        "models": {
            "default_model_id": models["default_model_id"],
            "items": public_models,
        },
        "model_control": {
            "source": "environment" if locked else ("error" if environment_error else "profiles"),
            "locked": locked,
            "error": environment_error,
        },
        "context": {
            "max_tokens": settings.context_max_tokens,
        },
        "workspace": {
            "coding_workspace_dir": str(
                Path(snapshot["workspace"]["coding_workspace_dir"]).expanduser().resolve()
            )
        },
        "agent": {**snapshot["agent"], "avatar_url": _avatar_url(active_agent_id)},
        "agents": {
            "active_agent_id": agents["active_agent_id"],
            "items": public_agents,
        },
    }


def _model_values(request: Request, body: ModelSettingsBody, current: dict | None = None) -> dict:
    if current is None:
        current = (
            _find_profile(request, body.model_id)[1]
            if body.model_id
            else _store(request).snapshot()["model"]
        )
    if body.clear_api_key:
        api_key = ""
    elif body.api_key is None or not body.api_key.strip():
        api_key = str(current.get("llm_api_key") or "")
    else:
        api_key = body.api_key.strip()
    values = {
        "llm_provider": body.provider,
        "llm_base_url": body.base_url.strip(),
        "llm_api_key": api_key,
        "llm_model": body.model.strip(),
        "llm_timeout_seconds": body.timeout_seconds,
        "llm_context_window_tokens": body.context_window_tokens,
        "llm_max_output_tokens": body.max_output_tokens,
    }
    if values["llm_max_output_tokens"] >= values["llm_context_window_tokens"]:
        raise HTTPException(422, "最大输出 tokens 必须小于上下文窗口")
    if body.provider == "openai-compatible":
        parsed = urlparse(values["llm_base_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(422, "模型 API 地址必须是有效的 http/https URL")
        if not values["llm_model"]:
            raise HTTPException(422, "请填写模型名称")
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not is_local and not values["llm_api_key"]:
            raise HTTPException(422, "云端模型必须填写 API Key")
    return values


def _find_profile(request: Request, model_id: str) -> tuple[dict, dict]:
    models = _store(request).snapshot()["models"]
    profile = next((item for item in models["items"] if item["id"] == model_id), None)
    if profile is None:
        raise HTTPException(404, "模型配置不存在")
    return models, profile


def _profile_payload(profile_id: str, name: str, values: dict) -> dict:
    return {"id": profile_id, "name": name.strip(), **values}


def _agent_values(body: AgentSettingsBody) -> dict:
    return {
        key: value.strip() if isinstance(value, str) else value
        for key, value in body.model_dump(exclude={"profile_name"}).items()
    }


def _find_agent_profile(request: Request, agent_id: str) -> tuple[dict, dict]:
    agents = _store(request).snapshot()["agents"]
    profile = next((item for item in agents["items"] if item["id"] == agent_id), None)
    if profile is None:
        raise HTTPException(404, "角色预设不存在")
    return agents, profile


def _activate_agent(request: Request, agents: dict) -> dict:
    saved = _store(request).update("agents", agents)
    active = next(
        item for item in saved["items"] if item["id"] == saved["active_agent_id"]
    )
    request.app.state.agent_profile.clear()
    request.app.state.agent_profile.update(
        {key: value for key, value in active.items() if key not in {"id", "profile_name"}}
    )
    return saved


async def _activate_model(request: Request, models: dict) -> None:
    selected = next(
        item for item in models["items"] if item["id"] == models["default_model_id"]
    )
    values = {key: selected[key] for key in (
        "llm_provider", "llm_base_url", "llm_api_key", "llm_model", "llm_timeout_seconds",
        "llm_context_window_tokens", "llm_max_output_tokens",
    )}
    if getattr(request.app.state, "environment_model_locked", False) or getattr(
        request.app.state, "environment_model_error", None
    ):
        _store(request).update("models", models)
        return
    provider = build_provider(_provider_config(values))
    try:
        saved = _store(request).update("models", models)
        for field, value in values.items():
            setattr(settings, field, value)
        await _replace_provider(request, provider)
    except Exception:
        if request.app.state.provider is not provider:
            await provider.close()
        raise


def _provider_config(values: dict):
    return SimpleNamespace(**values)


def _running_agent_exists() -> bool:
    with SessionLocal() as session:
        return session.query(AgentRun).filter(AgentRun.status == "running").first() is not None


async def _replace_provider(request: Request, provider) -> None:
    app = request.app
    task = app.state.activity_task
    if task is not None:
        app.state.activity_stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    previous = app.state.provider
    app.state.provider = provider
    app.state.activity_stop_event = None
    app.state.activity_task = None
    if settings.activity_enabled:
        app.state.activity_stop_event = asyncio.Event()
        app.state.activity_task = asyncio.create_task(
            activity_worker(
                app.state.activity_stop_event,
                app.state.provider,
                app.state.embedding_provider,
                app.state.skills,
                app.state.agent_profile,
                app.state.mcp_manager,
                lambda agent_id: resolve_agent_profile(
                    app.state.runtime_settings_store.snapshot(), agent_id
                ),
            ),
            name="activity-worker",
        )
    await previous.close()


def _resolve_directory(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(422, "请选择绝对文件夹路径")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(422, f"文件夹不可访问：{exc}") from exc
    if not resolved.is_dir():
        raise HTTPException(422, "选择的路径不是文件夹")
    return resolved


@router.get("")
def get_settings(request: Request):
    return _serialize(request)


@router.patch("/agent")
def update_agent(body: AgentSettingsBody, request: Request):
    values = _agent_values(body)
    saved = _store(request).update("agent", values)
    request.app.state.agent_profile.clear()
    request.app.state.agent_profile.update(saved)
    return _serialize(request)["agent"]


@router.post("/agents")
def create_agent_profile(body: AgentProfileBody, request: Request):
    agents = _store(request).snapshot()["agents"]
    profile_id = uuid.uuid4().hex
    agents["items"].append(
        {
            "id": profile_id,
            "profile_name": body.profile_name.strip(),
            **_agent_values(body),
        }
    )
    _store(request).update("agents", agents)
    return next(
        item for item in _serialize(request)["agents"]["items"] if item["id"] == profile_id
    )


@router.patch("/agents/selection")
def set_active_agent(body: ActiveAgentBody, request: Request):
    agents, _ = _find_agent_profile(request, body.agent_id)
    agents["active_agent_id"] = body.agent_id
    _activate_agent(request, agents)
    return _serialize(request)["agents"]


@router.patch("/agents/{agent_id}")
def update_agent_profile(agent_id: str, body: AgentProfileBody, request: Request):
    agents, _ = _find_agent_profile(request, agent_id)
    replacement = {
        "id": agent_id,
        "profile_name": body.profile_name.strip(),
        **_agent_values(body),
    }
    agents["items"] = [
        replacement if item["id"] == agent_id else item for item in agents["items"]
    ]
    if agents["active_agent_id"] == agent_id:
        _activate_agent(request, agents)
    else:
        _store(request).update("agents", agents)
    return next(
        item for item in _serialize(request)["agents"]["items"] if item["id"] == agent_id
    )


@router.delete("/agents/{agent_id}")
def delete_agent_profile(agent_id: str, request: Request):
    agents, _ = _find_agent_profile(request, agent_id)
    if len(agents["items"]) <= 1:
        raise HTTPException(409, "至少保留一个角色预设")
    if agents["active_agent_id"] == agent_id:
        raise HTTPException(409, "请先使用另一个角色，再删除此预设")
    with SessionLocal() as session:
        if session.query(Conversation.id).filter(Conversation.agent_id == agent_id).first():
            raise HTTPException(409, "此角色仍有对话记录，请先删除这些对话")
        if (
            session.query(ProjectAgentAccess.project_id)
            .filter(ProjectAgentAccess.agent_id == agent_id)
            .first()
        ):
            raise HTTPException(409, "此角色仍有项目文件夹权限，请先从这些项目中移除")
        if (
            session.query(Memory.id)
            .filter(Memory.scope_type == "agent", Memory.scope_key == agent_id)
            .first()
        ):
            raise HTTPException(409, "此角色仍有独立记忆，请先删除这些记忆")
    agents["items"] = [item for item in agents["items"] if item["id"] != agent_id]
    _store(request).update("agents", agents)
    _delete_avatar(agent_id)
    return {"ok": True}


@router.post("/agents/{agent_id}/avatar")
async def upload_agent_avatar(agent_id: str, request: Request, file: UploadFile = File(...)):
    _find_agent_profile(request, agent_id)
    data = await file.read(settings.chat_image_max_bytes + 1)
    if len(data) > settings.chat_image_max_bytes:
        raise HTTPException(413, f"图片大小超过限制：{settings.chat_image_max_bytes} 字节")
    if not data:
        raise HTTPException(415, "图片内容为空")
    original_filename = Path(file.filename or "avatar").name
    try:
        _, extension, _, _ = inspect_image(data, original_filename)
    except InvalidChatImageError as exc:
        raise HTTPException(415, str(exc)) from exc

    root = _avatar_root()
    target = root / f"{agent_id}{extension}"
    temporary = root / f".{agent_id}-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    _delete_avatar(agent_id, keep=target)
    return next(
        item for item in _serialize(request)["agents"]["items"] if item["id"] == agent_id
    )


@router.get("/agents/{agent_id}/avatar")
def get_agent_avatar(agent_id: str, request: Request):
    _find_agent_profile(request, agent_id)
    path = _avatar_path(agent_id)
    if path is None:
        raise HTTPException(404, "角色头像不存在")
    return FileResponse(
        path,
        media_type=_AVATAR_MEDIA_TYPES[path.suffix.lower()],
        content_disposition_type="inline",
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/workspace")
def update_workspace(body: WorkspaceSettingsBody, request: Request):
    resolved = _resolve_directory(body.coding_workspace_dir.strip())
    values = {"coding_workspace_dir": str(resolved)}
    saved = _store(request).update("workspace", values)
    settings.coding_workspace_dir = saved["coding_workspace_dir"]
    return saved


@router.post("/model/test")
async def test_model(body: ModelSettingsBody, request: Request):
    values = _model_values(request, body)
    provider = build_provider(_provider_config(values))
    try:
        if body.provider == "openai-compatible":
            reply = await provider.complete(
                [
                    {"role": "system", "content": "你正在执行连接测试。"},
                    {"role": "user", "content": "只回复 OK"},
                ],
                temperature=0,
            )
            return {"ok": True, "message": f"连接成功：{reply[:80] or '模型已响应'}"}
        return {"ok": True, "message": "Mock 模型可用，无需网络连接"}
    except Exception as exc:
        message = str(exc)[:300]
        if "api.deepseek.com" in body.base_url:
            if "401" in message or "Authentication Fails" in message:
                message = "DeepSeek API Key 无效，请在 DeepSeek 开放平台重新创建 Key 后再保存"
            elif "404" in message or "Model Not Found" in message:
                message = "DeepSeek 模型不存在，请选择 deepseek-v4-flash 或 deepseek-v4-pro"
        raise HTTPException(422, f"模型连接失败：{message}") from exc
    finally:
        await provider.close()


@router.patch("/model")
async def update_model(body: ModelSettingsBody, request: Request):
    async with request.app.state.runtime_settings_lock:
        if _running_agent_exists():
            raise HTTPException(409, "当前有正在运行的对话或活动，请完成后再切换模型")
        values = _model_values(request, body)
        provider = build_provider(_provider_config(values))
        try:
            saved = _store(request).update("model", values)
            if getattr(request.app.state, "environment_model_locked", False) or getattr(
                request.app.state, "environment_model_error", None
            ):
                await provider.close()
            else:
                for field, value in saved.items():
                    setattr(settings, field, value)
                await _replace_provider(request, provider)
        except Exception:
            if request.app.state.provider is not provider:
                await provider.close()
            raise
    return _serialize(request)["model"]


@router.post("/models")
async def create_model_profile(body: ModelProfileBody, request: Request):
    async with request.app.state.runtime_settings_lock:
        models = _store(request).snapshot()["models"]
        values = _model_values(request, body, current={})
        profile_id = uuid.uuid4().hex
        models["items"].append(_profile_payload(profile_id, body.name, values))
        first_profile = not models["default_model_id"]
        if first_profile:
            models["default_model_id"] = profile_id
            await _activate_model(request, models)
        else:
            _store(request).update("models", models)
    return next(item for item in _serialize(request)["models"]["items"] if item["id"] == profile_id)


@router.patch("/models/selection")
async def set_default_model(body: DefaultModelBody, request: Request):
    async with request.app.state.runtime_settings_lock:
        if _running_agent_exists():
            raise HTTPException(409, "当前有正在运行的对话或活动，请完成后再切换模型")
        models, _ = _find_profile(request, body.model_id)
        models["default_model_id"] = body.model_id
        await _activate_model(request, models)
    return _serialize(request)["models"]


@router.patch("/models/{model_id}")
async def update_model_profile(model_id: str, body: ModelProfileBody, request: Request):
    async with request.app.state.runtime_settings_lock:
        models, current = _find_profile(request, model_id)
        is_default = models["default_model_id"] == model_id
        if is_default and _running_agent_exists():
            raise HTTPException(409, "当前有正在运行的对话或活动，请完成后再修改默认模型")
        values = _model_values(request, body, current=current)
        replacement = _profile_payload(model_id, body.name, values)
        models["items"] = [replacement if item["id"] == model_id else item for item in models["items"]]
        if is_default:
            await _activate_model(request, models)
        else:
            _store(request).update("models", models)
    return next(item for item in _serialize(request)["models"]["items"] if item["id"] == model_id)


@router.delete("/models/{model_id}")
def delete_model_profile(model_id: str, request: Request):
    models, _ = _find_profile(request, model_id)
    if len(models["items"]) <= 1:
        raise HTTPException(409, "至少保留一个模型配置")
    if models["default_model_id"] == model_id:
        raise HTTPException(409, "请先把另一个模型设为默认，再删除此配置")
    models["items"] = [item for item in models["items"] if item["id"] != model_id]
    _store(request).update("models", models)
    return {"ok": True}


@router.get("/directories")
def list_directories(
    path: str | None = Query(default=None, max_length=1200),
):
    if not path:
        if Path("C:/").exists():
            roots = [
                {"name": f"{letter}:", "path": f"{letter}:\\"}
                for letter in string.ascii_uppercase
                if Path(f"{letter}:/").exists()
            ]
        else:
            roots = [{"name": "/", "path": "/"}]
        return {"current_path": None, "parent_path": None, "directories": roots}

    current = _resolve_directory(path)
    directories: list[dict] = []
    try:
        children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise HTTPException(422, f"无法读取文件夹：{exc}") from exc
    for child in children:
        try:
            if child.is_dir() and not child.is_symlink():
                directories.append({"name": child.name, "path": str(child.resolve())})
        except OSError:
            continue
        if len(directories) >= 300:
            break
    parent = None if current.parent == current else str(current.parent)
    return {
        "current_path": str(current),
        "parent_path": parent,
        "directories": directories,
    }
