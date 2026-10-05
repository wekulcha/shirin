"""Bot construction shared by polling, webhooks and order notifications."""

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from app.config import get_settings


def create_bot(role: str) -> Bot:
    settings = get_settings()
    token = settings.bot_token_for(role)
    if not token:
        raise RuntimeError(f"SHIRIN_{role.upper()}_BOT_TOKEN is required")
    session = AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    return Bot(token=token, session=session)
