"""聊天域 Character：身份、人格、用户画像 → System Prompt。"""

import copy
from string import Template

import yaml


def load_character(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_agent_profile(character: dict, profile: dict | None) -> dict:
    """只把设置页允许的字段合并进 Character，不修改基础 YAML。"""
    if not profile:
        return character
    merged = copy.deepcopy(character)
    identity = merged.setdefault("identity", {})
    personality = merged.setdefault("personality", {})
    for field in ("name", "role", "language"):
        if field in profile:
            identity[field] = str(profile[field])
    for field in ("tone", "verbosity", "humor", "formality", "proactivity"):
        if field in profile:
            personality[field] = str(profile[field])
    merged["custom_instructions"] = str(profile.get("custom_instructions") or "")
    return merged


def render_system_prompt(character: dict, template_path: str) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        template = Template(f.read())
    profile = character.get("user_profile", {}).get("preferences", [])
    return template.substitute(
        name=character["identity"]["name"],
        role=character["identity"]["role"],
        language=character["identity"]["language"],
        tone=character["personality"]["tone"],
        verbosity=character["personality"]["verbosity"],
        humor=character["personality"]["humor"],
        formality=character["personality"]["formality"],
        proactivity=character["personality"]["proactivity"],
        user_profile_summary="\n".join(f"- {p}" for p in profile) or "（暂无）",
        custom_instructions=character.get("custom_instructions") or "（暂无额外指令）",
    )
