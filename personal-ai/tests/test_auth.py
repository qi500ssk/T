from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from core.settings.auth import (
    COOKIE_NAME, hash_recovery_code, request_is_local, session_username, verify_password,
)
from infrastructure.config import settings
from infrastructure.database import AdminAccount, LoginSession, RecoveryCode, SessionLocal


def setup_body(**overrides):
    return {"username": "owner", "password": "a-long-test-password", **overrides}


@pytest.fixture
def local_client():
    """模拟从运行服务的这台电脑打开页面。"""
    with TestClient(app, client=("127.0.0.1", 51234)) as test_client:
        test_client.headers["X-Requested-With"] = "PersonalAI"
        yield test_client


@pytest.mark.parametrize("path", [
    "/api/conversations", "/api/projects", "/api/settings", "/api/settings/directories",
    "/api/artifacts", "/api/artifacts/unknown", "/api/documents/unknown/content",
    "/api/chat/images/unknown/content", "/api/memories", "/api/tools", "/api/activities",
])
def test_all_business_routes_require_login(anonymous_client, path):
    response = anonymous_client.get(path)
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_request_is_local_only_accepts_loopback():
    assert request_is_local("127.0.0.1") is True
    assert request_is_local("::1") is True
    assert request_is_local("192.168.1.5") is False
    assert request_is_local("testclient") is False
    assert request_is_local(None) is False


def test_first_setup_on_this_machine_needs_no_setup_code(local_client):
    status = local_client.get("/api/auth/status").json()
    assert status == {"setup_required": True, "authenticated": False, "username": None, "setup_token_required": False}
    assert local_client.post("/api/auth/setup", json=setup_body(password="short")).status_code == 422

    response = local_client.post("/api/auth/setup", json=setup_body())
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert not Path(settings.auth_setup_token_file).exists()
    assert local_client.get("/api/conversations").status_code == 200

    codes = response.json()["recovery_codes"]
    assert len(codes) == 8 and len(set(codes)) == 8
    assert all(len(code) == 9 and code[4] == "-" for code in codes)

    assert local_client.post("/api/auth/setup", json=setup_body()).status_code == 409
    with SessionLocal() as session:
        account = session.get(AdminAccount, 1)
        assert account.password_hash != "a-long-test-password"
        assert verify_password("a-long-test-password", account.password_hash)
        stored = session.query(LoginSession).one()
        assert stored.token_hash != local_client.cookies.get(COOKIE_NAME)
        # 库里只保存恢复码摘要，明文不落盘。
        stored_codes = session.query(RecoveryCode).all()
        assert {row.code_hash for row in stored_codes} == {hash_recovery_code(code) for code in codes}
        assert all(row.used_at is None for row in stored_codes)


def test_first_setup_from_other_devices_requires_the_setup_code(anonymous_client):
    assert anonymous_client.get("/api/auth/status").json()["setup_token_required"] is True
    assert anonymous_client.post("/api/auth/setup", json=setup_body()).status_code == 403
    assert anonymous_client.post("/api/auth/setup", json=setup_body(setup_token="wrong")).status_code == 403

    code = Path(settings.auth_setup_token_file).read_text(encoding="utf-8").strip()
    assert anonymous_client.post("/api/auth/setup", json=setup_body(setup_token=code)).status_code == 200
    assert not Path(settings.auth_setup_token_file).exists()


def test_login_logout_revokes_cookie_and_preserves_other_sessions(client):
    first = client.cookies.get(COOKIE_NAME)
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "other", "password": "test-admin-password"}).status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    assert response.status_code == 200
    # fixture cookie 没有域，取实际登录响应的 cookie。
    token = response.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token)
    assert session_username(token) == "admin"
    assert client.post("/api/auth/logout").status_code == 200
    assert session_username(token) is None
    assert session_username(first) == "admin"
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/settings").status_code == 401


def test_remember_me_extends_session_only_when_requested(client):
    now = datetime.now(timezone.utc)
    client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    with SessionLocal() as session:
        short = session.query(LoginSession).order_by(LoginSession.expires_at.desc()).first().expires_at
    client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password", "remember": True})
    with SessionLocal() as session:
        long = session.query(LoginSession).order_by(LoginSession.expires_at.desc()).first().expires_at
    assert short - now < timedelta(hours=settings.auth_session_hours, minutes=5)
    assert long - now > timedelta(hours=settings.auth_session_remember_hours, minutes=-5)


def test_change_password_revokes_every_old_session(client):
    other = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"}).cookies[COOKIE_NAME]
    assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "another-long-password"}).status_code == 401
    assert session_username(other) == "admin"

    response = client.post("/api/auth/password", json={"current_password": "test-admin-password", "new_password": "another-long-password"})
    assert response.status_code == 200
    assert session_username(other) is None
    assert client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"}).status_code == 401

    token = response.cookies.get(COOKIE_NAME)
    assert session_username(token) == "admin"
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/settings").status_code == 200


def test_recovery_without_an_account_is_rejected(anonymous_client):
    assert anonymous_client.post("/api/auth/recovery", json={
        "username": "owner", "recovery_code": "ZZZZ-ZZZZ", "new_password": "recovered-password-2026",
    }).status_code == 409


