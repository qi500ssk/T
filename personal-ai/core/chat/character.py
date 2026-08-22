"""聊天域 Character：身份、人格、用户画像 → System Prompt。"""

from string import Template

import yaml


def load_character(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    )
