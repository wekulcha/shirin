from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Customer, ImportLog, ImportPreview, Media, Order, OrderEvent, Outbox, Product, Staff, User
from app.models.business import Permission
from app.schemas import AccessInput, Checkout, CreateOrder, CustomerInput, CustomerUpdate, Login, ProductInput, ProductUpdate, Transition
from app.services.access import Actor, actor_for_user, menu_editor, order_manager, principal
from app.services.catalog import save_customer, save_product, serialize
from app.services.excel import apply_import, build_workbook, preview_import
from app.services.media import attach_product_photo, media_url, upload_media
from app.services.orders import create_order, get_order, order_dto, quote, transition
from app.services.session_auth import (
    REFRESH_COOKIE_NAME,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_session,
    ensure_customer,
    revoke_refresh_session,
    rotate_refresh_session,
    set_refresh_cookie,
)
from app.services.telegram_auth import verify_telegram_init_data

router = APIRouter(prefix="/shirin/api")


def actor_dto(actor: Actor) -> dict:
    return {"id": actor.user.id, "username": actor.user.username, "permissions": sorted(actor.permissions), "superadmin": actor.superadmin}


@router.post("/auth/telegram")
async def login(body: Login, response: Response, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    tg = verify_telegram_init_data(body.init_data, settings.user_bot_token, settings.init_data_ttl_seconds)
    if not tg:
        raise HTTPException(401, "invalid_telegram_data")
    user = await ensure_customer(db, tg["id"], tg.get("username") or tg.get("first_name"))
    access_token, expiry = create_access_token(user.id)
    refresh_token, refresh_expiry = await create_refresh_session(db, user.id)
    set_refresh_cookie(response, refresh_token, refresh_expiry)
    return {
        "accessToken": access_token,
        "accessTokenExpiresAt": expiry.isoformat() + "Z",
        "user": actor_dto(await actor_for_user(db, user)),
    }


def check_cookie_origin(request: Request):
    origin = request.headers.get("Origin")
    if origin not in get_settings().cors_allowed_origins:
        raise HTTPException(403, "invalid_origin")


@router.post("/auth/refresh")
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db), cookie: str | None = Cookie(None, alias=REFRESH_COOKIE_NAME)
):
    check_cookie_origin(request)
    if not cookie:
        raise HTTPException(401, "login_required")
    rotated = await rotate_refresh_session(db, cookie)
    if not rotated:
        raise HTTPException(401, "login_required")
    user, token, expires = rotated
    access, expiry = create_access_token(user.id)
    set_refresh_cookie(response, token, expires)
    return {"accessToken": access, "accessTokenExpiresAt": expiry.isoformat() + "Z", "user": actor_dto(await actor_for_user(db, user))}


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db), cookie: str | None = Cookie(None, alias=REFRESH_COOKIE_NAME)
):
    check_cookie_origin(request)
    await revoke_refresh_session(db, cookie)
    clear_refresh_cookie(response)


@router.get("/auth/me")
async def me(actor: Actor = Depends(principal)):
    return actor_dto(actor)


@router.get("/products")
async def products(
    q: str = Query("", max_length=200),
    brand: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=100),
    admin: bool = False,
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(principal),
    db: AsyncSession = Depends(get_db),
):
    query = select(Product)
    if admin:
        actor.require(Permission.CAN_EDIT_MENU)
    else:
        query = query.where(Product.is_active)
    if brand:
        query = query.where(Product.brand == brand)
    if category:
        query = query.where(Product.category == category)
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(
                Product.sku.ilike(pattern),
                Product.name_ru.ilike(pattern),
                Product.name_uz.ilike(pattern),
                Product.category.ilike(pattern),
                Product.brand.ilike(pattern),
            )
        )
    return [serialize(p) for p in (await db.scalars(query.order_by(Product.id).offset(offset).limit(200))).all()]


