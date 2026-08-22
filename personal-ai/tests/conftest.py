"""测试环境：必须在导入应用模块前设置环境变量。"""

import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/personal_ai_test.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MODEL_ENVIRONMENT_FALLBACK_ENABLED"] = "true"
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["FILE_STORAGE_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_uploads"
os.environ["CHAT_IMAGE_STORAGE_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_chat_images"
os.environ["SANDBOX_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_sandbox"
os.environ["MCP_ENABLED"] = "false"
os.environ["ACTIVITY_ENABLED"] = "false"
os.environ["CODING_WORKSPACE_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_coding"
os.environ["RUNTIME_SETTINGS_FILE"] = f"{tempfile.gettempdir()}/personal_ai_test_runtime_settings.json"

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from infrastructure.config import settings
from infrastructure.database import Base, engine


@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前重建数据库，保证隔离。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    upload_dir = Path(settings.file_storage_dir)
    image_dir = Path(settings.chat_image_storage_dir)
    sandbox_dir = Path(settings.sandbox_dir)
    runtime_settings_file = Path(settings.runtime_settings_file)
    runtime_settings_file.unlink(missing_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    for path in upload_dir.iterdir():
        if path.is_file():
            path.unlink()
    for path in image_dir.iterdir():
        if path.is_file():
            path.unlink()
    for path in sandbox_dir.iterdir():
        if path.is_file():
            path.unlink()
    yield
    runtime_settings_file.unlink(missing_ok=True)
    for path in upload_dir.iterdir():
        if path.is_file():
            path.unlink()
    for path in image_dir.iterdir():
        if path.is_file():
            path.unlink()
    for path in sandbox_dir.iterdir():
        if path.is_file():
            path.unlink()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
