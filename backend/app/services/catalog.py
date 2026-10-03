from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Media, Order, Product
from app.models.business import Permission, now
from app.schemas import CustomerInput, ProductInput
from app.services.access import Actor


def serialize(obj) -> dict:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy import inspect

    values = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}
    return {k: str(v) if isinstance(v, Decimal) else v.isoformat() + "Z" if isinstance(v, datetime) else v for k, v in values.items()}


async def save_product(
    db: AsyncSession, actor: Actor, data: ProductInput, product_id: int | None = None, version: int | None = None
) -> Product:
    actor.require(Permission.CAN_EDIT_MENU)
    values = data.model_dump(exclude={"version"})
    if product_id:
        product = await db.scalar(select(Product).where(Product.id == product_id).with_for_update())
        if not product:
            raise HTTPException(404, "product_not_found")
        if version != product.version:
            raise HTTPException(409, "changed_since_preview")
        if values["sku"] != product.sku:
            raise HTTPException(422, "sku_immutable")
        for key, value in values.items():
            setattr(product, key, value)
        product.updated_at = now()
    else:
        if await db.scalar(select(Product.id).where(Product.sku == data.sku)):
            raise HTTPException(409, "duplicate_sku")
        product = Product(**values)
        db.add(product)
    await db.flush()
    return product


async def visible_customer(db: AsyncSession, actor: Actor, customer_id: int) -> Customer:
    customer = await db.get(Customer, customer_id)
    if not customer or not customer.is_active:
        raise HTTPException(404, "customer_not_found")
    if not actor.has(Permission.CAN_LOOK_ORDERS) and not actor.has(Permission.CAN_EDIT_MENU):
        own = customer.created_by == actor.user.id or await db.scalar(
            select(Order.id).where(Order.author_id == actor.user.id, Order.customer_id == customer_id).limit(1)
        )
        if not own:
            raise HTTPException(403, "access_denied")
    return customer


async def validate_customer_photo(db: AsyncSession, actor: Actor, photo: str | None):
    if not photo:
        return
    prefix = "/shirin/api/media/"
    if not photo.startswith(prefix) or "/" in photo[len(prefix) :]:
        raise HTTPException(422, "invalid_photo")
    media = await db.get(Media, photo[len(prefix) :])
    if not media or media.kind != "store":
        raise HTTPException(422, "invalid_photo")
    if media.owner_id != actor.user.id and not actor.has(Permission.CAN_LOOK_ORDERS) and not actor.has(Permission.CAN_EDIT_MENU):
        own_ids = select(Order.customer_id).where(Order.author_id == actor.user.id)
        from sqlalchemy import or_

        available = await db.scalar(
            select(Customer.id)
            .where(Customer.photo_reference == photo, or_(Customer.created_by == actor.user.id, Customer.id.in_(own_ids)))
            .limit(1)
        )
        if not available:
            raise HTTPException(403, "access_denied")


async def save_customer(
    db: AsyncSession, actor: Actor, data: CustomerInput, customer_id: int | None = None, version: int | None = None
) -> Customer:
    import uuid

    actor.require(Permission.CAN_EDIT_MENU)
    await validate_customer_photo(db, actor, data.photo_reference)
    values = data.model_dump(exclude={"version"})
    values["code"] = values["code"] or f"ST-{uuid.uuid4().hex[:10].upper()}"
    duplicate = await db.scalar(select(Customer.id).where(Customer.code == values["code"], Customer.id != (customer_id or 0)))
    if duplicate:
        raise HTTPException(409, "duplicate_store_code")
    if customer_id:
        customer = await db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
        if not customer:
            raise HTTPException(404, "customer_not_found")
        if version != customer.version:
            raise HTTPException(409, "changed_since_preview")
        for key, value in values.items():
            setattr(customer, key, value)
        customer.updated_at = now()
    else:
        customer = Customer(**values, created_by=actor.user.id)
        db.add(customer)
    await db.flush()
    return customer
