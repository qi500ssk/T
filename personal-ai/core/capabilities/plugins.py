"""能力域声明式 Plugin：组合 Skill 与 MCP，不执行插件内任意代码。"""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

import anyio
import yaml

from core.capabilities.mcp import McpServerConfig, _parse_server_config
from core.capabilities.mcp_manager import McpManager
from core.capabilities.skill_registry import DirectorySkillProvider, SkillRegistry
from infrastructure.config import settings


PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
PLUGIN_SETTING_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
MAX_FOLDER_FILES = 200
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_FOLDER_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".yaml", ".yml", ".json", ".md", ".txt",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".docx",
}


class PluginError(ValueError):
    pass


class PluginConflictError(PluginError):
    pass


@dataclass(frozen=True)
class PluginSetting:
    key: str
    label: str
    description: str
    secret: bool
    required: bool
    configured: bool

    def public(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "secret": self.secret,
            "required": self.required,
            "configured": self.configured,
        }


@dataclass(frozen=True)
class PluginRecord:
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    skill_count: int
    mcp_server_count: int
    status: str
    error: str | None = None
    settings: tuple[PluginSetting, ...] = ()
    config_ready: bool = True

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "enabled": self.enabled,
            "skill_count": self.skill_count,
            "mcp_server_count": self.mcp_server_count,
            "status": self.status,
            "error": self.error,
            "settings": [item.public() for item in self.settings],
            "config_ready": self.config_ready,
            "deletable": True,
        }


@dataclass(frozen=True)
class _ParsedPlugin:
    record: PluginRecord
    mcp_configs: tuple[McpServerConfig, ...]


def _safe_relative(raw: str) -> PurePosixPath:
    if not raw or "\\" in raw or "\x00" in raw:
        raise PluginError("文件夹中存在不安全路径")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginError("文件夹中存在不安全路径")
    if any(":" in part for part in path.parts):
        raise PluginError("文件夹中存在不安全路径")
    return path


def _normalize_entries(
    entries: list[tuple[str, bytes]],
) -> tuple[str, list[tuple[PurePosixPath, bytes]]]:
    if not entries or len(entries) > MAX_FOLDER_FILES:
        raise PluginError(f"文件数量必须在 1 到 {MAX_FOLDER_FILES} 之间")
    parsed = [(_safe_relative(path), content) for path, content in entries]
    roots = {path.parts[0] for path, _ in parsed if len(path.parts) > 1}
    strip_root = len(roots) == 1 and all(len(path.parts) > 1 for path, _ in parsed)
    folder_name = next(iter(roots)) if strip_root else "imported-plugin"
    normalized: list[tuple[PurePosixPath, bytes]] = []
    seen: set[str] = set()
    total = 0
    for path, content in parsed:
        relative = PurePosixPath(*path.parts[1:]) if strip_root else path
        key = relative.as_posix().lower()
        if key in seen:
            raise PluginError("插件中存在重复文件")
        seen.add(key)
        if len(content) > MAX_FILE_BYTES:
            raise PluginError("插件内单个文件不能超过 4MB")
        total += len(content)
        if total > MAX_FOLDER_BYTES:
            raise PluginError("插件文件夹不能超过 10MB")
        if relative.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise PluginError(f"声明式插件不允许文件类型：{relative.suffix or '无扩展名'}")
        normalized.append((relative, content))
    manifests = [item for item in normalized if item[0].as_posix().lower() == "plugin.yaml"]
    if len(manifests) != 1:
        raise PluginError("所选文件夹根目录必须有且只能有一个 plugin.yaml")
    return folder_name, normalized


def _manifest_document(path: Path) -> dict:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PluginError(f"plugin.yaml 无法读取：{exc}") from exc
    if not isinstance(document, dict):
        raise PluginError("plugin.yaml 必须是对象")
    return document


def _parse_settings(document: dict, values: dict[str, str]) -> tuple[PluginSetting, ...]:
    raw_settings = document.get("settings", []) or []
    if not isinstance(raw_settings, list):
        raise PluginError("settings 必须是列表")
    parsed: list[PluginSetting] = []
    seen: set[str] = set()
    for raw in raw_settings:
        if not isinstance(raw, dict):
            raise PluginError("settings 中的每一项都必须是对象")
        key = str(raw.get("key", "")).strip()
        if not PLUGIN_SETTING_KEY_RE.fullmatch(key) or key in seen:
            raise PluginError("插件设置 key 必须唯一，且只能包含小写字母、数字和下划线")
        setting_type = str(raw.get("type", "secret")).strip()
        if setting_type not in {"secret", "text"}:
            raise PluginError(f"插件设置 {key} 的 type 必须是 secret 或 text")
        label = str(raw.get("label", key)).strip()
        description = str(raw.get("description", "")).strip()
        required = raw.get("required", False)
        if not label or not isinstance(required, bool):
            raise PluginError(f"插件设置 {key} 的 label 或 required 无效")
        value = values.get(key, "")
        parsed.append(
            PluginSetting(
                key=key,
                label=label,
                description=description,
                secret=setting_type == "secret",
                required=required,
                configured=bool(value.strip()),
            )
        )
        seen.add(key)
    return tuple(parsed)


