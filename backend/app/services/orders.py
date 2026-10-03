import hashlib
import hmac
import json
import time
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Order, OrderEvent, Outbox, Product
from app.models.business import Permission, now
from app.schemas import Checkout, CreateOrder, Transition
from app.services.access import Actor
from app.services.catalog import save_customer, serialize, validate_customer_photo, visible_customer


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checkout_values(data: Checkout) -> dict:
    return data.model_dump(mode="json", exclude={"attempt_key", "quote_token"})


async def priced_lines(db: AsyncSession, data: Checkout, lock: bool = False) -> tuple[list[dict], Decimal]:
    ids = sorted({line.product_id for line in data.lines})
    query = select(Product).where(Product.id.in_(ids)).order_by(Product.id)
    if lock:
        query = query.with_for_update()
    products = {p.id: p for p in (await db.scalars(query)).all()}
    lines = []
    total = Decimal("0.00")
    for line in data.lines:
        product = products.get(line.product_id)
        if not product or not product.is_active or not getattr(product, f"sell_by_{line.sale_format}"):
            raise HTTPException(409, "product_unavailable")
        price = getattr(product, f"{line.sale_format}_price_uzs")
        size = product.units_per_package if line.sale_format == "package" else 1
        amount = (price * line.quantity).quantize(Decimal(".01"))
        total += amount
        if total >= Decimal("1000000000000000"):
            raise HTTPException(422, "order_too_large")
        lines.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name_ru": product.name_ru,
                "name_uz": product.name_uz,
                "sale_format": line.sale_format,
                "units_per_package": size,
                "quantity": line.quantity,
                "base_units": size * line.quantity,
                "price_uzs": str(price),
                "amount_uzs": str(amount),
            }
        )
    return lines, total


def quote_signature(actor: Actor, values: dict, lines: list, expires: int) -> str:
    secret = get_settings().auth_access_secret
    if not secret:
        raise HTTPException(503, "auth_not_configured")
    message = canonical({"actor": actor.user.id, "checkout": values, "lines": lines, "expires": expires})
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


async def quote(db: AsyncSession, actor: Actor, data: Checkout) -> dict:
    if data.customer_id:
        await visible_customer(db, actor, data.customer_id)
    await validate_customer_photo(db, actor, data.customer.photo_reference)
    if data.save_customer:
        actor.require(Permission.CAN_EDIT_MENU)
    lines, total = await priced_lines(db, data)
    expires = int(time.time()) + 600
    return {
        "lines": lines,
        "total_uzs": str(total),
        "currency": "UZS",
        "expires_at": expires,
        "quote_token": f"{expires}.{quote_signature(actor, checkout_values(data), lines, expires)}",
    }


async def create_order(db: AsyncSession, actor: Actor, data: CreateOrder) -> Order:
    request_hash = hashlib.sha256(canonical(checkout_values(data)).encode()).hexdigest()
    existing = await db.scalar(select(Order).where(Order.author_id == actor.user.id, Order.attempt_key == data.attempt_key))
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "attempt_already_used")
        return existing
    if data.customer_id:
        await visible_customer(db, actor, data.customer_id)
    await validate_customer_photo(db, actor, data.customer.photo_reference)
    lines, total = await priced_lines(db, data, lock=True)
    try:
        expires_str, signature = data.quote_token.split(".", 1)
        expires = int(expires_str)
    except ValueError:
        raise HTTPException(409, "quote_expired") from None
    expected = quote_signature(actor, checkout_values(data), lines, expires)
    if expires < time.time() or expires > time.time() + 610 or not hmac.compare_digest(signature, expected):
        raise HTTPException(409, "conditions_changed")
    try:
        async with db.begin_nested():
            customer_id = data.customer_id
            snapshot = data.customer.model_dump(mode="json")
            if data.save_customer and not customer_id:
                customer = await save_customer(db, actor, data.customer)
                customer_id = customer.id
                snapshot["code"] = customer.code
            order = Order(
                author_id=actor.user.id,
                attempt_key=data.attempt_key,
                request_hash=request_hash,
                customer_id=customer_id,
                customer_snapshot=snapshot,
                author_snapshot={"id": actor.user.id, "name": actor.user.username},
                lines=lines,
                total_uzs=total,
                status="ACCEPTED",
                payment_status="UNPAID",
            )
            db.add(order)
            await db.flush()
            db.add(
                OrderEvent(order_id=order.id, actor_id=actor.user.id, before={}, after={"status": "ACCEPTED", "payment_status": "UNPAID"})
            )
            await queue_notification(db, order, "created")
    except IntegrityError:
        existing = await db.scalar(select(Order).where(Order.author_id == actor.user.id, Order.attempt_key == data.attempt_key))
        if not existing or existing.request_hash != request_hash:
            raise HTTPException(409, "conflict_retry") from None
        return existing
    return order


async def queue_notification(db: AsyncSession, order: Order, kind: str):
    db.add(
        Outbox(event_key=f"order:{order.id}:{kind}:{order.version}", order_id=order.id, payload={"kind": kind, "order": order_dto(order)})
    )
    await db.flush()


def order_dto(order: Order) -> dict:
    values = serialize(order)
    values.pop("request_hash", None)
    values.pop("attempt_key", None)
    values["number"] = f"SH-{order.id:06d}"
    values["currency"] = "UZS"
    return values


async def get_order(db: AsyncSession, actor: Actor, order_id: int, lock: bool = False) -> Order:
    query = select(Order).where(Order.id == order_id)
    if lock:
        query = query.with_for_update()
    order = await db.scalar(query)
    if not order:
        raise HTTPException(404, "order_not_found")
    if order.author_id != actor.user.id and not actor.has(Permission.CAN_LOOK_ORDERS):
        raise HTTPException(403, "access_denied")
    return order


async def transition(db: AsyncSession, actor: Actor, order_id: int, data: Transition) -> Order:
    actor.require(Permission.CAN_LOOK_ORDERS)
    order = await get_order(db, actor, order_id, lock=True)
    before = {"status": order.status, "payment_status": order.payment_status}
    if data.status and data.status != order.status and order.status != "COMPLETED":
        allowed = {"ACCEPTED": "READY", "READY": "DELIVERED"}
        if allowed.get(order.status) != data.status:
            raise HTTPException(409, "invalid_transition")
        order.status = data.status
        if data.status == "DELIVERED":
            order.delivered_at = now()
    if data.payment_status == "PAID" and order.payment_status != "PAID":
        order.payment_status = "PAID"
        order.paid_at = now()
    if order.delivered_at and order.payment_status == "PAID":
        order.status = "COMPLETED"
    after = {"status": order.status, "payment_status": order.payment_status}
    if before != after:
        await db.flush()
        db.add(OrderEvent(order_id=order.id, actor_id=actor.user.id, before=before, after=after))
        await queue_notification(db, order, "updated")
    return order
