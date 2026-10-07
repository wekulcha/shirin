import asyncio
import io
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path

import pytest
from app.config import get_settings
from app.services import media
from fastapi import HTTPException
from PIL import Image


def test_loading_media_without_s3_does_not_import_image_or_aws_libraries():
    program = '''
import sys
from app import config
settings = config.Settings(_env_file=None, environment="test", database_url="sqlite+aiosqlite:///:memory:", object_storage_bucket="")
config.get_settings = lambda: settings
from app.services import media
from app.services.object_storage import ObjectStorageService, ObjectStorageNotConfiguredError
try:
    ObjectStorageService(settings)
except ObjectStorageNotConfiguredError:
    pass
else:
    raise AssertionError("Unconfigured storage should fail before importing boto3")
assert "PIL.Image" not in sys.modules
assert "boto3" not in sys.modules
assert "botocore" not in sys.modules
'''
    subprocess.run([sys.executable, "-c", program], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)


def picture(image_format="PNG", mode="RGB", size=(30, 20)):
    output = io.BytesIO()
    with Image.new(mode, size) as source:
        source.save(output, image_format)
    return output.getvalue()


@pytest.mark.parametrize("image_format,mode", [("JPEG", "RGB"), ("JPEG", "CMYK"), ("JPEG", "L"), ("PNG", "RGBA"), ("PNG", "P"), ("WEBP", "RGBA")])
def test_image_formats_are_normalized_without_upscaling(image_format, mode):
    result, content_type, extension = media.checked_image(picture(image_format, mode))
    assert (content_type, extension) == ("image/jpeg", ".jpg")
    with Image.open(io.BytesIO(result)) as converted:
        assert converted.format == "JPEG"
        assert converted.mode == "RGB"
        assert converted.size == (30, 20)


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_large_image_is_resized_with_original_aspect_ratio(image_format):
    result, _, _ = media.checked_image(picture(image_format, size=(5000, 100)))
    with Image.open(io.BytesIO(result)) as converted:
        assert converted.size == (2400, 48)


@pytest.mark.parametrize("content", [b"not an image", picture("GIF"), picture()[:-20]])
def test_corrupt_and_unsupported_images_are_rejected(content):
    with pytest.raises(HTTPException) as exc:
        media.checked_image(content)
    assert (exc.value.status_code, exc.value.detail) == (422, "invalid_image")


def test_pixel_limit_is_checked_before_resize():
    # A valid PNG header claiming more than 30M pixels must be rejected before
    # attempting to decode it. No large image allocation is needed for this test.
    original = picture()
    ihdr = struct.pack(">II", 6000, 5001) + original[24:29]
    oversized = original[:16] + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr)) + original[33:]
    with pytest.raises(HTTPException) as exc:
        media.checked_image(oversized)
    assert (exc.value.status_code, exc.value.detail) == (422, "invalid_image")


def test_upload_size_limit_and_empty_image_are_preserved(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 100)
    for content in (b"", b"x" * 101):
        with pytest.raises(HTTPException) as exc:
            media.checked_image(content)
        assert (exc.value.status_code, exc.value.detail) == (413, "file_too_large")


async def test_cancelling_request_does_not_allow_concurrent_decodes(monkeypatch):
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()

    def decode(content):
        if content == b"first":
            first_started.set()
            assert first_release.wait(5)
        else:
            second_started.set()
        return content, "image/jpeg", ".jpg"

    monkeypatch.setattr(media, "checked_image", decode)
    first = asyncio.create_task(media.checked_image_async(b"first"))
    second = None
    try:
        assert await asyncio.to_thread(first_started.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(media.checked_image_async(b"second"))
        await asyncio.sleep(0)
        assert not await asyncio.to_thread(second_started.wait, 0.1)
        first_release.set()
        assert await asyncio.wait_for(second, timeout=2) == (b"second", "image/jpeg", ".jpg")
        assert second_started.is_set()
    finally:
        first_release.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
