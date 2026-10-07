import asyncio
import signal
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetMe, GetUpdates, SendMessage
from aiogram.types import Update
from aiogram.types import User as TelegramUser
from app import bot as bot_module
from app import workers
from app.config import get_settings


def start_update(update_id=1):
    return Update.model_validate({
        "update_id": update_id,
        "message": {"message_id": update_id, "date": 1, "chat": {"id": 101, "type": "private"},
                    "text": "/start", "from": {"id": 101, "is_bot": False, "first_name": "Test"}},
    })


class PollingSession(BaseSession):
    """Exercise the real aiogram dispatcher without calling Telegram."""

    def __init__(self, updates=(), fail_get_me=False):
        super().__init__()
        self.updates = list(updates)
        self.fail_get_me = fail_get_me
        self.polling = asyncio.Event()
        self.closed = False
        self.active_requests = 0
        self.sent = []

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            if self.fail_get_me:
                raise RuntimeError("synthetic-secret-must-not-be-logged")
            return TelegramUser(id=bot.id, is_bot=True, first_name="Synthetic", username=f"test_{bot.id}_bot")
        if isinstance(method, GetUpdates):
            if self.updates:
                updates, self.updates = self.updates, []
                return updates
            self.active_requests += 1
            self.polling.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.active_requests -= 1
        if isinstance(method, SendMessage):
            self.sent.append(method)
            return True
        raise AssertionError(f"Unexpected Telegram method: {type(method).__name__}")

    async def close(self):
        assert self.active_requests == 0, "getUpdates must stop before closing its HTTP session"
        self.closed = True

    async def stream_content(self, *args, **kwargs):
        yield b""


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_compact_bots_keep_roles_restart_one_failure_and_close_polling(monkeypatch, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_mode", "polling")
    sessions = {role: [] for role in workers.BOT_ROLES}

    def create_bot(role):
        session = PollingSession([start_update()], fail_get_me=role == "user" and not sessions[role])
        sessions[role].append(session)
        return Bot(settings.bot_token_for(role), session=session)

    notification_started = asyncio.Event()
    notification_stopped = asyncio.Event()

    async def notifications():
        notification_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            notification_stopped.set()

    monkeypatch.setattr(bot_module, "create_bot", create_bot)
    monkeypatch.setattr(workers, "run_worker", notifications)
    monkeypatch.setattr(workers, "supervise", partial(workers.supervise, retry_delay=0.01))
    stop = asyncio.Event()
    running = asyncio.create_task(workers.run_workers(stop))
    try:
        await wait_until(lambda: all(sessions[role] and sessions[role][-1].polling.is_set() for role in workers.BOT_ROLES))
        assert notification_started.is_set()
        assert len(sessions["user"]) == 2
        assert len(sessions["admin"]) == len(sessions["superadmin"]) == 1
        assert sessions["user"][0].closed
        assert "RuntimeError" in caplog.text
        assert "synthetic-secret-must-not-be-logged" not in caplog.text
        expected_urls = {"user": settings.mini_app_url, "admin": settings.admin_app_url, "superadmin": settings.superadmin_app_url}
        for role, instances in sessions.items():
            sent = instances[-1].sent
            assert len(sent) == 1
            urls = [b.web_app.url for row in sent[0].reply_markup.inline_keyboard for b in row if b.web_app]
            assert urls == [expected_urls[role]]
    finally:
        stop.set()
        await asyncio.wait_for(running, 5)
    assert notification_stopped.is_set()
    assert all(session.closed and session.active_requests == 0 for instances in sessions.values() for session in instances)


async def test_compact_polling_handles_updates_sequentially_and_cancels_inflight_handler():
    session = PollingSession([start_update(1), start_update(2)])
    bot = Bot(get_settings().user_bot_token, session=session)
    dp = Dispatcher()
    entered = []
    first_started, first_stopped = asyncio.Event(), asyncio.Event()

    async def slow_handler(message):
        entered.append(message.message_id)
        first_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            first_stopped.set()

    dp.message.register(slow_handler)
    running = asyncio.create_task(bot_module.poll_bot(dp, bot, handle_signals=False, handle_as_tasks=False))
    try:
        await asyncio.wait_for(first_started.wait(), 5)
        await asyncio.sleep(0)
        assert entered == [1]
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 5)
        await bot.session.close()
    assert first_stopped.is_set()
    assert entered == [1]