def _parse_manifest(
    plugin_id: str,
    root: Path,
    setting_values: dict[str, str] | None = None,
) -> _ParsedPlugin:
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        raise PluginError("插件 ID 只能包含小写字母、数字和连字符")
    document = _manifest_document(root / "plugin.yaml")
    declared_id = str(document.get("id", plugin_id)).strip()
    if declared_id != plugin_id:
        raise PluginError("plugin.yaml 的 id 必须与插件文件夹名一致")
    name = str(document.get("name", "")).strip()
    description = str(document.get("description", "")).strip()
    version = str(document.get("version", "0.1.0")).strip()
    enabled = document.get("enabled", False)
    if not name or not description:
        raise PluginError("plugin.yaml 必须包含 name 和 description")
    if not isinstance(enabled, bool):
        raise PluginError("enabled 必须是布尔值")

    values = setting_values if isinstance(setting_values, dict) else {}
    plugin_settings = _parse_settings(document, values)
    missing_required = [item.label for item in plugin_settings if item.required and not item.configured]
    effective_enabled = enabled and not missing_required

    skills_root = root / "skills"
    skill_count = len(list(skills_root.glob("*/SKILL.md"))) if skills_root.is_dir() else 0
    raw_servers = document.get("mcp_servers", {}) or {}
    if not isinstance(raw_servers, dict):
        raise PluginError("mcp_servers 必须是对象")
    configs: list[McpServerConfig] = []
    for local_name, raw in raw_servers.items():
        if not isinstance(raw, dict):
            raise PluginError(f"MCP Server {local_name} 无效：配置必须是对象")
        resolved_raw = dict(raw)
        raw_env_mapping = resolved_raw.pop("env_from_settings", {}) or {}
        if not isinstance(raw_env_mapping, dict) or any(
            not isinstance(env_name, str) or not isinstance(setting_key, str)
            for env_name, setting_key in raw_env_mapping.items()
        ):
            raise PluginError(f"MCP Server {local_name} 的 env_from_settings 必须是字符串键值对象")
        declared_keys = {item.key for item in plugin_settings}
        unknown_keys = sorted(set(raw_env_mapping.values()) - declared_keys)
        if unknown_keys:
            raise PluginError(
                f"MCP Server {local_name} 引用了未声明的插件设置：{', '.join(unknown_keys)}"
            )
        resolved_env = dict(resolved_raw.get("env", {}) or {})
        for env_name, setting_key in raw_env_mapping.items():
            resolved_env[env_name] = values.get(setting_key, "")
        resolved_raw["env"] = resolved_env
        namespace = f"{plugin_id}-{local_name}"
        try:
            config = _parse_server_config(namespace, resolved_raw)
        except (TypeError, ValueError) as exc:
            raise PluginError(f"MCP Server {local_name} 无效：{exc}") from exc
        configs.append(replace(config, enabled=effective_enabled and config.enabled))
    status = "enabled" if effective_enabled else "needs_configuration" if missing_required else "disabled"
    return _ParsedPlugin(
        PluginRecord(
            id=plugin_id,
            name=name,
            description=description,
            version=version,
            enabled=effective_enabled,
            skill_count=skill_count,
            mcp_server_count=len(configs),
            status=status,
            settings=plugin_settings,
            config_ready=not missing_required,
        ),
        tuple(configs),
    )


