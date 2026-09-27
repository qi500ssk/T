from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import apps.api.auth as auth_api
from apps.api.main import app
from core.settings.auth import COOKIE_NAME, session_username, hash_recovery_code, verify_password
from infrastructure.database import AdminAccount, AgentRun, Conversation, LoginSession, RecoveryCode, SessionLocal, engine, build_sqlite_engine


def test_concurrent_recovery_code_can_only_succeed_once(client):
    codes = client.post("/api/auth/recovery-codes", json={"password": "test-admin-password"}).json()["recovery_codes"]
    gate = threading.Barrier(2)
    def reset(index):
        gate.wait(timeout=10)
        try:
            auth_api.recovery(auth_api.RecoveryRequest(username="admin", recovery_code=codes[0], new_password=f"replacement-password-{index}"), Response())
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reset, (1, 2)))
    assert sorted(results) == [200, 401]
    with SessionLocal() as session:
        assert session.query(RecoveryCode).filter(RecoveryCode.used_at.is_not(None)).count() == 1
        assert session.query(LoginSession).count() == 1


def test_failed_first_setup_rolls_back_account_sessions_and_codes(anonymous_client, monkeypatch):
    def failed_codes(*args):
        raise RuntimeError("injected storage failure")
    monkeypatch.setattr(auth_api, "issue_recovery_codes", failed_codes)
    with TestClient(app, client=("127.0.0.1", 1234)) as local:
        with pytest.raises(RuntimeError, match="injected"):
            local.post("/api/auth/setup", headers={"X-Requested-With": "PersonalAI"}, json={"username": "owner", "password": "new-owner-password"})
    with SessionLocal() as session:
        assert session.query(AdminAccount).count() == 0
        assert session.query(LoginSession).count() == 0
        assert session.query(RecoveryCode).count() == 0


def test_failed_recovery_preserves_password_code_and_session(client, monkeypatch):
    code = client.post("/api/auth/recovery-codes", json={"password": "test-admin-password"}).json()["recovery_codes"][0]
    previous = client.cookies.get(COOKIE_NAME)
    def failed_session(*args):
        raise RuntimeError("injected session failure")
    monkeypatch.setattr(auth_api, "new_session", failed_session)
    with pytest.raises(RuntimeError, match="injected"):
        client.post("/api/auth/recovery", json={"username": "admin", "recovery_code": code, "new_password": "new-owner-password"})
    assert session_username(previous) == "admin"
    with SessionLocal() as session:
        assert verify_password("test-admin-password", session.get(AdminAccount, 1).password_hash)
        assert session.get(RecoveryCode, hash_recovery_code(code)).used_at is None


def test_sqlite_constraints_utc_and_persistence():
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    with SessionLocal() as session:
        conversation = Conversation(title="persistent")
        session.add(conversation); session.flush()
        session.add_all([AgentRun(conversation_id=conversation.id, status="completed"), AgentRun(conversation_id=conversation.id, status="completed")])
        session.commit()
        cid = conversation.id
    with SessionLocal() as session:
        row = session.get(Conversation, cid)
        assert row.created_at.tzinfo == timezone.utc
        session.add_all([AgentRun(conversation_id=cid), AgentRun(conversation_id=cid)])
        with pytest.raises(IntegrityError):
            session.commit()
    independent = build_sqlite_engine(engine.url)
    try:
        with independent.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM conversations WHERE id = ?", (cid,)).scalar() == 1
    finally:
        independent.dispose()


def test_database_rejects_remote_connections():
    with pytest.raises(ValueError, match="仅支持 SQLite"):
        build_sqlite_engine("postgresql://user:password@example.invalid/shared")


def test_backup_includes_committed_wal_and_refuses_overwrite(tmp_path, monkeypatch):
    import sqlite3
    import sys
    from contextlib import closing
    from scripts import backup_database

    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    monkeypatch.setattr(backup_database.settings, "database_url", "sqlite:///" + source.as_posix())
    monkeypatch.setattr(sys, "argv", ["backup_database", str(destination)])
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('committed in WAL')")
        connection.commit()
        backup_database.main()
        with closing(sqlite3.connect(destination)) as backup:
            assert backup.execute("SELECT value FROM sample").fetchone()[0] == "committed in WAL"
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(SystemExit):
            backup_database.main()
    # Windows 下立即移动也验证备份连接已关闭。
    destination.rename(tmp_path / "moved.db")


def test_default_database_follows_system_user_data_directory(tmp_path, monkeypatch):
    import sys
    from sqlalchemy.engine import make_url
    from infrastructure.config import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PERSONAL_AI_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    paths = []
    for user in ("alice", "bob"):
        local = tmp_path / user / "AppData" / "Local"
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        url = make_url(Settings(_env_file=None).database_url)
        assert url.get_backend_name() == "sqlite"
        assert url.database == (local / "PersonalAI" / "personal-ai.db").as_posix()
        paths.append(url.database)
    assert paths[0] != paths[1]
