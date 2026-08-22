"""常规设置 API：模型、Agent 人格与编码工作区。"""

from __future__ import annotations

import asyncio
import string
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.automation.activity import activity_worker
from core.chat.gateway import build_provider
from infrastructure.config import settings
from infrastructure.database import AgentRun, SessionLocal


router = APIRouter(prefix="/api/settings", tags=["settings"])


class ModelSettingsBody(BaseModel):
    model_id: str | None = Field(default=None, max_length=100)
    provider: Literal["mock", "openai-compatible"]
    base_url: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False
    timeout_seconds: float = Field(default=60.0, ge=5, le=300)


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


class WorkspaceSettingsBody(BaseModel):
    coding_workspace_dir: str = Field(min_length=1, max_length=1200)


def _store(request: Request):
    store = getattr(request.app.state, "runtime_settings_store", None)
    if store is None:
        raise HTTPException(503, "运行时设置尚未初始化")
    return store


def _serialize(request: Request) -> dict:
    snapshot = _store(request).snapshot()
    locked = bool(getattr(request.app.state, "environment_model_locked", False))
    environment_error = getattr(request.app.state, "environment_model_error", None)
    model = (
        {field: getattr(settings, field) for field in (
            "llm_provider", "llm_base_url", "llm_api_key", "llm_model", "llm_timeout_seconds"
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
            "api_key_configured": bool(item.get("llm_api_key")),
            "is_default": item["id"] == models["default_model_id"],
        }
        for item in models["items"]
    ]
    return {
        "model": {
            "provider": model["llm_provider"],
            "base_url": model["llm_base_url"],
            "model": model["llm_model"],
            "timeout_seconds": model["llm_timeout_seconds"],
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
        "workspace": {
            "coding_workspace_dir": str(
                Path(snapshot["workspace"]["coding_workspace_dir"]).expanduser().resolve()
            )
        },
        "agent": snapshot["agent"],
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
    }
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


async def _activate_model(request: Request, models: dict) -> None:
    selected = next(
        item for item in models["items"] if item["id"] == models["default_model_id"]
    )
    values = {key: selected[key] for key in (
        "llm_provider", "llm_base_url", "llm_api_key", "llm_model", "llm_timeout_seconds"
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
    values = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in body.model_dump().items()
    }
    saved = _store(request).update("agent", values)
    request.app.state.agent_profile.clear()
    request.app.state.agent_profile.update(saved)
    return _serialize(request)["agent"]


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
