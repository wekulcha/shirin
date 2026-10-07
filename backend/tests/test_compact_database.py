"""Exercise nested webhook transactions against a real, bounded PostgreSQL pool."""

import asyncio

import pytest
from aiogram import Bot
from app import bot as bot_runtime
from app.config import get_settings
from app.database import async_session, database_engine
from app.models import WebhookUpdate
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_bot import RecordingSession


async def test_three_webhooks_make_progress_with_worker_holding_a_connection(monkeypatch):
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("Requires PostgreSQL row locks and bounded connection pool")
    # Five is the minimum accepted compact webhook capacity; deployed default
    # has six. Each poller keeps its row lock while the handler opens a session.
    bounded = database_engine(settings.model_copy(update={
        "database_pool_size": 4, "database_max_overflow": 1, "database_pool_timeout": 2,
    }))
    sessions = async_sessionmaker(bounded, expire_on_commit=False)
    monkeypatch.setattr(bot_runtime, "async_session", sessions)
    monkeypatch.setattr(settings, "bot_mode", "webhook")
    roles = {"user": 202, "admin": 404, "superadmin": 101}
    transports = {role: RecordingSession() for role in roles}
    monkeypatch.setattr(bot_runtime, "create_bot", lambda role: Bot(settings.bot_token_for(role), session=transports[role]))
    entered = set()
    all_entered = asyncio.Event()
    original_dispatcher = bot_runtime.dispatcher

    def dispatcher(role):
        dp = original_dispatcher(role)

        async def barrier(handler, event, data):
            entered.add(role)
            if len(entered) == 3:
                all_entered.set()
            await asyncio.wait_for(all_entered.wait(), 3)
            return await handler(event, data)

        dp.update.outer_middleware(barrier)
        return dp

    monkeypatch.setattr(bot_runtime, "dispatcher", dispatcher)
    async with async_session() as db:
        for role, uid in roles.items():
            db.add(WebhookUpdate(id=1, bot_role=role, payload={
                "update_id": 1,
                "message": {"message_id": 1, "date": 1, "chat": {"id": uid, "type": "private"},
                            "text": "/start", "from": {"id": uid, "is_bot": False, "first_name": "Test"}},
            }))
        await db.commit()

    tasks = []
    try:
        async with bounded.connect() as worker_connection:
            assert await worker_connection.scalar(text("SELECT 1")) == 1
            tasks = [asyncio.create_task(bot_runtime.run_bot(role)) for role in roles]

            async def completed():
                while True:
                    # Observe via the fixture's separate pool, leaving the
                    # compact pool available only to workers and handlers.
                    async with async_session() as db:
                        states = (await db.scalars(select(WebhookUpdate.state))).all()
                    if states == ["DONE"] * 3:
                        return
                    await asyncio.sleep(0.02)

            await asyncio.wait_for(completed(), 5)
            expected = {"user": settings.mini_app_url, "admin": settings.admin_app_url, "superadmin": settings.superadmin_app_url}
            for role, transport in transports.items():
                assert len(transport.sent) == 1
                urls = [button.web_app.url for row in transport.sent[0].reply_markup.inline_keyboard
                        for button in row if button.web_app]
                assert urls == [expected[role]]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bounded.dispose()
