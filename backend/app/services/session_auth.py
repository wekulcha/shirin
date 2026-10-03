from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.refresh_session import RefreshSession
from app.models.user import User

REFRESH_COOKIE_NAME = "kulcha_market_refresh_token"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    return utcnow().replace(tzinfo=None)


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _base64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def _sign(value: bytes, secret: str) -> str:
    return _base64url_encode(hmac.new(secret.encode(), value, hashlib.sha256).digest())


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _get_access_secret() -> str:
    settings = get_settings()
    if settings.auth_access_secret:
        return settings.auth_access_secret
    if settings.internal_api_secret:
        return settings.internal_api_secret
    if settings.user_bot_token:
        return settings.user_bot_token
    raise HTTPException(503, "Auth access secret is not configured")


def create_access_token(user_id: int) -> tuple[str, datetime]:
    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(minutes=settings.auth_access_ttl_minutes)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    encoded_header = _base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = _sign(signing_input, _get_access_secret())
    return f"{encoded_header}.{encoded_payload}.{signature}", expires_at.replace(tzinfo=None)


def verify_access_token(token: str) -> int | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        encoded_header, encoded_payload, received_signature = parts
        signing_input = f"{encoded_header}.{encoded_payload}".encode()
        expected_signature = _sign(signing_input, _get_access_secret())
        if not hmac.compare_digest(expected_signature, received_signature):
            return None

        payload = json.loads(_base64url_decode(encoded_payload))
        if payload.get("typ") != "access":
            return None
        exp = payload.get("exp")
        sub = payload.get("sub")
        if not isinstance(exp, int) or not isinstance(sub, str):
            return None
        if int(time.time()) >= exp:
            return None
        return int(sub)
    except Exception:
        return None


def get_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Invalid Authorization header")
    return token.strip()


async def get_user_from_bearer(db: AsyncSession, authorization: str | None) -> User | None:
    token = get_bearer_token(authorization)
    if not token:
        return None
    user_id = verify_access_token(token)
    if user_id is None:
        raise HTTPException(401, "Invalid access token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(401, "User not found for access token")
    if not user.is_active:
        raise HTTPException(403, "Аккаунт отключён")
    return user


async def ensure_customer(db: AsyncSession, telegram_id: int, username: str | None) -> User:
    result = await db.execute(select(User).where(User.id == telegram_id))
    user = result.scalars().first()
    if user:
        if not user.is_active:
            raise HTTPException(403, "Аккаунт отключён")
        return user

    user = User(
        id=telegram_id,
        username=username or f"tg_{telegram_id}",
        phone=f"tg-{telegram_id}",
        registered_at=datetime.now(),
    )
    db.add(user)
    await db.flush()
    return user


async def create_refresh_session(db: AsyncSession, user_id: int) -> tuple[str, datetime]:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    now = utcnow_naive()
    expires_at = now + timedelta(days=settings.auth_refresh_ttl_days)
    session = RefreshSession(
        user_id=user_id,
        token_hash=_hash_refresh_token(raw_token),
        created_at=now,
        last_used_at=now,
        expires_at=expires_at,
        revoked_at=None,
    )
    db.add(session)
    await db.flush()
    return raw_token, expires_at


async def rotate_refresh_session(
    db: AsyncSession,
    raw_token: str,
) -> tuple[User, str, datetime] | None:
    now = utcnow_naive()
    result = await db.execute(
        select(RefreshSession).where(RefreshSession.token_hash == _hash_refresh_token(raw_token))
    )
    session = result.scalars().first()
    if not session:
        return None
    if session.revoked_at is not None or session.expires_at <= now:
        return None

    session.revoked_at = now
    session.last_used_at = now
    refresh_token, refresh_expires_at = await create_refresh_session(db, session.user_id)

    result = await db.execute(select(User).where(User.id == session.user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(401, "User not found for refresh session")
    if not user.is_active:
        raise HTTPException(403, "Аккаунт отключён")
    return user, refresh_token, refresh_expires_at


async def revoke_refresh_session(db: AsyncSession, raw_token: str | None) -> None:
    if not raw_token:
        return
    result = await db.execute(
        select(RefreshSession).where(RefreshSession.token_hash == _hash_refresh_token(raw_token))
    )
    session = result.scalars().first()
    if session and session.revoked_at is None:
        session.revoked_at = utcnow_naive()
        session.last_used_at = utcnow_naive()
        await db.flush()


def set_refresh_cookie(response: Response, raw_token: str, expires_at: datetime) -> None:
    settings = get_settings()
    max_age = max(0, int((expires_at - utcnow_naive()).total_seconds()))
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        domain=settings.auth_cookie_domain or None,
        path="/api/v1/auth",
        max_age=max_age,
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        domain=settings.auth_cookie_domain or None,
        path="/api/v1/auth",
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )
