"""本机账号密码、一次性恢复码与可撤销会话；数据库里不保存明文密码、恢复码或会话令牌。"""

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from infrastructure.config import settings
from infrastructure.database import AdminAccount, LoginSession, RecoveryCode, SessionLocal

COOKIE_NAME = "personal_ai_session"
RECOVERY_CODE_COUNT = 8
# 去掉容易看错的 I、O、0、1，方便用户抄写。
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_attempts: deque[float] = deque()
_attempt_lock = threading.Lock()
_password_lock = threading.Lock()


def allow_login_attempt() -> bool:
    # 每台安装只有一个账号，共用全局限速，避免信任可伪造的转发 IP。
    with _attempt_lock:
        now = time.monotonic()
        while _attempts and _attempts[0] < now - 60:
            _attempts.popleft()
        if len(_attempts) >= 10:
            return False
        _attempts.append(now)
        return True


def reset_login_attempts() -> None:
    # 登录成功后清空计数，正常使用不会被自己的重试挡在门外。
    with _attempt_lock:
        _attempts.clear()


def request_is_local(host: str | None) -> bool:
    """判断请求是否来自本机回环地址；用于首次设置免验证码。"""
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    # 限制并发哈希的内存用量；scrypt 参数固定，不能由请求控制。
    with _password_lock:
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1,
            maxmem=256 * 1024 * 1024,
        )
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, _ = stored.split("$")
        return algorithm == "scrypt" and hmac.compare_digest(hash_password(password, salt), stored)
    except (ValueError, TypeError):
        return False


def setup_required() -> bool:
    with SessionLocal() as session:
        return session.get(AdminAccount, 1) is None


def ensure_setup_token() -> None:
    # 首次设置码只在非本机来源时要求；正常安装不需要跑命令行。
    if not setup_required():
        return
    path = Path(settings.auth_setup_token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(secrets.token_urlsafe(32))


def valid_setup_token(token: str) -> bool:
    try:
        expected = Path(settings.auth_setup_token_file).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(expected) and hmac.compare_digest(token.encode(), expected.encode())


def session_hours(remember: bool) -> int:
    return settings.auth_session_remember_hours if remember else settings.auth_session_hours


def new_session(session, account: AdminAccount, hours: int | None = None) -> str:
    """创建会话但不提交，由调用方与密码/恢复码操作一起提交。"""
    now = datetime.now(timezone.utc)
    session.query(LoginSession).filter(LoginSession.expires_at <= now).delete()
    token = secrets.token_urlsafe(32)
    session.add(LoginSession(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=account.id,
        expires_at=now + timedelta(hours=hours or settings.auth_session_hours),
    ))
    session.flush()
    return token


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def hash_recovery_code(code: str) -> str:
    # 输入允许大小写、空格和短横线自由书写，只按字母数字比较。
    normalized = "".join(character for character in code.upper() if character.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def issue_recovery_codes(session, account: AdminAccount, count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """重新生成一批恢复码；由调用方提交，明文只在这一次响应里出现。"""
    session.query(RecoveryCode).filter(RecoveryCode.account_id == account.id).delete()
    codes = [_new_recovery_code() for _ in range(count)]
    session.add_all(
        RecoveryCode(code_hash=hash_recovery_code(code), account_id=account.id) for code in codes
    )
    session.flush()
    return codes


def consume_recovery_code(session, account: AdminAccount, code: str) -> bool:
    """校验并作废一个恢复码；同一个码不能使用第二次。"""
    if not code.strip():
        return False
    changed = session.query(RecoveryCode).filter(
        RecoveryCode.code_hash == hash_recovery_code(code),
        RecoveryCode.account_id == account.id,
        RecoveryCode.used_at.is_(None),
    ).update({RecoveryCode.used_at: datetime.now(timezone.utc)}, synchronize_session=False)
    return changed == 1


def recovery_code_summary(session, account_id: int) -> dict:
    rows = session.query(RecoveryCode).filter(RecoveryCode.account_id == account_id).all()
    used = sum(1 for row in rows if row.used_at is not None)
    return {"total": len(rows), "used": used, "remaining": len(rows) - used}


def session_username(token: str | None) -> str | None:
    if not token or len(token) > 128:
        return None
    with SessionLocal() as session:
        row = session.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
        if row is None or row.expires_at <= datetime.now(timezone.utc):
            return None
        account = session.get(AdminAccount, row.account_id)
        return account.username if account else None
