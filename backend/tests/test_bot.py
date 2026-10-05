import io
from datetime import timedelta

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, PhotoSize, Update
from aiogram.types import User as TelegramUser
from app.bot import cancel_command, confirm, dispatcher, menu, select_product, set_state, uploaded_file
from app.config import get_settings
from app.database import async_session
from app.models import BotState, Product
from app.models.business import now
from app.services.notifications import TelegramTransport
from conftest import add_product
from PIL import Image


class FakeMessage:
    def __init__(self, uid=101, content=None):
        self.from_user = TelegramUser(id=uid, is_bot=False, first_name="Synthetic")
        self.chat = Chat(id=uid, type="private")
        self.document = None
        self.photo = [PhotoSize(file_id="fake", file_unique_id="unique", width=10, height=10, file_size=100)] if content else None
        self.responses = []
        self.keyboards = []

    async def answer(self, text, **kwargs):
        self.responses.append(text)
        self.keyboards.append(kwargs.get("reply_markup"))

    async def answer_photo(self, photo, **kwargs):
        self.responses.append(kwargs)

    async def edit_reply_markup(self, **kwargs):
        return None


class FakeCallback:
    def __init__(self, uid, data):
        self.from_user = TelegramUser(id=uid, is_bot=False, first_name="Synthetic")
        self.message = FakeMessage(uid)
        self.data = data
        self.responses = []

    async def answer(self, text=None, **kwargs):
        self.responses.append(text)


class DownloadBot:
    def __init__(self, content):
        self.content = content

    async def download(self, file, destination):
        destination.write(self.content)


async def test_bot_photo_bound_to_actor_product_and_confirmation(client, headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_role", "admin")
    first = await add_product(client, headers)
    second = await add_product(client, headers, sku="other")
    async with async_session() as db:
        await set_state(db, 101, "photo_select", {"token": "user-101-token"})
        await set_state(db, 404, "photo_select", {"token": "user-404-token"})
        await db.commit()
    await select_product(FakeCallback(101, f"select:user-101-token:{first['id']}"))
    await select_product(FakeCallback(404, f"select:user-404-token:{second['id']}"))
    content = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(content, "PNG")
    await uploaded_file(FakeMessage(101, content), DownloadBot(content.getvalue()))
    async with async_session() as db:
        state = await db.get(BotState, 101)
        token = state.payload["token"]
        assert state.kind == "photo_confirm"
        assert (await db.get(Product, first["id"])).photo_reference is None
    await confirm(FakeCallback(404, "confirm:" + token))
    async with async_session() as db:
        assert (await db.get(Product, first["id"])).photo_reference is None
    await confirm(FakeCallback(101, "confirm:" + token))
    async with async_session() as db:
        assert (await db.get(Product, first["id"])).photo_reference
        assert (await db.get(Product, second["id"])).photo_reference is None
        assert await db.get(BotState, 101) is None


async def test_bot_stale_state_and_permission_revocation(client, headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "bot_role", "admin")
    product = await add_product(client, headers)
    async with async_session() as db:
        state = await set_state(
            db, 101, "archive_confirm", {"token": "expired", "product_id": product["id"], "version": product["version"]}
        )
        state.expires_at = now() - timedelta(seconds=1)
        await db.commit()
    await confirm(FakeCallback(101, "confirm:expired"))
    async with async_session() as db:
        assert (await db.get(Product, product["id"])).is_active
    async with async_session() as db:
        await set_state(db, 202, "archive_confirm", {"token": "no-rights", "product_id": product["id"], "version": product["version"]})
        await db.commit()
    await confirm(FakeCallback(202, "confirm:no-rights"))
    async with async_session() as db:
        assert (await db.get(Product, product["id"])).is_active


async def test_bot_superadmin_entry_only_for_allowlisted_user():
    for uid, allowed in ((101, True), (404, False), (303, False), (202, False)):
        message = FakeMessage(uid)
        await menu(message, bot_role="superadmin")
        markup = message.keyboards[-1]
        urls = [button.web_app.url for row in markup.inline_keyboard for button in row if button.web_app] if markup else []
        assert (get_settings().superadmin_app_url in urls) is allowed


async def test_other_bots_cannot_consume_or_cancel_admin_dialog(client, headers):
    product = await add_product(client, headers)
    async with async_session() as db:
        await set_state(db, 101, "archive_confirm", {"token": "admin-only", "product_id": product["id"], "version": product["version"]})
        await db.commit()
    for role in ("user", "superadmin"):
        await cancel_command(FakeMessage(101), bot_role=role)
        await confirm(FakeCallback(101, "confirm:admin-only"), bot_role=role)
        async with async_session() as db:
            assert (await db.get(Product, product["id"])).is_active
            assert await db.get(BotState, 101) is not None
    await confirm(FakeCallback(101, "confirm:admin-only"), bot_role="admin")
    async with async_session() as db:
        assert not (await db.get(Product, product["id"])).is_active
        assert await db.get(BotState, 101) is None


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""


@pytest.mark.parametrize("role", ("user", "admin", "superadmin"))
async def test_dispatcher_launches_only_its_panel(role):
    settings = get_settings()
    session = RecordingSession()
    bot = Bot(settings.bot_token_for(role), session=session)
    update = Update.model_validate({
        "update_id": 1,
        "message": {"message_id": 1, "date": 1, "chat": {"id": 101, "type": "private"},
                    "text": "/start", "from": {"id": 101, "is_bot": False, "first_name": "Test"}},
    })
    await dispatcher(role).feed_update(bot, update)
    assert len(session.sent) == 1
    urls = [button.web_app.url for row in session.sent[0].reply_markup.inline_keyboard for button in row if button.web_app]
    expected = {"user": settings.mini_app_url, "admin": settings.admin_app_url, "superadmin": settings.superadmin_app_url}
    assert urls == [expected[role]]


async def test_group_sender_uses_admin_bot_and_supports_proxy(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "user_bot_token", "")
    monkeypatch.setattr(settings, "telegram_proxy_url", "http://127.0.0.1:3128")
    transport = TelegramTransport()
    try:
        assert transport.bot.id == int(settings.admin_bot_token.split(":")[0])
    finally:
        await transport.close()
