"""本地运行时设置：按用户持久化，不写入仓库配置文件。"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path


MODEL_FIELDS = (
    "llm_provider",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "llm_timeout_seconds",
    "llm_context_window_tokens",
    "llm_max_output_tokens",
)

AGENT_FIELDS = (
    "name",
    "role",
    "language",
    "tone",
    "verbosity",
    "humor",
    "formality",
    "proactivity",
    "custom_instructions",
)

DEFAULT_MODEL_PROFILE_ID = "default"
DEFAULT_AGENT_PROFILE_ID = "default"


def _model_profile(model: dict, *, profile_id: str = DEFAULT_MODEL_PROFILE_ID, name: str = "") -> dict:
    return {
        "id": profile_id,
        "name": name.strip() or str(model.get("llm_model") or "Mock"),
        **{field: copy.deepcopy(model.get(field)) for field in MODEL_FIELDS},
    }


def _normalize_models(raw: dict | None, fallback_model: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    items: list[dict] = []
    seen: set[str] = set()
    for candidate in raw.get("items") or []:
        if not isinstance(candidate, dict):
            continue
        profile_id = str(candidate.get("id") or "").strip()
        if not profile_id or profile_id in seen:
            continue
        merged = copy.deepcopy(fallback_model)
        for field in MODEL_FIELDS:
            if field in candidate:
                merged[field] = copy.deepcopy(candidate[field])
        items.append(
            _model_profile(
                merged,
                profile_id=profile_id,
                name=str(candidate.get("name") or ""),
            )
        )
        seen.add(profile_id)
    if not items and fallback_model.get("llm_provider") != "unconfigured":
        items = [_model_profile(fallback_model)]
    default_id = str(raw.get("default_model_id") or "").strip()
    if default_id not in {item["id"] for item in items}:
        default_id = items[0]["id"] if items else ""
    return {"default_model_id": default_id, "items": items}


def _agent_profile(
    agent: dict,
    *,
    profile_id: str = DEFAULT_AGENT_PROFILE_ID,
    profile_name: str = "",
) -> dict:
    return {
        "id": profile_id,
        "profile_name": profile_name.strip() or "默认角色",
        **{field: str(agent.get(field) or "") for field in AGENT_FIELDS},
    }


def _normalize_agents(raw: dict | None, fallback_agent: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    items: list[dict] = []
    seen: set[str] = set()
    for candidate in raw.get("items") or []:
        if not isinstance(candidate, dict):
            continue
        profile_id = str(candidate.get("id") or "").strip()
        if not profile_id or profile_id in seen:
            continue
        merged = copy.deepcopy(fallback_agent)
        for field in AGENT_FIELDS:
            if field in candidate:
                merged[field] = str(candidate[field] or "")
        items.append(
            _agent_profile(
                merged,
                profile_id=profile_id,
                profile_name=str(candidate.get("profile_name") or ""),
            )
        )
        seen.add(profile_id)
    if not items:
        items = [_agent_profile(fallback_agent)]
    active_id = str(raw.get("active_agent_id") or "").strip()
    if active_id not in {item["id"] for item in items}:
        active_id = items[0]["id"]
    return {"active_agent_id": active_id, "items": items}


def default_agent_profile(character: dict) -> dict:
    identity = character.get("identity") or {}
    personality = character.get("personality") or {}
    return {
        "name": str(identity.get("name") or "Assistant"),
        "role": str(identity.get("role") or "Personal AI Assistant"),
        "language": str(identity.get("language") or "zh-CN"),
        "tone": str(personality.get("tone") or "友好、自然"),
        "verbosity": str(personality.get("verbosity") or "简洁"),
        "humor": str(personality.get("humor") or "适度"),
        "formality": str(personality.get("formality") or "轻松但不失专业"),
        "proactivity": str(personality.get("proactivity") or "低（不主动打扰）"),
        "custom_instructions": str(character.get("custom_instructions") or ""),
    }


def resolve_agent_profile(snapshot: dict, agent_id: str | None = None) -> dict:
    """按稳定 ID 解析角色；旧数据缺少 ID 时回退到当前默认角色。"""
    agents = snapshot["agents"]
    requested_id = str(agent_id or agents["active_agent_id"])
    selected = next(
        (item for item in agents["items"] if item["id"] == requested_id),
        None,
    )
    if selected is None:
        selected = next(
            (
                item
                for item in agents["items"]
                if item["id"] == agents["active_agent_id"]
            ),
            agents["items"][0],
        )
    return {field: copy.deepcopy(selected[field]) for field in AGENT_FIELDS}


def capture_runtime_config(config) -> dict:
    model_defaults = {
        "llm_context_window_tokens": 12_096,
        "llm_max_output_tokens": 4_096,
    }
    return {
        "model": {
            field: getattr(config, field, model_defaults.get(field))
            for field in MODEL_FIELDS
        },
        "workspace": {"coding_workspace_dir": config.coding_workspace_dir},
    }


def apply_runtime_config(config, values: dict) -> None:
    model = values.get("model") or {}
    workspace = values.get("workspace") or {}
    for field in MODEL_FIELDS:
        if field in model:
            setattr(config, field, model[field])
    if "coding_workspace_dir" in workspace:
        config.coding_workspace_dir = str(workspace["coding_workspace_dir"])


class RuntimeSettingsStore:
    """维护环境默认值与本地覆盖值，并使用原子写入保存。"""

    def __init__(self, path: str, config, character: dict):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._defaults = {
            **capture_runtime_config(config),
            "agent": default_agent_profile(character),
            "plugin_settings": {},
        }
        if not getattr(config, "model_environment_fallback_enabled", False):
            self._defaults["model"] = {
                "llm_provider": "unconfigured",
                "llm_base_url": "",
                "llm_api_key": "",
                "llm_model": "",
                "llm_timeout_seconds": 60.0,
                "llm_context_window_tokens": getattr(config, "llm_context_window_tokens", 12_096),
                "llm_max_output_tokens": getattr(config, "llm_max_output_tokens", 4_096),
            }
        self._defaults["models"] = _normalize_models(None, self._defaults["model"])
        self._defaults["agents"] = _normalize_agents(None, self._defaults["agent"])
        self._overrides: dict = {}
        self.error: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("运行时设置必须是 JSON 对象")
            # 兼容早期只有一个 model 对象的运行时配置。迁移后仍保留全部密钥，
            # 但把它包装为可选择的默认模型配置。
            if not isinstance(raw.get("models"), dict):
                legacy_model = copy.deepcopy(self._defaults["model"])
                if isinstance(raw.get("model"), dict):
                    legacy_model.update(copy.deepcopy(raw["model"]))
                raw["models"] = _normalize_models(None, legacy_model)
            raw.pop("model", None)
            # 兼容早期只有一个 agent 对象的运行时配置。
            if not isinstance(raw.get("agents"), dict):
                legacy_agent = copy.deepcopy(self._defaults["agent"])
                if isinstance(raw.get("agent"), dict):
                    legacy_agent.update(copy.deepcopy(raw["agent"]))
                raw["agents"] = _normalize_agents(None, legacy_agent)
            raw.pop("agent", None)
            self._overrides = raw
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.error = f"运行时设置加载失败，已使用环境默认值：{exc}"

    def snapshot(self) -> dict:
        result = copy.deepcopy(self._defaults)
        for section in ("workspace", "plugin_settings"):
            override = self._overrides.get(section)
            if isinstance(override, dict):
                result[section].update(copy.deepcopy(override))
        result["models"] = _normalize_models(
            self._overrides.get("models"),
            self._defaults["model"],
        )
        selected = next(
            (
                item
                for item in result["models"]["items"]
                if item["id"] == result["models"]["default_model_id"]
            ),
            None,
        )
        result["model"] = (
            {field: copy.deepcopy(selected[field]) for field in MODEL_FIELDS}
            if selected
            else copy.deepcopy(self._defaults["model"])
        )
        result["agents"] = _normalize_agents(
            self._overrides.get("agents"),
            self._defaults["agent"],
        )
        active_agent = next(
            (
                item
                for item in result["agents"]["items"]
                if item["id"] == result["agents"]["active_agent_id"]
            ),
            result["agents"]["items"][0],
        )
        result["agent"] = {
            field: copy.deepcopy(active_agent[field]) for field in AGENT_FIELDS
        }
        return result

    def update(self, section: str, values: dict) -> dict:
        if section not in {"model", "models", "workspace", "agent", "agents", "plugin_settings"}:
            raise KeyError(section)
        with self._lock:
            if section == "model":
                models = self.snapshot()["models"]
                for item in models["items"]:
                    if item["id"] == models["default_model_id"]:
                        item.update({field: copy.deepcopy(values[field]) for field in MODEL_FIELDS})
                        break
                self._overrides["models"] = models
                self._overrides.pop("model", None)
            elif section == "models":
                self._overrides["models"] = _normalize_models(values, self._defaults["model"])
                self._overrides.pop("model", None)
            elif section == "agent":
                agents = self.snapshot()["agents"]
                for item in agents["items"]:
                    if item["id"] == agents["active_agent_id"]:
                        item.update(
                            {
                                field: copy.deepcopy(values[field])
                                for field in AGENT_FIELDS
                                if field in values
                            }
                        )
                        break
                self._overrides["agents"] = _normalize_agents(
                    agents, self._defaults["agent"]
                )
                self._overrides.pop("agent", None)
            elif section == "agents":
                self._overrides["agents"] = _normalize_agents(
                    values, self._defaults["agent"]
                )
                self._overrides.pop("agent", None)
            else:
                self._overrides[section] = copy.deepcopy(values)
            self._write()
            return self.snapshot()[section]

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = json.dumps(self._overrides, ensure_ascii=False, indent=2) + "\n"
        try:
            temp.write_text(payload, encoding="utf-8")
            try:
                temp.chmod(0o600)
            except OSError:
                pass
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()
