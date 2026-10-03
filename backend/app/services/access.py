import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import IntegrationNonce, Staff, User
from app.models.business import Permission, now
from app.services.session_auth import ensure_customer, get_user_from_bearer


@dataclass
class Actor:
    user: User
    permissions: set[str]
    superadmin: bool = False

    def has(self, permission: str) -> bool:
        return self.superadmin or permission in self.permissions

    def require(self, permission: str):
        if not self.has(permission):
            raise HTTPException(403, "access_denied")

    def require_superadmin(self):
        if not self.superadmin:
            raise HTTPException(403, "access_denied")


async def actor_for_user(db: AsyncSession, user: User) -> Actor:
    if not user.is_active:
        raise HTTPException(403, "account_disabled")
    perms = set((await db.scalars(select(Staff.permission).where(Staff.user_id == user.id))).all())
    return Actor(user, perms, user.id in get_settings().superadmin_allowed_ids)


def signed_value(method: str, path: str, query: str, body: bytes, actor: str, timestamp: str, nonce: str) -> bytes:
    return "\n".join([method, path, query, hashlib.sha256(body).hexdigest(), actor, timestamp, nonce]).encode()


async def principal(request: Request, db: AsyncSession = Depends(get_db)) -> Actor:
    integration_signature = request.headers.get("X-Shirin-Signature")
    if integration_signature:
        settings = get_settings()
        actor_id = request.headers.get("X-Shirin-Actor", "")
        timestamp = request.headers.get("X-Shirin-Timestamp", "")
        nonce = request.headers.get("X-Shirin-Nonce", "")
        try:
            valid_time = abs(time.time() - int(timestamp)) <= 60
            uid = int(actor_id)
        except ValueError:
            raise HTTPException(401, "invalid_integration") from None
        if (
            not settings.market_integration_secret
            or uid not in settings.superadmin_allowed_ids
            or not valid_time
            or not (16 <= len(nonce) <= 64)
        ):
            raise HTTPException(401, "invalid_integration")
        body = request.state.integration_body if hasattr(request.state, "integration_body") else await request.body()
        message = signed_value(request.method, request.url.path, request.url.query, body, actor_id, timestamp, nonce)
        expected = hmac.new(settings.market_integration_secret.encode(), message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, integration_signature):
            raise HTTPException(401, "invalid_integration")
        await db.execute(delete(IntegrationNonce).where(IntegrationNonce.expires_at < now()))
        try:
            async with db.begin_nested():
                db.add(IntegrationNonce(id=nonce, expires_at=now() + timedelta(minutes=2)))
                await db.flush()
        except IntegrityError:
            raise HTTPException(401, "integration_replay") from None
        user = await ensure_customer(db, uid, f"market_{uid}")
        return await actor_for_user(db, user)
    user = await get_user_from_bearer(db, request.headers.get("Authorization"))
    if not user:
        raise HTTPException(401, "login_required")
    return await actor_for_user(db, user)


async def menu_editor(actor: Actor = Depends(principal)) -> Actor:
    actor.require(Permission.CAN_EDIT_MENU)
    return actor


async def order_manager(actor: Actor = Depends(principal)) -> Actor:
    actor.require(Permission.CAN_LOOK_ORDERS)
    return actor
