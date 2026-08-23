"""测试环境：必须在导入应用模块前设置环境变量。"""

import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://personal_ai:personal_ai_test_local@localhost:5433/personal_ai_test",
)
if not os.environ["DATABASE_URL"].rstrip("/").endswith("/personal_ai_test"):
    raise RuntimeError("测试只允许连接 personal_ai_test 数据库")
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
from infrastructure.database import Base, engine, init_db


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """测试只使用独立 PostgreSQL 数据库，并通过 Alembic 建立 pgvector schema。"""
    init_db()
    yield


@pytest.fixture(autouse=True)
def clean_db(test_database):
    """每个测试前清空独立测试库，保留 pgvector 扩展和索引。"""
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"
        )
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