def test_recovery_code_resets_password_and_revokes_old_sessions(local_client):
    codes = local_client.post("/api/auth/setup", json=setup_body()).json()["recovery_codes"]
    other = local_client.post("/api/auth/login", json={"username": "owner", "password": "a-long-test-password"}).cookies[COOKIE_NAME]
    assert session_username(other) == "owner"

    response = local_client.post("/api/auth/recovery", json={
        "username": "owner", "recovery_code": codes[0], "new_password": "recovered-password-2026",
    })
    assert response.status_code == 200
    assert response.json()["recovery_codes_remaining"] == 7
    assert session_username(response.cookies.get(COOKIE_NAME)) == "owner"
    assert session_username(other) is None
    with SessionLocal() as session:
        assert verify_password("recovered-password-2026", session.get(AdminAccount, 1).password_hash)
        assert session.get(RecoveryCode, hash_recovery_code(codes[0])).used_at is not None


def test_recovery_code_is_single_use_and_accepts_free_form_input(local_client):
    codes = local_client.post("/api/auth/setup", json=setup_body()).json()["recovery_codes"]
    first = codes[0]
    # 允许小写、空格和漏写短横线。
    assert local_client.post("/api/auth/recovery", json={
        "username": "owner", "recovery_code": f" {first[:4].lower()} {first[5:]} ", "new_password": "recovered-password-2026",
    }).status_code == 200
    assert local_client.post("/api/auth/recovery", json={
        "username": "owner", "recovery_code": first, "new_password": "another-long-password",
    }).status_code == 401
    assert local_client.post("/api/auth/recovery", json={
        "username": "owner", "recovery_code": "ZZZZ-ZZZZ", "new_password": "another-long-password",
    }).status_code == 401
    with SessionLocal() as session:
        assert verify_password("recovered-password-2026", session.get(AdminAccount, 1).password_hash)
        assert session.get(RecoveryCode, hash_recovery_code(codes[1])).used_at is None


def test_wrong_username_does_not_consume_the_recovery_code(local_client):
    codes = local_client.post("/api/auth/setup", json=setup_body()).json()["recovery_codes"]
    assert local_client.post("/api/auth/recovery", json={
        "username": "someone-else", "recovery_code": codes[0], "new_password": "recovered-password-2026",
    }).status_code == 401
    # 用户名打错不该浪费掉一组恢复码。
    assert local_client.post("/api/auth/recovery", json={
        "username": "owner", "recovery_code": codes[0], "new_password": "recovered-password-2026",
    }).status_code == 200


def test_regenerating_recovery_codes_invalidates_previous_batch(client):
    with SessionLocal() as session:
        assert session.query(RecoveryCode).count() == 0
    assert client.post("/api/auth/recovery-codes", json={"password": "wrong-password"}).status_code == 401
    response = client.post("/api/auth/recovery-codes", json={"password": "test-admin-password"})
    assert response.status_code == 200
    codes = response.json()["recovery_codes"]
    assert len(codes) == 8

    assert client.get("/api/auth/recovery-codes").json() == {"total": 8, "used": 0, "remaining": 8}
    first = client.post("/api/auth/recovery-codes", json={"password": "test-admin-password"}).json()["recovery_codes"]
    assert client.get("/api/auth/recovery-codes").json()["remaining"] == 8
    assert client.post("/api/auth/recovery", json={
        "username": "admin", "recovery_code": codes[0], "new_password": "recovered-password-2026",
    }).status_code == 401
    assert client.post("/api/auth/recovery", json={
        "username": "admin", "recovery_code": first[0], "new_password": "recovered-password-2026",
    }).status_code == 200


def test_logout_all_revokes_sessions_on_every_device(client):
    other = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"}).cookies[COOKIE_NAME]
    assert client.post("/api/auth/logout-all").status_code == 200
    assert session_username(other) is None
    assert client.get("/api/settings").status_code == 401


def test_expired_and_forged_sessions_are_rejected(client):
    with SessionLocal() as session:
        session.query(LoginSession).update({LoginSession.expires_at: datetime.now(timezone.utc) - timedelta(seconds=1)})
        session.commit()
    assert client.get("/api/conversations").status_code == 401
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, "forged-token")
    assert client.get("/api/settings").status_code == 401


def test_mutations_require_csrf_header_even_when_logged_in(client):
    del client.headers["X-Requested-With"]
    assert client.post("/api/conversations", json={"title": "blocked"}).status_code == 403
    assert client.post("/api/chat", json={}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/recovery", json={}).status_code == 403
    assert client.get("/api/settings").status_code == 200


def test_global_login_rate_limit(anonymous_client):
    for _ in range(10):
        assert anonymous_client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 409
    response = anonymous_client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_https_cookie_and_private_response_cache(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-admin-password"})
    assert "; Secure" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"


def test_sse_disables_proxy_transformation(client):
    conversation = client.post("/api/conversations", json={"title": "stream"}).json()
    response = client.post("/api/chat", json={"conversation_id": conversation["id"], "message": "你好"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, no-transform"
    assert "event: run.completed" in response.text
