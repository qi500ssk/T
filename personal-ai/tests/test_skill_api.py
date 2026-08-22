from infrastructure.config import settings


def test_skill_list_toggle_and_capability_snapshot(client):
    rows = client.get("/api/skills")
    assert rows.status_code == 200
    by_id = {item["id"]: item for item in rows.json()}
    assert by_id["file-notes"]["source"] == "builtin"
    assert by_id["file-notes"]["enabled"] is True
    assert by_id["file-notes"]["deletable"] is True

    disabled = client.patch("/api/skills/file-notes", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    capabilities = client.get("/api/capabilities").json()
    assert not any(
        item["kind"] == "skill" and item["name"] == "file-notes"
        for item in capabilities
    )

    enabled = client.patch("/api/skills/file-notes", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    catalog = client.get("/api/skills/catalog")
    assert catalog.status_code == 200
    assert len(catalog.json()["version"]) == 64
    assert catalog.json()["complete"] is True


def test_refresh_lists_missing_dependencies_without_breaking_runtime(
    client, tmp_path, monkeypatch
):
    skill_dir = tmp_path / "online-demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: online-demo\n"
        "description: imported test\n"
        "required_tools: [missing_tool]\n"
        "enabled: true\n"
        "source: online\n"
        "---\n"
        "Use the missing tool.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "skills_dir", str(tmp_path))

    response = client.post("/api/skills/refresh")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == "online-demo"
    assert item["status"] == "missing_dependencies"
    assert item["enabled"] is False
    assert client.patch(
        "/api/skills/online-demo", json={"enabled": True}
    ).status_code == 409
    assert client.get("/api/conversations").status_code == 200


def test_import_plain_skill_folder_defaults_to_disabled(client, tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    trash_root = tmp_path / "trash"
    monkeypatch.setattr(settings, "skills_dir", str(skill_root))
    monkeypatch.setattr(settings, "skill_trash_dir", str(trash_root))
    document = (
        "---\n"
        "name: Test Notes\n"
        "description: imported folder test\n"
        "required_tools: []\n"
        "enabled: true\n"
        "source: online\n"
        "---\n"
        "Help the user organize short notes.\n"
    ).encode()
    response = client.post(
        "/api/skills/import-folder",
        data={"paths": ["test-notes/SKILL.md", "test-notes/references/example.md"]},
        files=[
            ("files", ("SKILL.md", document, "text/markdown")),
            ("files", ("example.md", b"example", "text/markdown")),
        ],
    )
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["id"] == "test-notes"
    assert item["source"] == "local"
    assert item["enabled"] is False
    assert item["deletable"] is True
    assert (skill_root / "test-notes" / "references" / "example.md").exists()
    normalized = (skill_root / "test-notes" / "SKILL.md").read_text(encoding="utf-8")
    assert "enabled: false" in normalized
    assert "source: local" in normalized
    assert "name: test-notes" in normalized


def test_import_folder_rejects_scripts_and_unsafe_paths(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "skills_dir", str(tmp_path / "skills"))
    document = b"---\nname: unsafe\ndescription: unsafe test\n---\nDo work.\n"
    script = client.post(
        "/api/skills/import-folder",
        data={"paths": ["unsafe/SKILL.md", "unsafe/run.py"]},
        files=[
            ("files", ("SKILL.md", document, "text/markdown")),
            ("files", ("run.py", b"print('no')", "text/x-python")),
        ],
    )
    assert script.status_code == 422
    assert "不允许导入文件类型" in script.text

    traversal = client.post(
        "/api/skills/import-folder",
        data={"paths": ["unsafe/../SKILL.md"]},
        files=[("files", ("SKILL.md", document, "text/markdown"))],
    )
    assert traversal.status_code == 422
    assert "不安全路径" in traversal.text


def test_create_and_recoverably_delete_local_skill(client, tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    trash_root = tmp_path / "trash"
    monkeypatch.setattr(settings, "skills_dir", str(skill_root))
    monkeypatch.setattr(settings, "skill_trash_dir", str(trash_root))
    created = client.post(
        "/api/skills",
        json={
            "id": "simple-helper",
            "name": "Simple Helper",
            "description": "created from settings",
            "instructions": "Answer briefly.",
            "required_tools": [],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["enabled"] is False
    assert created.json()["name"] == "simple-helper"
    assert (skill_root / "simple-helper" / "SKILL.md").exists()

    duplicate = client.post("/api/skills", json={
        "id": "simple-helper",
        "name": "Simple Helper",
        "description": "duplicate",
        "instructions": "Answer.",
        "required_tools": [],
    })
    assert duplicate.status_code == 409

    deleted = client.delete("/api/skills/simple-helper")
    assert deleted.status_code == 200
    assert deleted.json()["recoverable"] is True
    assert not (skill_root / "simple-helper").exists()
    assert any(path.name.startswith("simple-helper-") for path in trash_root.iterdir())


def test_builtin_skill_delete_moves_entire_folder(client, tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    trash_root = tmp_path / "trash"
    skill_dir = skill_root / "builtin-notes"
    reference_dir = skill_dir / "references"
    reference_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: builtin-notes\n"
        "description: builtin delete test\n"
        "required_tools: []\n"
        "enabled: true\n"
        "source: builtin\n"
        "---\n"
        "Use the bundled instructions.\n",
        encoding="utf-8",
    )
    (reference_dir / "guide.md").write_text("keep with package", encoding="utf-8")
    monkeypatch.setattr(settings, "skills_dir", str(skill_root))
    monkeypatch.setattr(settings, "skill_trash_dir", str(trash_root))

    refreshed = client.post("/api/skills/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()[0]["deletable"] is True

    response = client.delete("/api/skills/builtin-notes")
    assert response.status_code == 200
    assert response.json()["recoverable"] is True
    assert not skill_dir.exists()
    moved = next(path for path in trash_root.iterdir() if path.name.startswith("builtin-notes-"))
    assert (moved / "SKILL.md").exists()
    assert (moved / "references" / "guide.md").read_text(encoding="utf-8") == "keep with package"
    assert client.get("/api/skills").json() == []
