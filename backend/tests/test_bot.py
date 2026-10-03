import io
from datetime import timedelta

from aiogram.types import Chat, PhotoSize
from aiogram.types import User as TelegramUser
from app.bot import confirm, menu, select_product, set_state, uploaded_file
from app.config import get_settings
from app.database import async_session
from app.models import BotState, Product
from app.models.business import now
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


async def test_bot_photo_bound_to_actor_product_and_confirmation(client, headers):
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


async def test_bot_stale_state_and_permission_revocation(client, headers):
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
        await menu(message)
        urls = [button.web_app.url for row in message.keyboards[-1].inline_keyboard for button in row if button.web_app]
        assert (get_settings().superadmin_app_url in urls) is allowed
