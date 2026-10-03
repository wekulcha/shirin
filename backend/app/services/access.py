from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Staff, User
from app.models.business import Permission
from app.services.session_auth import get_user_from_bearer


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


async def principal(request: Request, db: AsyncSession = Depends(get_db)) -> Actor:
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


async def superadmin(actor: Actor = Depends(principal)) -> Actor:
    actor.require_superadmin()
    return actor