@router.get("/catalog/meta")
async def catalog_meta(actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    categories = (await db.scalars(select(Product.category).where(Product.is_active).distinct().order_by(Product.category))).all()
    return {"categories": categories}


@router.post("/products", status_code=201)
async def add_product(body: ProductInput, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    return serialize(await save_product(db, actor, body))


@router.put("/products/{product_id}")
async def edit_product(product_id: int, body: ProductUpdate, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    return serialize(await save_product(db, actor, body, product_id, body.version))


@router.post("/products/{product_id}/photo")
async def product_photo(product_id: int, file: UploadFile, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "product_not_found")
    media = await upload_media(db, actor, await file.read(get_settings().max_upload_bytes + 1), "product")
    await attach_product_photo(db, actor, product, media)
    return serialize(product)


@router.get("/customers")
async def customers(
    q: str = Query("", max_length=200),
    admin: bool = False,
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(principal),
    db: AsyncSession = Depends(get_db),
):
    query = select(Customer)
    if admin:
        actor.require(Permission.CAN_EDIT_MENU)
    else:
        query = query.where(Customer.is_active)
    if not actor.has(Permission.CAN_LOOK_ORDERS) and not actor.has(Permission.CAN_EDIT_MENU):
        own_ids = select(Order.customer_id).where(Order.author_id == actor.user.id)
        query = query.where(or_(Customer.created_by == actor.user.id, Customer.id.in_(own_ids)))
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(Customer.code.ilike(pattern), Customer.name.ilike(pattern), Customer.phone.ilike(pattern), Customer.address.ilike(pattern))
        )
    return [serialize(c) for c in (await db.scalars(query.order_by(Customer.name).offset(offset).limit(200))).all()]


@router.post("/customers", status_code=201)
async def add_customer(body: CustomerInput, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    return serialize(await save_customer(db, actor, body))


@router.put("/customers/{customer_id}")
async def edit_customer(customer_id: int, body: CustomerUpdate, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    return serialize(await save_customer(db, actor, body, customer_id, body.version))


@router.post("/orders/quote")
async def order_quote(body: Checkout, actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    return await quote(db, actor, body)


@router.post("/orders", status_code=201)
async def add_order(body: CreateOrder, actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    return order_dto(await create_order(db, actor, body))


@router.get("/orders")
async def orders(
    q: str = Query("", max_length=200),
    status: str | None = None,
    payment_status: str | None = None,
    offset: int = Query(0, ge=0),
    actor: Actor = Depends(principal),
    db: AsyncSession = Depends(get_db),
):
    query = select(Order)
    if not actor.has(Permission.CAN_LOOK_ORDERS):
        query = query.where(Order.author_id == actor.user.id)
    if status:
        query = query.where(Order.status == status)
    if payment_status:
        query = query.where(Order.payment_status == payment_status)
    if q:
        pattern = f"%{q}%"
        numeric_id = int(q.removeprefix("SH-")) if q.removeprefix("SH-").isdigit() else -1
        query = query.where(
            or_(
                Order.id == numeric_id,
                Order.customer_snapshot["name"].as_string().ilike(pattern),
                Order.customer_snapshot["phone"].as_string().ilike(pattern),
            )
        )
    return [order_dto(o) for o in (await db.scalars(query.order_by(Order.id.desc()).offset(offset).limit(200))).all()]


@router.get("/orders/{order_id}")
async def order_detail(order_id: int, actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    order = await get_order(db, actor, order_id)
    events = (await db.scalars(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id))).all()
    result = order_dto(order)
    result["events"] = [serialize(e) for e in events]
    if actor.has(Permission.CAN_LOOK_ORDERS):
        result["notifications"] = [serialize(e) for e in (await db.scalars(select(Outbox).where(Outbox.order_id == order_id))).all()]
        for notification in result["notifications"]:
            notification.pop("payload", None)
    return result


@router.patch("/orders/{order_id}")
async def order_transition(order_id: int, body: Transition, actor: Actor = Depends(order_manager), db: AsyncSession = Depends(get_db)):
    return order_dto(await transition(db, actor, order_id, body))


@router.post("/orders/{order_id}/customer")
async def link_customer(order_id: int, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    # Catalog editors may create clients; only order managers may read another user's contact snapshot.
    order = await get_order(db, actor, order_id, lock=True)
    if order.customer_id:
        return serialize(await db.get(Customer, order.customer_id))
    customer = await save_customer(db, actor, CustomerInput.model_validate(order.customer_snapshot))
    order.customer_id = customer.id
    db.add(OrderEvent(order_id=order.id, actor_id=actor.user.id, before={"customer_id": None}, after={"customer_id": customer.id}))
    await db.flush()
    return serialize(customer)


@router.post("/media/upload")
async def upload(file: UploadFile, kind: str = "store", actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    media = await upload_media(db, actor, await file.read(get_settings().max_upload_bytes + 1), kind)
    return {"path": media_url(media)}


@router.get("/media/{media_id}")
async def image(media_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    media = await db.get(Media, media_id)
    if not media:
        raise HTTPException(404, "image_not_found")
    if media.kind == "store":
        actor = await principal(request, db)
        permitted = media.owner_id == actor.user.id or actor.has(Permission.CAN_LOOK_ORDERS) or actor.has(Permission.CAN_EDIT_MENU)
        if not permitted:
            reference = media_url(media)
            permitted = bool(
                await db.scalar(
                    select(Order.id)
                    .where(Order.author_id == actor.user.id, Order.customer_snapshot["photo_reference"].as_string() == reference)
                    .limit(1)
                )
            )
            if not permitted:
                own_ids = select(Order.customer_id).where(Order.author_id == actor.user.id)
                permitted = bool(
                    await db.scalar(
                        select(Customer.id)
                        .where(Customer.photo_reference == reference, or_(Customer.created_by == actor.user.id, Customer.id.in_(own_ids)))
                        .limit(1)
                    )
                )
        if not permitted:
            raise HTTPException(403, "access_denied")
    headers = {"Cache-Control": "private, no-store" if media.kind == "store" else "public, max-age=31536000, immutable"}
    if media.storage_path.startswith("https://"):
        return RedirectResponse(media.storage_path, headers=headers)
    if not Path(media.storage_path).is_file():
        raise HTTPException(404, "image_not_found")
    return FileResponse(media.storage_path, media_type=media.content_type, headers=headers)


@router.get("/catalog/export")
async def export(template: bool = False, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    import asyncio

    products = [] if template else (await db.scalars(select(Product).order_by(Product.sku))).all()
    workbook = await asyncio.to_thread(build_workbook, products, template)
    return Response(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="shirin-{"template" if template else "catalog"}.xlsx"'},
    )


@router.post("/catalog/preview")
async def import_preview(file: UploadFile, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "invalid_workbook")
    return serialize(await preview_import(db, actor, await file.read(get_settings().max_upload_bytes + 1)))


@router.get("/catalog/previews/{preview_id}")
async def read_preview(preview_id: str, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    preview = await db.get(ImportPreview, preview_id)
    if not preview or preview.actor_id != actor.user.id:
        raise HTTPException(404, "preview_not_found")
    return serialize(preview)


@router.post("/catalog/previews/{preview_id}/apply")
async def import_apply(preview_id: str, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    return await apply_import(db, actor, preview_id)


@router.post("/catalog/previews/{preview_id}/cancel")
async def import_cancel(preview_id: str, actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    preview = await db.scalar(select(ImportPreview).where(ImportPreview.id == preview_id).with_for_update())
    if not preview or preview.actor_id != actor.user.id:
        raise HTTPException(404, "preview_not_found")
    if preview.state == "PENDING":
        preview.state = "CANCELLED"
    return {"state": preview.state}


@router.get("/catalog/logs")
async def import_logs(actor: Actor = Depends(menu_editor), db: AsyncSession = Depends(get_db)):
    return [serialize(log) for log in (await db.scalars(select(ImportLog).order_by(ImportLog.id.desc()).limit(100))).all()]


@router.get("/access")
async def access_list(actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    actor.require_superadmin()
    users = (await db.scalars(select(User).order_by(User.registered_at.desc()).limit(200))).all()
    assignments = (await db.scalars(select(Staff))).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "is_active": u.is_active,
            "permissions": [s.permission for s in assignments if s.user_id == u.id],
        }
        for u in users
    ]


@router.put("/access")
async def update_access(body: AccessInput, actor: Actor = Depends(principal), db: AsyncSession = Depends(get_db)):
    actor.require_superadmin()
    user = await db.get(User, body.user_id)
    if not user:
        raise HTTPException(404, "user_must_start_bot")
    await db.execute(delete(Staff).where(Staff.user_id == user.id))
    for permission in set(body.permissions):
        db.add(Staff(user_id=user.id, permission=permission))
    return {"user_id": user.id, "permissions": sorted(set(body.permissions))}


@router.get("/settings")
async def settings_info(actor: Actor = Depends(principal)):
    if not actor.has(Permission.CAN_EDIT_MENU) and not actor.has(Permission.CAN_LOOK_ORDERS):
        raise HTTPException(403, "access_denied")
    s = get_settings()
    return {
        "project": "shirin",
        "currency": "UZS",
        "timezone": s.timezone,
        "mini_app_url": s.mini_app_url,
        "admin_app_url": s.admin_app_url,
        "bot_configured": bool(s.user_bot_token),
        "group_configured": bool(s.work_group_id),
        "integration_configured": bool(s.market_integration_secret),
        "max_upload_bytes": s.max_upload_bytes,
        "max_import_rows": s.max_import_rows,
    }
