import base64
import json
from pathlib import Path
from types import SimpleNamespace

from core.chat.character import apply_agent_profile, load_character, render_system_prompt
from core.settings.runtime import RuntimeSettingsStore
from infrastructure.config import Settings, settings
from apps.api.main import app


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_settings_defaults_hide_api_key(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    payload = response.json()
    assert "api_key" not in payload["model"]
    assert payload["model"]["provider"] == "mock"
    assert payload["model"]["context_window_tokens"] == settings.llm_context_window_tokens
    assert payload["model"]["max_output_tokens"] == settings.llm_max_output_tokens
    assert payload["context"]["max_tokens"] == settings.context_max_tokens
    assert Path(payload["workspace"]["coding_workspace_dir"]).is_absolute()


def test_agent_settings_persist_and_render_prompt(client):
    body = {
        "name": "小派",
        "role": "熟悉用户的个人助手",
        "language": "zh-CN",
        "tone": "温柔、直接",
        "verbosity": "适中",
        "humor": "少量",
        "formality": "自然",
        "proactivity": "需要时主动提醒",
        "custom_instructions": "称呼用户为小王，先给结论。",
    }
    response = client.patch("/api/settings/agent", json=body)
    assert response.status_code == 200
    assert response.json() == {**body, "avatar_url": None}
    assert client.get("/api/settings").json()["agent"]["name"] == "小派"

    character = apply_agent_profile(load_character(settings.character_file), body)
    prompt = render_system_prompt(character, settings.system_prompt_file)
    assert prompt == "称呼用户为小王，先给结论。"
    assert "你是 小派" not in prompt
    assert "温柔、直接" not in prompt

    conversation = client.post("/api/conversations", json={}).json()
    chat = client.post(
        "/api/chat",
        json={"conversation_id": conversation["id"], "message": "你好"},
    )
    assert chat.status_code == 200
    reply = ""
    for block in chat.text.split("\n\n"):
        if block.startswith("event: message.delta"):
            data = next(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
            reply += json.loads(data)["content"]
    assert "Mock · Mock" in reply


def test_empty_custom_prompt_uses_basic_agent_settings():
    body = {
        "name": "严谨助手",
        "role": "研究顾问",
        "language": "zh-CN",
        "tone": "严谨、克制",
        "verbosity": "详细",
        "humor": "关闭",
        "formality": "正式",
        "proactivity": "低",
        "custom_instructions": "   ",
    }
    character = apply_agent_profile(load_character(settings.character_file), body)
    prompt = render_system_prompt(character, settings.system_prompt_file)
    assert "你是 严谨助手，研究顾问" in prompt
    assert "语气：严谨、克制" in prompt
    assert "回答长度：详细" in prompt


def test_agent_profiles_can_be_named_selected_updated_and_deleted(client):
    initial = client.get("/api/settings").json()
    assert len(initial["agents"]["items"]) == 1
    original_id = initial["agents"]["active_agent_id"]

    body = {
        "profile_name": "小说角色",
        "name": "林老师",
        "role": "写作陪练",
        "language": "zh-CN",
        "tone": "自然",
        "verbosity": "适中",
        "humor": "少量",
        "formality": "轻松",
        "proactivity": "低",
        "custom_instructions": "你是一名小说写作陪练，只按照本段设定回答。",
    }
    created = client.post("/api/settings/agents", json=body)
    assert created.status_code == 200
    created_id = created.json()["id"]
    assert created.json()["profile_name"] == "小说角色"
    assert created.json()["is_active"] is False

    selected = client.patch(
        "/api/settings/agents/selection", json={"agent_id": created_id}
    )
    assert selected.status_code == 200
    assert selected.json()["active_agent_id"] == created_id
    current = client.get("/api/settings").json()
    assert current["agent"]["name"] == "林老师"
    assert current["agent"]["custom_instructions"] == body["custom_instructions"]

    body["profile_name"] = "小说教练"
    updated = client.patch(f"/api/settings/agents/{created_id}", json=body)
    assert updated.status_code == 200
    assert updated.json()["profile_name"] == "小说教练"

    assert client.delete(f"/api/settings/agents/{created_id}").status_code == 409
    assert client.patch(
        "/api/settings/agents/selection", json={"agent_id": original_id}
    ).status_code == 200
    assert client.delete(f"/api/settings/agents/{created_id}").status_code == 200
    assert len(client.get("/api/settings").json()["agents"]["items"]) == 1


def test_agent_avatar_upload_validation_and_profile_cleanup(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "agent_avatar_storage_dir", str(tmp_path / "agent-avatars"))
    initial = client.get("/api/settings").json()
    original_id = initial["agents"]["active_agent_id"]
    assert initial["agent"]["avatar_url"] is None

    uploaded = client.post(
        f"/api/settings/agents/{original_id}/avatar",
        files={"file": ("avatar.png", PNG_1X1, "image/png")},
    )
    assert uploaded.status_code == 200
    avatar_url = uploaded.json()["avatar_url"]
    assert avatar_url.startswith(f"/api/settings/agents/{original_id}/avatar?v=")
    image = client.get(avatar_url)
    assert image.status_code == 200
    assert image.content == PNG_1X1
    assert image.headers["content-type"].startswith("image/png")
    assert image.headers["cache-control"] == "no-store"

    rejected = client.post(
        f"/api/settings/agents/{original_id}/avatar",
        files={"file": ("avatar.png", b"not an image", "image/png")},
    )
    assert rejected.status_code == 415

    body = {
        "profile_name": "临时角色",
        "name": "临时助手",
        "role": "测试头像清理",
        "language": "zh-CN",
        "tone": "自然",
        "verbosity": "适中",
        "humor": "少量",
        "formality": "轻松",
        "proactivity": "低",
        "custom_instructions": "",
    }
    created = client.post("/api/settings/agents", json=body)
    assert created.status_code == 200
    created_id = created.json()["id"]
    assert client.post(
        f"/api/settings/agents/{created_id}/avatar",
        files={"file": ("avatar.png", PNG_1X1, "image/png")},
    ).status_code == 200
    stored_path = tmp_path / "agent-avatars" / f"{created_id}.png"
    assert stored_path.is_file()
    assert client.delete(f"/api/settings/agents/{created_id}").status_code == 200
    assert not stored_path.exists()


def test_workspace_picker_and_runtime_update(client, tmp_path):
    project = tmp_path / "project"
    child = project / "src"
    child.mkdir(parents=True)
    response = client.patch(
        "/api/settings/workspace", json={"coding_workspace_dir": str(project)}
    )
    assert response.status_code == 200
    assert Path(response.json()["coding_workspace_dir"]) == project.resolve()
    assert Path(settings.coding_workspace_dir) == project.resolve()

    listing = client.get("/api/settings/directories", params={"path": str(project)})
    assert listing.status_code == 200
    assert listing.json()["directories"] == [
        {"name": "src", "path": str(child.resolve())}
    ]
    assert client.patch(
        "/api/settings/workspace", json={"coding_workspace_dir": "relative/path"}
    ).status_code == 422


def test_model_settings_validate_mask_and_hot_swap(client):
    invalid = client.patch(
        "/api/settings/model",
        json={
            "provider": "openai-compatible",
            "base_url": "not-a-url",
            "model": "demo",
            "timeout_seconds": 30,
        },
    )
    assert invalid.status_code == 422

    saved = client.patch(
        "/api/settings/model",
        json={
            "provider": "openai-compatible",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:7b",
            "api_key": "local-test-key",
            "timeout_seconds": 30,
            "context_window_tokens": 32_768,
            "max_output_tokens": 2_048,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["api_key_configured"] is True
    assert "api_key" not in saved.json()
    assert saved.json()["context_window_tokens"] == 32_768
    assert saved.json()["max_output_tokens"] == 2_048
    assert client.get("/api/settings").json()["model"]["model"] == "qwen2.5:7b"

    mock_test = client.post(
        "/api/settings/model/test",
        json={"provider": "mock", "timeout_seconds": 30},
    )
    assert mock_test.status_code == 200
    assert mock_test.json()["ok"] is True

    invalid_budget = client.post(
        "/api/settings/model/test",
        json={
            "provider": "mock",
            "timeout_seconds": 30,
            "context_window_tokens": 4_096,
            "max_output_tokens": 4_096,
        },
    )
    assert invalid_budget.status_code == 422


def test_runtime_store_does_not_enable_env_model_without_explicit_test_fallback(tmp_path):
    config = SimpleNamespace(
        llm_provider="openai-compatible",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="env-secret",
        llm_model="env-model",
        llm_timeout_seconds=60,
        coding_workspace_dir=str(tmp_path),
        model_environment_fallback_enabled=False,
    )
    store = RuntimeSettingsStore(str(tmp_path / "runtime.json"), config, {})
    snapshot = store.snapshot()
    assert snapshot["models"] == {"default_model_id": "", "items": []}
    assert snapshot["model"]["llm_provider"] == "unconfigured"
    assert snapshot["model"]["llm_api_key"] == ""


def test_runtime_store_keeps_plugin_secrets_in_local_settings(tmp_path):
    config = SimpleNamespace(
        llm_provider="mock",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
        llm_timeout_seconds=60,
        coding_workspace_dir=str(tmp_path),
        model_environment_fallback_enabled=True,
    )
    path = tmp_path / "runtime.json"
    store = RuntimeSettingsStore(str(path), config, {})
    store.update("plugin_settings", {"web-search": {"tavily_api_key": "secret"}})
    assert store.snapshot()["plugin_settings"]["web-search"]["tavily_api_key"] == "secret"
    reloaded = RuntimeSettingsStore(str(path), config, {})
    assert reloaded.snapshot()["plugin_settings"]["web-search"]["tavily_api_key"] == "secret"


def test_multiple_model_profiles_can_be_selected_and_deleted(client):
    original = client.get("/api/settings").json()["models"]
    assert len(original["items"]) == 1

    created = client.post(
        "/api/settings/models",
        json={
            "name": "备用 Mock",
            "provider": "mock",
            "base_url": "",
            "model": "",
            "timeout_seconds": 30,
        },
    )
    assert created.status_code == 200
    created_id = created.json()["id"]

    selected = client.patch("/api/settings/models/selection", json={"model_id": created_id})
    assert selected.status_code == 200
    assert selected.json()["default_model_id"] == created_id

    old_id = original["default_model_id"]
    deleted = client.delete(f"/api/settings/models/{old_id}")
    assert deleted.status_code == 200
    current = client.get("/api/settings").json()["models"]
    assert [item["id"] for item in current["items"]] == [created_id]


def test_legacy_default_profile_id_can_be_updated(client):
    current = client.get("/api/settings").json()["models"]
    legacy = next(item for item in current["items"] if item["id"] == "default")
    response = client.patch(
        "/api/settings/models/default",
        json={
            "name": "更新后的默认配置",
            "provider": "mock",
            "base_url": "",
            "model": "",
            "timeout_seconds": 45,
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == legacy["id"]
    assert response.json()["name"] == "更新后的默认配置"


def test_cloud_model_requires_api_key(client):
    response = client.post(
        "/api/settings/models",
        json={
            "name": "无 Key 云模型",
            "provider": "openai-compatible",
            "base_url": "https://api.example.com/v1",
            "model": "cloud-model",
            "timeout_seconds": 30,
        },
    )
    assert response.status_code == 422
    assert "API Key" in response.json()["detail"]


def test_complete_environment_model_locks_frontend_profiles():
    configured = Settings(
        _env_file=None,
        llm_provider="openai-compatible",
        llm_base_url="https://api.example.com/v1",
        llm_api_key="secret",
        llm_model="locked-model",
        model_environment_fallback_enabled=False,
    )
    assert configured.environment_model_configured is True
    assert configured.environment_model_error is None

    incomplete = Settings(
        _env_file=None,
        llm_provider="openai-compatible",
        llm_model="missing-url-and-key",
        model_environment_fallback_enabled=False,
    )
    assert incomplete.environment_model_configured is False
    assert incomplete.environment_model_error


def test_environment_lock_ignores_chat_model_selection(client):
    conversation = client.post("/api/conversations", json={}).json()
    previous_locked = app.state.environment_model_locked
    previous_error = app.state.environment_model_error
    app.state.environment_model_locked = True
    app.state.environment_model_error = None
    try:
        response = client.post(
            "/api/chat",
            json={
                "conversation_id": conversation["id"],
                "message": "环境锁定测试",
                "model_id": "does-not-exist",
            },
        )
        assert response.status_code == 200
        assert "run.completed" in response.text
    finally:
        app.state.environment_model_locked = previous_locked
        app.state.environment_model_error = previous_error
