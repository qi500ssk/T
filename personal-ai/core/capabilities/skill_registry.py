"""能力域 Skill Provider Registry：统一本地、内置与未来远程来源。"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from core.capabilities.skills import SkillRecord, scan_skills
from infrastructure.config import settings


logger = logging.getLogger(__name__)


class SkillProvider(Protocol):
    name: str
    priority: int

    def list(self) -> list[SkillRecord]: ...


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    records: tuple[SkillRecord, ...]
    version: str
    complete: bool


@dataclass
class DirectorySkillProvider:
    """扫描一个普通 Skill 目录；路径 getter 允许配置热更新。"""

    name: str = "filesystem"
    priority: int = 100
    directory: str | Path | Callable[[], str | Path] = lambda: settings.skills_dir

    def list(self) -> list[SkillRecord]:
        root = self.directory() if callable(self.directory) else self.directory
        return scan_skills(root)


def _catalog_version(records: list[SkillRecord]) -> str:
    payload = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "required_tools": item.required_tools,
            "instructions": item.instructions,
            "source": item.source,
            "available": item.available,
            "error": item.error,
        }
        for item in records
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SkillRegistry:
    """Provider 生命周期、冲突优先级、失败隔离和目录版本。"""

    def __init__(self) -> None:
        self._providers: dict[str, SkillProvider] = {}
        self._last_good: dict[str, list[SkillRecord]] = {}

    def register(self, provider: SkillProvider) -> Callable[[], None]:
        if provider.name in self._providers:
            raise ValueError(f"Skill Provider 已存在：{provider.name}")
        self._providers[provider.name] = provider

        def dispose() -> None:
            if self._providers.get(provider.name) is provider:
                self._providers.pop(provider.name, None)
                self._last_good.pop(provider.name, None)

        return dispose

    def snapshot(self) -> SkillCatalogSnapshot:
        complete = True
        winners: dict[str, tuple[int, int, SkillRecord]] = {}
        providers = sorted(self._providers.values(), key=lambda item: (item.priority, item.name))
        for provider_index, provider in enumerate(providers):
            try:
                records = provider.list()
                self._last_good[provider.name] = records
            except Exception:
                logger.exception("Skill Provider %s 扫描失败，保留最后一次可用目录", provider.name)
                complete = False
                records = self._last_good.get(provider.name, [])
            for record in records:
                candidate = (provider.priority, provider_index, record)
                current = winners.get(record.id)
                if current is None or candidate[:2] < current[:2]:
                    winners[record.id] = candidate
        ordered = sorted((item[2] for item in winners.values()), key=lambda item: item.id)
        return SkillCatalogSnapshot(tuple(ordered), _catalog_version(ordered), complete)


def build_default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(DirectorySkillProvider())
    return registry
