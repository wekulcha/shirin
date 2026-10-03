import asyncio
import io
import secrets
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Media, Product
from app.models.business import Permission, now
from app.services.access import Actor
from app.services.object_storage import ObjectStorageNotConfiguredError, get_object_storage


def checked_image(content: bytes) -> tuple[bytes, str, str]:
    if not content or len(content) > get_settings().max_upload_bytes:
        raise HTTPException(413, "file_too_large")
    try:
        with Image.open(io.BytesIO(content)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP") or im.width * im.height > 30_000_000:
                raise HTTPException(422, "invalid_image")
            im.verify()
        with Image.open(io.BytesIO(content)) as im:
            im = im.convert("RGB")
            im.thumbnail((2400, 2400))
            output = io.BytesIO()
            im.save(output, "JPEG", quality=90)
            return output.getvalue(), "image/jpeg", ".jpg"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise HTTPException(422, "invalid_image") from None


async def upload_media(db: AsyncSession, actor: Actor, content: bytes, kind: str) -> Media:
    if kind == "product":
        actor.require(Permission.CAN_EDIT_MENU)
    if kind not in ("product", "store"):
        raise HTTPException(422, "invalid_image")
    content, content_type, extension = await asyncio.to_thread(checked_image, content)
    mid = secrets.token_hex(20)
    storage_path = ""
    if kind == "product":
        try:
            storage = get_object_storage()
            key = storage.build_asset_key("shirin/products", 1, content_type)
            storage_path = await storage.upload_file(io.BytesIO(content), key=key, content_type=content_type)
        except ObjectStorageNotConfiguredError:
            pass
    if not storage_path:
        folder = Path(get_settings().uploads_dir, kind)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        file = folder / (mid + extension)
        await asyncio.to_thread(file.write_bytes, content)
        storage_path = str(file.resolve())
    media = Media(id=mid, owner_id=actor.user.id, kind=kind, storage_path=storage_path, content_type=content_type)
    db.add(media)
    await db.flush()
    return media


def media_url(media: Media) -> str:
    return f"/shirin/api/media/{media.id}"


async def attach_product_photo(db: AsyncSession, actor: Actor, product: Product, media: Media):
    actor.require(Permission.CAN_EDIT_MENU)
    if media.owner_id != actor.user.id or media.kind != "product":
        raise HTTPException(403, "access_denied")
    product.photo_reference = media_url(media)
    product.updated_at = now()
    await db.flush()
