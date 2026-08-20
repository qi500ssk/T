from core.skills import allowed_tool_names, load_skills, render_skill_instructions


def _write_skill(root, directory, frontmatter, instructions="instructions"):
    path = root / directory
    path.mkdir()
    (path / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n{instructions}\n", encoding="utf-8"
    )


def test_enabled_skills_control_prompt_and_whitelist(tmp_path):
    _write_skill(
        tmp_path,
        "enabled",
        "name: notes\ndescription: note files\nrequired_tools: [read_file]\nenabled: true",
    )
    _write_skill(
        tmp_path,
        "disabled",
        "name: writer\ndescription: writes\nrequired_tools: [write_file]\nenabled: false",
    )
    skills = load_skills(tmp_path)
    assert [skill.name for skill in skills] == ["notes"]
    assert allowed_tool_names(skills) == {"get_time", "calculate", "read_file"}
    prompt = render_skill_instructions(skills)
    assert "notes" in prompt
    assert "writer" not in prompt


def test_skill_with_unknown_tool_is_skipped(tmp_path):
    _write_skill(
        tmp_path,
        "invalid",
        "name: invalid\ndescription: invalid\nrequired_tools: [not_registered]\nenabled: true",
    )
    assert load_skills(tmp_path) == []
