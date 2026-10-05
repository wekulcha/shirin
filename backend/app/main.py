import hmac
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.config import get_settings
from app.database import async_session
from app.models import WebhookUpdate
from app.routers.api import router

settings = get_settings()
app = FastAPI(title="Shirin", version="1.0.0", docs_url="/shirin/api/docs", openapi_url="/shirin/api/openapi.json", redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)


@app.middleware("http")
async def request_limits(request: Request, call_next):
    try:
        size = int(request.headers.get("Content-Length", "0"))
    except ValueError:
        return JSONResponse({"detail": "invalid_request"}, status_code=400)
    if size > settings.max_upload_bytes + 65536:
        return JSONResponse({"detail": "file_too_large"}, status_code=413)
    origin = request.headers.get("Origin")
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and origin and origin not in settings.cors_allowed_origins:
        return JSONResponse({"detail": "invalid_origin"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "validation_error", "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}, status_code=422)


@app.exception_handler(IntegrityError)
@app.exception_handler(StaleDataError)
async def conflict_error(request: Request, exc: Exception):
    return JSONResponse({"detail": "conflict_retry"}, status_code=409)


@app.get("/shirin/api/health")
async def health():
    return {"status": "ok", "project": "shirin"}


@app.post("/shirin/webhooks/telegram/")
@app.post("/shirin/webhooks/telegram/{bot_role}/")
async def webhook(request: Request, bot_role: Literal["user", "admin", "superadmin"] = "user"):
    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if (
        settings.bot_mode != "webhook"
        or not settings.bot_token_for(bot_role)
        or not settings.webhook_secret
        or not hmac.compare_digest(received, settings.webhook_secret)
    ):
        raise HTTPException(403, "invalid_webhook")
    if int(request.headers.get("Content-Length", "0")) > 1048576:
        raise HTTPException(413, "file_too_large")
    try:
        from aiogram.types import Update

        body = await request.json()
        update = Update.model_validate(body)
    except (ValueError, TypeError):
        raise HTTPException(422, "invalid_update") from None
    async with async_session() as db:
        if not await db.get(WebhookUpdate, (update.update_id, bot_role)):
            db.add(WebhookUpdate(id=update.update_id, bot_role=bot_role, payload=body))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()  # Telegram redelivery was already persisted.
    return {"ok": True}