class PluginManager:
    def __init__(
        self,
        registry: SkillRegistry,
        mcp_manager: McpManager,
        root: str | Path | None = None,
        trash_root: str | Path | None = None,
        settings_provider: Callable[[str], dict[str, str]] | None = None,
    ):
        self.registry = registry
        self.mcp_manager = mcp_manager
        self.root = Path(root or settings.plugins_dir)
        self.trash_root = Path(trash_root or settings.plugin_trash_dir)
        self.settings_provider = settings_provider or (lambda _plugin_id: {})
        self._records: dict[str, PluginRecord] = {}
        self._disposers: dict[str, Callable[[], None]] = {}

    def list(self) -> list[dict]:
        return [self._records[key].public() for key in sorted(self._records)]

    async def refresh(self) -> list[dict]:
        previous = set(self._records) | set(self._disposers)
        for dispose in self._disposers.values():
            dispose()
        self._disposers.clear()
        for plugin_id in previous:
            await self.mcp_manager.replace_external(f"plugin:{plugin_id}", [])

        self.root.mkdir(parents=True, exist_ok=True)
        records: dict[str, PluginRecord] = {}
        for folder in sorted(self.root.iterdir(), key=lambda item: item.name.lower()):
            if not folder.is_dir() or folder.is_symlink() or folder.name.startswith("."):
                continue
            try:
                parsed = _parse_manifest(
                    folder.name,
                    folder,
                    self.settings_provider(folder.name),
                )
                record = parsed.record
                if record.enabled:
                    await self.mcp_manager.replace_external(
                        f"plugin:{record.id}", list(parsed.mcp_configs)
                    )
                    skills_root = folder / "skills"
                    if skills_root.is_dir():
                        provider = DirectorySkillProvider(
                            name=f"plugin:{record.id}",
                            priority=200,
                            directory=skills_root,
                        )
                        self._disposers[record.id] = self.registry.register(provider)
                records[record.id] = record
            except Exception as exc:
                records[folder.name] = PluginRecord(
                    id=folder.name,
                    name=folder.name,
                    description="无法加载此插件",
                    version="-",
                    enabled=False,
                    skill_count=0,
                    mcp_server_count=0,
                    status="invalid",
                    error=str(exc),
                )
        self._records = records
        return self.list()

    async def set_enabled(self, plugin_id: str, enabled: bool) -> dict:
        record = self._records.get(plugin_id)
        if record is None:
            raise KeyError(plugin_id)
        if record.error:
            raise PluginError(record.error)
        manifest = self.root / plugin_id / "plugin.yaml"
        document = _manifest_document(manifest)
        if enabled:
            parsed = _parse_manifest(
                plugin_id,
                self.root / plugin_id,
                self.settings_provider(plugin_id),
            )
            missing = [item.label for item in parsed.record.settings if item.required and not item.configured]
            if missing:
                raise PluginError(f"请先配置：{', '.join(missing)}")
        document["enabled"] = enabled
        await _atomic_yaml_write(manifest, document)
        await self.refresh()
        return self._records[plugin_id].public()

    def get(self, plugin_id: str) -> dict:
        record = self._records.get(plugin_id)
        if record is None:
            raise KeyError(plugin_id)
        return record.public()

    async def install_folder(self, entries: list[tuple[str, bytes]]) -> dict:
        folder_name, normalized = _normalize_entries(entries)
        raw_manifest = next(
            content for path, content in normalized if path.as_posix().lower() == "plugin.yaml"
        )
        try:
            document = yaml.safe_load(raw_manifest.decode("utf-8-sig")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise PluginError(f"plugin.yaml 无法读取：{exc}") from exc
        if not isinstance(document, dict):
            raise PluginError("plugin.yaml 必须是对象")
        plugin_id = str(document.get("id", folder_name)).strip().lower()
        if not PLUGIN_ID_RE.fullmatch(plugin_id):
            raise PluginError("插件 ID 只能包含小写字母、数字和连字符，长度 2-64")
        document["id"] = plugin_id
        document["enabled"] = False

        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / plugin_id
        if target.exists():
            raise PluginConflictError(f"插件 {plugin_id} 已存在")
        staging = Path(tempfile.mkdtemp(prefix=".plugin-import-", dir=self.root))
        try:
            for relative, content in normalized:
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            (staging / "plugin.yaml").write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            _parse_manifest(plugin_id, staging, {})
            staging.replace(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        await self.refresh()
        return self._records[plugin_id].public()

    async def remove(self, plugin_id: str) -> Path:
        if plugin_id not in self._records:
            raise KeyError(plugin_id)
        target = (self.root / plugin_id).resolve()
        root = self.root.resolve()
        if target.parent != root or not target.is_dir() or target.is_symlink():
            raise PluginError("插件文件夹不存在或路径不安全")
        self.trash_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = self.trash_root / f"{plugin_id}-{stamp}-{uuid.uuid4().hex[:6]}"
        await anyio.to_thread.run_sync(shutil.move, str(target), str(destination))
        await self.refresh()
        return destination


async def _atomic_yaml_write(path: Path, document: dict) -> None:
    def _write() -> None:
        text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".plugin-", suffix=".yaml", delete=False
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.replace(path)

    await anyio.to_thread.run_sync(_write)
