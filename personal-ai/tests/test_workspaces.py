import asyncio
import os
import subprocess
import time
from pathlib import Path

import pytest

from core.execution import coding_tools
from core.execution.workspace import bind_coding_workspace, reset_coding_workspace
from infrastructure.config import settings


def test_directory_and_project_entries_cannot_escape_root(client, tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    child = root / "project"
    child.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(settings, "workspace_root_dir", str(root))
    listing = client.get("/api/settings/directories").json()
    assert listing["current_path"] == str(root.resolve())
    assert listing["parent_path"] is None
    assert listing["directories"] == [{"name": "project", "path": str(child.resolve())}]
    assert client.get("/api/settings/directories", params={"path": str(outside)}).status_code == 422
    assert client.patch("/api/settings/workspace", json={"coding_workspace_dir": str(outside)}).status_code == 422
    assert client.post("/api/projects", json={"name": "outside", "workspace_dir": str(outside)}).status_code == 422
    project = client.post("/api/projects", json={"name": "allowed", "workspace_dir": str(child)})
    assert project.status_code == 200
    assert client.patch(f"/api/projects/{project.json()['id']}", json={"workspace_dir": str(outside)}).status_code == 422


@pytest.mark.asyncio
async def test_legacy_project_cannot_bypass_new_root(tmp_path, monkeypatch):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(settings, "workspace_root_dir", str(root))
    token = bind_coding_workspace(str(outside))
    try:
        with pytest.raises(coding_tools.CodingToolError, match="工作区根"):
            await coding_tools.code_create_file({"path": "blocked.py", "content": "x = 1"})
    finally:
        reset_coding_workspace(token)
    assert not (outside / "blocked.py").exists()


@pytest.mark.asyncio
async def test_simultaneous_edits_keep_both_changes(tmp_path, monkeypatch):
    target = tmp_path / "demo.py"
    target.write_text("a = 0\nb = 0\n", encoding="utf-8")
    original_read = coding_tools._read_source
    def slow_read(path: Path):
        content = original_read(path)
        time.sleep(0.03)
        return content
    monkeypatch.setattr(coding_tools, "_read_source", slow_read)
    token = bind_coding_workspace(str(tmp_path))
    try:
        await asyncio.gather(
            coding_tools.code_edit({"path": "demo.py", "old_text": "a = 0", "new_text": "a = 1"}),
            coding_tools.code_edit({"path": "demo.py", "old_text": "b = 0", "new_text": "b = 1"}),
        )
    finally:
        reset_coding_workspace(token)
    assert target.read_text(encoding="utf-8") == "a = 1\nb = 1\n"


@pytest.mark.asyncio
async def test_search_and_listing_hide_service_credentials(tmp_path, monkeypatch):
    secret = tmp_path / "custom-settings.json"
    secret.write_text("private-marker-123", encoding="utf-8")
    monkeypatch.setattr(settings, "runtime_settings_file", str(secret))
    token = bind_coding_workspace(str(tmp_path))
    try:
        assert "custom-settings.json" not in await coding_tools.code_list_files({"path": "."})
        assert "private-marker-123" not in await coding_tools.code_search({"path": ".", "query": "private-marker"})
        with pytest.raises(coding_tools.CodingToolError, match="凭据"):
            await coding_tools.code_read({"path": secret.name})
    finally:
        reset_coding_workspace(token)


@pytest.mark.asyncio
async def test_recursive_tools_skip_directory_links(tmp_path, monkeypatch):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "private.txt").write_text("outside-marker", encoding="utf-8")
    link = root / "escape"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip("当前环境不能创建目录联接")
    else:
        link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings, "workspace_root_dir", str(root))
    token = bind_coding_workspace(str(root))
    try:
        assert "private.txt" not in await coding_tools.code_list_files({"path": "."})
        assert "outside-marker" not in await coding_tools.code_search({"path": ".", "query": "outside-marker"})
        with pytest.raises(coding_tools.CodingToolError):
            await coding_tools.code_read({"path": "escape/private.txt"})
    finally:
        reset_coding_workspace(token)
        if os.name == "nt":
            link.rmdir()  # 仅删除本测试创建的目录联接，不递归操作目标目录。
        else:
            link.unlink()
    assert (outside / "private.txt").is_file()


def test_native_selection_grants_only_chosen_folder(client, tmp_path, monkeypatch):
    from core.files import native_folder
    from core.files.workspaces import resolve_workspace
    root=tmp_path / "root"
    chosen=tmp_path / "chosen"
    sibling=tmp_path / "sibling"
    for path in (root,chosen,sibling): path.mkdir()
    monkeypatch.setattr(settings,"workspace_root_dir",str(root))
    monkeypatch.setattr(settings,"workspace_grants_file",str(tmp_path / "grants.json"))
    monkeypatch.setattr(native_folder,"select_local_folder",lambda:str(chosen))
    assert client.post("/api/projects",json={"name":"test","workspace_dir":str(chosen)}).status_code==422
    result=client.post("/api/settings/directories/pick")
    assert result.status_code==200
    assert result.json()["path"]==str(chosen.resolve())
    assert resolve_workspace(chosen)==chosen.resolve()
    assert client.post("/api/projects",json={"name":"test","workspace_dir":str(chosen)}).status_code==200
    assert client.get("/api/settings/directories",params={"path":str(chosen)}).json()["parent_path"] is None
    assert client.post("/api/projects",json={"name":"no","workspace_dir":str(sibling)}).status_code==422
    monkeypatch.setattr(native_folder,"select_local_folder",lambda:None)
    before=Path(settings.workspace_grants_file).read_text()
    assert client.post("/api/settings/directories/pick").json()=={"path":None}
    assert Path(settings.workspace_grants_file).read_text()==before


def test_native_selection_error_is_visible(client, monkeypatch):
    from core.files import native_folder
    def failed(): raise ValueError("选择窗口无法打开")
    monkeypatch.setattr(native_folder,"select_local_folder",failed)
    assert client.post("/api/settings/directories/pick").status_code==422
