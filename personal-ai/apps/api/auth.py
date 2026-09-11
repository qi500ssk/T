"""登录、首次设置，以及保护全部业务接口的 ASGI 中间件。"""

import hashlib
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.responses import JSONResponse

from core.settings.auth import (
    COOKIE_NAME, allow_login_attempt, hash_password, new_session,
    session_username, setup_required, valid_setup_token, verify_password,
)
from infrastructure.config import settings
from infrastructure.database import AdminAccount, LoginSession, SessionLocal

router = APIRouter(prefix="/api/auth", tags=["auth"])
PUBLIC_PATHS = {"/api/auth/status", "/api/auth/login", "/api/auth/setup"}


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


class SetupCredentials(Credentials):
    password: str = Field(min_length=12, max_length=128)
    setup_token: str = Field(min_length=1, max_length=128)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.auth_session_hours * 3600,
        httponly=True, secure=settings.auth_cookie_secure, samesite="strict", path="/",
    )


def _limit_attempts() -> None:
    if not allow_login_attempt():
        raise HTTPException(429, "尝试次数过多，请一分钟后再试", headers={"Retry-After": "60"})


@router.get("/status")
def status(request: Request):
    username = session_username(request.cookies.get(COOKIE_NAME))
    return {"setup_required": setup_required(), "authenticated": bool(username), "username": username}


@router.post("/setup")
def setup(body: SetupCredentials, response: Response):
    _limit_attempts()
    if not setup_required():
        raise HTTPException(409, "管理员已设置，请直接登录")
    if not valid_setup_token(body.setup_token):
        raise HTTPException(403, "首次设置码无效，请在运行服务的电脑上获取")
    account = AdminAccount(id=1, username=body.username, password_hash=hash_password(body.password))
    with SessionLocal() as session:
        session.add(account)
        try:
            session.flush()
            token = new_session(session, account)
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "管理员已设置，请直接登录") from None
    Path(settings.auth_setup_token_file).unlink(missing_ok=True)
    _set_cookie(response, token)
    return {"ok": True, "username": account.username}


@router.post("/login")
def login(body: Credentials, response: Response):
    _limit_attempts()
    with SessionLocal() as session:
        account = session.get(AdminAccount, 1)
        if account is None:
            raise HTTPException(409, "请先完成管理员设置")
        valid = verify_password(body.password, account.password_hash)
        if not valid or account.username != body.username:
            raise HTTPException(401, "用户名或密码错误")
        token = new_session(session, account)
    _set_cookie(response, token)
    return {"ok": True, "username": account.username}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    with SessionLocal() as session:
        session.query(LoginSession).filter(LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()).delete()
        session.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=settings.auth_cookie_secure, samesite="strict")
    return {"ok": True}
