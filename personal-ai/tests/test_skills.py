import pytest

from core.capabilities.skills import allowed_tool_names, load_skills, render_skill_instructions, scan_skills
from core.execution.tools import bind_active_skills, execute_tool, reset_active_skills


def _write_skill(root, directory, frontmatter, instructions="instructions"):
    path = root / directory
    path.mkdir()
    (path / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n{instructions}\n", encoding="utf-8"
    )


def test_enabled_skills_control_prompt_and_whitelist(tmp_path):
    _write_skill(
        tmp_path,
        "notes",
        "name: notes\ndescription: note files\nrequired_tools: [read_file]\nenabled: true",
    )
    _write_skill(
        tmp_path,
        "writer",
        "name: writer\ndescription: writes\nrequired_tools: [write_file]\nenabled: false",
    )
    skills = load_skills(tmp_path)
    assert [skill.name for skill in skills] == ["notes"]
    assert allowed_tool_names(skills) == {"get_time", "calculate", "skill_load", "read_file"}
    prompt = render_skill_instructions(skills)
    assert "notes" in prompt
    assert "writer" not in prompt
    assert "instructions" not in prompt


@pytest.mark.asyncio
async def test_skill_body_is_loaded_only_on_demand(tmp_path):
    _write_skill(
        tmp_path,
        "notes",
        "name: notes\ndescription: note files\nrequired_tools: [read_file]\nenabled: true",
        instructions="First read the note and then summarize it.",
    )
    skills = load_skills(tmp_path)
    token = bind_active_skills(skills)
    try:
        loaded = await execute_tool("skill_load", {"name": "notes"}, {"skill_load"})
        missing = await execute_tool("skill_load", {"name": "disabled"}, {"skill_load"})
    finally:
        reset_active_skills(token)
    assert loaded.status == "completed"
    assert "First read the note" in loaded.content
    assert missing.status == "failed"
    assert "未启用" in missing.content


def test_skill_with_unknown_tool_is_skipped(tmp_path):
    _write_skill(
        tmp_path,
        "invalid",
        "name: invalid\ndescription: invalid\nrequired_tools: [not_registered]\nenabled: true",
    )
    assert load_skills(tmp_path) == []
    record = scan_skills(tmp_path)[0]
    assert record.available is False
    assert record.error == "缺少工具：not_registered"


def test_scan_keeps_disabled_and_invalid_skills_visible(tmp_path):
    _write_skill(
        tmp_path,
        "writer",
        "name: writer\ndescription: writes\nrequired_tools: []\nenabled: false",
    )
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("not frontmatter", encoding="utf-8")

    records = {record.id: record for record in scan_skills(tmp_path)}
    assert records["writer"].default_enabled is False
    assert records["writer"].available is True
    assert records["invalid"].available is False
    assert records["invalid"].error.startswith("格式错误：")


def test_skill_name_must_match_folder(tmp_path):
    _write_skill(
        tmp_path,
        "pdf",
        "name: PDF 文档\ndescription: invalid display name\nrequired_tools: []",
    )
    record = scan_skills(tmp_path)[0]
    assert record.available is False
    assert "name 只能包含小写字母" in record.error
