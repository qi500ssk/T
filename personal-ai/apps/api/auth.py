"""本机账号：首次设置、登录、改密码，以及保护全部业务接口的 ASGI 中间件。"""

import hashlib
import hmac
from pathlib import Path
from contextlib import contextmanager
import logging

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from starlette.responses import JSONResponse

from core.settings.auth import (
    COOKIE_NAME, allow_login_attempt, consume_recovery_code, hash_password,
    issue_recovery_codes, new_session, recovery_code_summary, request_is_local,
    reset_login_attempts, session_hours, session_username, setup_required,
    valid_setup_token, verify_password,
)
from infrastructure.config import settings
from infrastructure.database import AdminAccount, LoginSession, SessionLocal

router = APIRouter(prefix="/api/auth", tags=["auth"])
PUBLIC_PATHS = {
    "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/auth/recovery",
}


@contextmanager
def _account_transaction():
    # SQLite 的 FOR UPDATE 不提供行锁。先取得写锁，再检查凭据和换发会话，
    # 避免旧密码登录与密码重设并发时重新产生本应失效的会话。
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        yield session
        session.commit()


class AuthenticationMiddleware:
    # 使用原生 ASGI，不缓冲 SSE 响应，也不改变流式任务的取消语义。
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/")
        request = Request(scope)
        if path == "/api" or path.startswith("/api/"):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if request.headers.get("x-requested-with") != "PersonalAI":
                    await JSONResponse({"detail": "请求缺少同源保护标记"}, 403)(scope, receive, send)
                    return
            if path not in PUBLIC_PATHS:
                username = await anyio.to_thread.run_sync(session_username, request.cookies.get(COOKIE_NAME))
                if not username:
                    await JSONResponse({"detail": "请先登录"}, 401)(scope, receive, send)
                    return
                scope.setdefault("state", {})["username"] = username
        async def no_cache(message):
            if message["type"] == "http.response.start" and path.startswith("/api/"):
                streaming = any(k.lower() == b"content-type" and v.startswith(b"text/event-stream") for k, v in message["headers"])
                message["headers"] = [(k, v) for k, v in message["headers"] if k.lower() != b"cache-control"]
                # 禁止代理压缩 SSE，否则 Next.js 会等压缩缓冲区填满才发送。
                message["headers"].append((b"cache-control", b"no-store, no-transform" if streaming else b"no-store"))
            await send(message)
        await self.app(scope, receive, no_cache)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)


class LoginCredentials(Credentials):
    remember: bool = False


class SetupCredentials(Credentials):
    password: str = Field(min_length=12, max_length=128)
    # 只有非本机来源才必须提供设置码；本机首次打开页面直接创建账号。
    setup_token: str = Field(default="", max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class RecoveryRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    recovery_code: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=12, max_length=128)


def _set_cookie(response: Response, token: str, hours: int) -> None:
    response.set_cookie(
        COOKIE_NAME, token, max_age=hours * 3600,
        httponly=True, secure=settings.auth_cookie_secure, samesite="strict", path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=settings.auth_cookie_secure, samesite="strict")


def _limit_attempts() -> None:
    if not allow_login_attempt():
        raise HTTPException(429, "尝试次数过多，请一分钟后再试", headers={"Retry-After": "60"})


def _client_is_local(request: Request) -> bool:
    return request_is_local(request.client.host if request.client else None)


@router.get("/status")
def status(request: Request):
    username = session_username(request.cookies.get(COOKIE_NAME))
    return {
        "setup_required": setup_required(),
        "authenticated": bool(username),
        "username": username,
        "setup_token_required": not _client_is_local(request),
    }


