"""Optional shared process for the three Shirin bots and notification delivery."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from functools import partial

from sqlalchemy.engine import make_url

from app.bot import run_bot
from app.config import Settings, get_settings
from app.database import engine
from app.services.notifications import run_worker

logger = logging.getLogger(__name__)
BOT_ROLES = ("user", "admin", "superadmin")
RETRY_DELAY = 5


def validate_settings(settings: Settings):
    tokens = [settings.bot_token_for(role).strip() for role in BOT_ROLES]
    if not all(tokens) or len(set(tokens)) != len(tokens):
        raise ValueError("Compact workers require three nonempty, distinct Shirin bot tokens")
    if (
        settings.bot_mode == "webhook"
        and make_url(settings.database_url).get_backend_name() == "postgresql"
        and settings.database_pool_size + settings.database_max_overflow < 5
    ):
        # Each bot holds its queue-row transaction while a handler opens another session.
        # Reserve space for three queue claims, notification delivery, and a handler.
        raise ValueError("Compact webhook workers require SHIRIN_DATABASE_POOL_SIZE + SHIRIN_DATABASE_MAX_OVERFLOW >= 5")


async def supervise(name: str, factory: Callable[[], Awaitable[None]], *, retry_delay: float = RETRY_DELAY):
    while True:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Exception messages can contain Telegram tokens or proxy credentials.
            logger.warning("Shirin %s stopped (%s); retrying in %s seconds", name, type(exc).__name__, retry_delay)
        else:
            logger.warning("Shirin %s stopped; retrying in %s seconds", name, retry_delay)
        await asyncio.sleep(retry_delay)


async def run_workers(stop_event: asyncio.Event | None = None):
    validate_settings(get_settings())
    loop = asyncio.get_running_loop()
    installed_signals = []
    if stop_event is None:
        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, RuntimeError):
                # asyncio.run still cancels this coroutine on Ctrl+C where unsupported.
                continue
            installed_signals.append(sig)
    services = {
        role: partial(run_bot, role, handle_signals=False, handle_as_tasks=False)
        for role in BOT_ROLES
    }
    services["notifications"] = run_worker
    tasks = [asyncio.create_task(supervise(name, factory), name=f"shirin-{name}") for name, factory in services.items()]
    logger.info("Shirin compact workers started: user, admin, superadmin, notifications")
    try:
        await stop_event.wait()
    finally:
        for sig in installed_signals:
            loop.remove_signal_handler(sig)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()
        logger.info("Shirin compact workers stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_workers())
