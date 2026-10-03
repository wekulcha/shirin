from __future__ import annotations

import asyncio
import re
import uuid
from functools import lru_cache
from typing import BinaryIO
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings, get_settings

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg"}
ASSET_FILENAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
OBJECT_CACHE_CONTROL = "public, max-age=31536000, immutable"


class ObjectStorageNotConfiguredError(RuntimeError):
    pass


class ObjectStorageService:
    def __init__(self, settings: Settings):
        self._bucket = settings.object_storage_bucket.strip()
        self._public_base_url = settings.object_storage_public_base_url.strip().rstrip("/")

        missing = [
            name for name, value in (
                ("MARKET_OBJECT_STORAGE_ENDPOINT", settings.object_storage_endpoint),
                ("MARKET_OBJECT_STORAGE_REGION", settings.object_storage_region),
                ("MARKET_OBJECT_STORAGE_BUCKET", settings.object_storage_bucket),
                ("MARKET_OBJECT_STORAGE_ACCESS_KEY_ID", settings.object_storage_access_key_id),
                ("MARKET_OBJECT_STORAGE_SECRET_ACCESS_KEY", settings.object_storage_secret_access_key),
                ("MARKET_OBJECT_STORAGE_PUBLIC_BASE_URL", settings.object_storage_public_base_url),
            )
            if not value.strip()
        ]
        if missing:
            raise ObjectStorageNotConfiguredError(
                f"Object Storage is not configured. Missing: {', '.join(missing)}"
            )

        session = boto3.session.Session(
            aws_access_key_id=settings.object_storage_access_key_id,
            aws_secret_access_key=settings.object_storage_secret_access_key,
            region_name=settings.object_storage_region,
        )
        self._client = session.client(
            service_name="s3",
            endpoint_url=settings.object_storage_endpoint,
            config=Config(signature_version="s3v4"),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    @staticmethod
    def ensure_valid_filename(filename: str) -> None:
        if not ASSET_FILENAME_RE.match(filename):
            raise ValueError("Invalid filename")

    @staticmethod
    def normalize_content_type(content_type: str) -> str:
        return "image/jpeg" if content_type == "image/jpg" else content_type

    @staticmethod
    def extension_for_content_type(content_type: str) -> str:
        return ".png" if content_type == "image/png" else ".jpg"

    def build_asset_key(self, folder: str, restaurant_id: int, content_type: str) -> str:
        ext = self.extension_for_content_type(content_type)
        return f"{folder}/{restaurant_id}/{uuid.uuid4()}{ext}"

    def build_legacy_key(self, folder: str, filename: str) -> str:
        self.ensure_valid_filename(filename)
        return f"{folder}/legacy/{filename}"

    def public_url(self, key: str) -> str:
        return f"{self._public_base_url}/{quote(key, safe='/')}"

    async def upload_file(self, file_obj: BinaryIO, *, key: str, content_type: str) -> str:
        def _upload() -> None:
            file_obj.seek(0)
            self._client.upload_fileobj(
                Fileobj=file_obj,
                Bucket=self._bucket,
                Key=key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": OBJECT_CACHE_CONTROL,
                },
            )

        await asyncio.to_thread(_upload)
        return self.public_url(key)

    async def object_exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise

        return await asyncio.to_thread(_head)


@lru_cache
def get_object_storage() -> ObjectStorageService:
    return ObjectStorageService(get_settings())