@router.post("/setup")
def setup(body: SetupCredentials, request: Request, response: Response):
    _limit_attempts()
    if not setup_required():
        raise HTTPException(409, "本机账号已创建，请直接登录")
    if not _client_is_local(request) and not valid_setup_token(body.setup_token):
        raise HTTPException(403, "首次设置码无效，请在运行服务的电脑上完成设置")
    account = AdminAccount(id=1, username=body.username, password_hash=hash_password(body.password))
    with _account_transaction() as session:
        session.add(account)
        try:
            session.flush()
            token = new_session(session, account)
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "本机账号已创建，请直接登录") from None
        recovery_codes = issue_recovery_codes(session, account)
    try:
        Path(settings.auth_setup_token_file).unlink(missing_ok=True)
    except OSError:
        logging.getLogger(__name__).warning("本机账号已创建，旧设置码文件未能清理；该码已不可用于创建账号")
    reset_login_attempts()
    _set_cookie(response, token, settings.auth_session_hours)
    return {"ok": True, "username": account.username, "recovery_codes": recovery_codes}


@router.post("/login")
def login(body: LoginCredentials, response: Response):
    _limit_attempts()
    with _account_transaction() as session:
        account = session.get(AdminAccount, 1)
        if account is None:
            raise HTTPException(409, "请先创建本机账号")
        valid = verify_password(body.password, account.password_hash)
        if not valid or not hmac.compare_digest(account.username.encode(), body.username.encode()):
            raise HTTPException(401, "用户名或密码错误")
        hours = session_hours(body.remember)
        token = new_session(session, account, hours)
    reset_login_attempts()
    _set_cookie(response, token, hours)
    return {"ok": True, "username": account.username}


@router.post("/password")
def change_password(body: PasswordChange, response: Response):
    _limit_attempts()
    with _account_transaction() as session:
        account = session.get(AdminAccount, 1)
        if account is None:
            raise HTTPException(409, "请先创建本机账号")
        if not verify_password(body.current_password, account.password_hash):
            raise HTTPException(401, "当前密码不正确")
        account.password_hash = hash_password(body.new_password)
        # 旧会话全部失效，当前设备换发新会话，其他设备需要重新登录。
        session.query(LoginSession).delete()
        token = new_session(session, account, settings.auth_session_hours)
    reset_login_attempts()
    _set_cookie(response, token, settings.auth_session_hours)
    return {"ok": True}


@router.post("/recovery")
def recovery(body: RecoveryRequest, response: Response):
    """用一次性恢复码重设密码；成功后直接登录，旧会话全部失效。"""
    _limit_attempts()
    with _account_transaction() as session:
        account = session.get(AdminAccount, 1)
        if account is None:
            raise HTTPException(409, "请先创建本机账号")
        if not hmac.compare_digest(account.username.encode(), body.username.encode()):
            raise HTTPException(401, "用户名或恢复码不正确")
        if not consume_recovery_code(session, account, body.recovery_code):
            raise HTTPException(401, "用户名或恢复码不正确")
        account.password_hash = hash_password(body.new_password)
        session.query(LoginSession).delete()
        token = new_session(session, account, settings.auth_session_hours)
        remaining = recovery_code_summary(session, account.id)["remaining"]
    reset_login_attempts()
    _set_cookie(response, token, settings.auth_session_hours)
    return {"ok": True, "username": account.username, "recovery_codes_remaining": remaining}


@router.get("/recovery-codes")
def get_recovery_codes():
    with SessionLocal() as session:
        return recovery_code_summary(session, 1)


@router.post("/recovery-codes")
def regenerate_recovery_codes(body: PasswordConfirm):
    """作废旧恢复码并重新生成一批；明文只在这一条响应里返回。"""
    _limit_attempts()
    with _account_transaction() as session:
        account = session.get(AdminAccount, 1)
        if account is None:
            raise HTTPException(409, "请先创建本机账号")
        if not verify_password(body.password, account.password_hash):
            raise HTTPException(401, "密码不正确")
        codes = issue_recovery_codes(session, account)
    reset_login_attempts()
    return {"ok": True, "recovery_codes": codes}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    with _account_transaction() as session:
        session.query(LoginSession).filter(LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()).delete()
    _clear_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
def logout_all(response: Response):
    with _account_transaction() as session:
        session.query(LoginSession).delete()
    _clear_cookie(response)
    return {"ok": True}