async def test_cancelling_during_dispatcher_startup_closes_session(monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_mode", "polling")
    session = PollingSession()
    bot = Bot(get_settings().user_bot_token, session=session)
    dp = Dispatcher()
    startup = asyncio.Event()

    async def slow_startup(**kwargs):
        startup.set()
        await asyncio.Event().wait()

    dp.startup.register(slow_startup)
    monkeypatch.setattr(bot_module, "create_bot", lambda role: bot)
    monkeypatch.setattr(bot_module, "dispatcher", lambda role: dp)
    running = asyncio.create_task(bot_module.run_bot("user", handle_signals=False, handle_as_tasks=False))
    await asyncio.wait_for(startup.wait(), 5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 5)
    assert session.closed
    assert not session.polling.is_set()


async def test_shutdown_callback_failure_does_not_hang_polling_cleanup(monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_mode", "polling")
    session = PollingSession()
    bot = Bot(get_settings().user_bot_token, session=session)
    dp = Dispatcher()

    async def failed_shutdown(**kwargs):
        raise RuntimeError("synthetic shutdown failure")

    dp.shutdown.register(failed_shutdown)
    monkeypatch.setattr(bot_module, "create_bot", lambda role: bot)
    monkeypatch.setattr(bot_module, "dispatcher", lambda role: dp)
    running = asyncio.create_task(bot_module.run_bot("user", handle_signals=False, handle_as_tasks=False))
    await asyncio.wait_for(session.polling.wait(), 5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 5)
    assert session.closed


async def test_external_runner_cancellation_stops_services_and_disposes_pool(monkeypatch):
    started, stopped = set(), set()
    dispose = AsyncMock()

    async def service(name, **kwargs):
        started.add(name)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(name)

    monkeypatch.setattr(get_settings(), "bot_mode", "polling")
    monkeypatch.setattr(workers, "run_bot", service)
    monkeypatch.setattr(workers, "run_worker", partial(service, "notifications"))
    monkeypatch.setattr(workers, "engine", SimpleNamespace(dispose=dispose))
    running = asyncio.create_task(workers.run_workers(asyncio.Event()))
    await wait_until(lambda: len(started) == 4)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 5)
    assert stopped == started == {"user", "admin", "superadmin", "notifications"}
    dispose.assert_awaited_once()


@pytest.mark.parametrize("sig", (signal.SIGINT, signal.SIGTERM))
async def test_runner_handles_signals_without_bot_signal_handlers(monkeypatch, sig):
    installed, stopped = {}, set()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: installed.setdefault(sig, callback))
    monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: installed.pop(sig))
    monkeypatch.setattr(get_settings(), "bot_mode", "polling")

    async def service(role="notifications", **kwargs):
        if role != "notifications":
            assert kwargs == {"handle_signals": False, "handle_as_tasks": False}
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(role)

    monkeypatch.setattr(workers, "run_bot", service)
    monkeypatch.setattr(workers, "run_worker", service)
    running = asyncio.create_task(workers.run_workers())
    await wait_until(lambda: len(installed) == 2)
    installed[sig]()
    await asyncio.wait_for(running, 5)
    assert stopped == {"user", "admin", "superadmin", "notifications"}
    assert not installed


@pytest.mark.parametrize("token", ("", "   ", "same-as-user"))
def test_compact_requires_three_distinct_tokens(token):
    settings = get_settings().model_copy(update={"admin_bot_token": get_settings().user_bot_token if token == "same-as-user" else token})
    with pytest.raises(ValueError, match="three nonempty, distinct"):
        workers.validate_settings(settings)


def test_compact_webhook_pool_reserves_capacity_for_nested_handlers():
    settings = get_settings().model_copy(update={
        "database_url": "postgresql+asyncpg://synthetic@localhost/test", "bot_mode": "webhook",
        "database_pool_size": 2, "database_max_overflow": 2,
    })
    with pytest.raises(ValueError, match=">= 5"):
        workers.validate_settings(settings)
    workers.validate_settings(settings.model_copy(update={"database_max_overflow": 3}))
    workers.validate_settings(settings.model_copy(update={"bot_mode": "polling"}))
    workers.validate_settings(settings.model_copy(update={"database_url": "sqlite+aiosqlite://"}))
