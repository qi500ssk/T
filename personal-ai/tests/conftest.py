"""测试环境：必须在导入应用模块前设置环境变量。"""

import os
import tempfile
from pathlib import Path

# 每次测试运行使用全新临时 SQLite 文件，不接受外部正式库地址。
_test_data = tempfile.TemporaryDirectory(prefix="personal-ai-tests-")
os.environ["PERSONAL_AI_DATA_DIR"] = _test_data.name
_postgres_test_url = os.environ.get("PERSONAL_AI_TEST_POSTGRES_URL", "")
if _postgres_test_url:
    from sqlalchemy.engine import make_url
    _test_url = make_url(_postgres_test_url)
    if _test_url.get_backend_name() != "postgresql" or not (_test_url.database or "").startswith("personal_ai_test_") or _test_url.host not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("PostgreSQL tests require a dedicated local personal_ai_test_* database")
os.environ["DATABASE_URL"] = _postgres_test_url or "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["LLM_PROVIDER"] = "mock"
os.environ["MODEL_ENVIRONMENT_FALLBACK_ENABLED"] = "true"
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["FILE_STORAGE_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_uploads"
os.environ["CHAT_IMAGE_STORAGE_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_chat_images"
os.environ["SANDBOX_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_sandbox"
os.environ["MCP_ENABLED"] = "false"
os.environ["ACTIVITY_ENABLED"] = "false"
os.environ["CODING_WORKSPACE_DIR"] = f"{tempfile.gettempdir()}/personal_ai_test_coding"
os.environ["WORKSPACE_ROOT_DIR"] = tempfile.gettempdir()
os.environ["RUNTIME_SETTINGS_FILE"] = f"{tempfile.gettempdir()}/personal_ai_test_runtime_settings.json"

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from infrastructure.config import settings
from infrastructure.database import Base, engine, init_db


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """测试使用独立临时 SQLite 文件，通过 Alembic 建立 schema。"""
    init_db()
    yield
    engine.dispose()
    _test_data.cleanup()


@pytest.fixture(autouse=True)
def clean_db(test_database, tmp_path, monkeypatch):
    """每个测试前清空临时库；保留表结构与索引。"""
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    monkeypatch.setattr(settings, "auth_setup_token_file", str(tmp_path / "setup-token"))
    from core.settings.auth import _attempts
    _attempts.clear()
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


@pytest.fixture(scope="session")
def admin_password_hash():
    from core.settings.auth import hash_password
    return hash_password("test-admin-password")


@pytest.fixture
def client(admin_password_hash):
    from core.settings.auth import COOKIE_NAME, new_session
    from infrastructure.database import AdminAccount, SessionLocal
    with SessionLocal() as session:
        account = AdminAccount(id=1, username="admin", password_hash=admin_password_hash)
        session.add(account)
        session.flush()
        token = new_session(session, account)
        session.commit()
    with TestClient(app) as c:
        c.headers["X-Requested-With"] = "PersonalAI"
        c.cookies.set(COOKIE_NAME, token)
        yield c


@pytest.fixture
def anonymous_client():
    with TestClient(app) as c:
        c.headers["X-Requested-With"] = "PersonalAI"
        yield c
