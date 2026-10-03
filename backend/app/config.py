from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://shirin:shirin@localhost:5444/shirin"
    environment: str = "production"
    user_bot_token: str = ""
    auth_access_secret: str = ""
    auth_access_ttl_minutes: int = 15
    auth_refresh_ttl_days: int = 30
    auth_cookie_domain: str = ""
    auth_cookie_secure: bool = True
    init_data_ttl_seconds: int = 3600
    superadmin_allowed_ids: Annotated[list[int], NoDecode] = []
    internal_api_secret: str = ""
    market_integration_secret: str = ""
    webhook_secret: str = ""
    bot_mode: str = "polling"
    bot_username: str = ""
    work_group_id: int = 0
    work_group_topic_id: int = 0
    group_language: str = "ru"
    mini_app_url: str = "https://market.wekulcha.ru/shirin/"
    admin_app_url: str = "https://adminmarket.wekulcha.online/shirin/"
    timezone: str = "Asia/Tashkent"
    uploads_dir: str = "./uploads"
    object_storage_endpoint: str = "https://storage.yandexcloud.net"
    object_storage_region: str = "ru-central1"
    object_storage_bucket: str = ""
    object_storage_access_key_id: str = ""
    object_storage_secret_access_key: str = ""
    object_storage_public_base_url: str = ""
    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "https://market.wekulcha.ru",
        "https://adminmarket.wekulcha.online",
        "http://localhost:5183",
        "http://localhost:5184",
    ]
    max_upload_bytes: int = 8 * 1024 * 1024
    max_import_rows: int = 3000
    import_ttl_minutes: int = 30
    model_config = SettingsConfigDict(env_prefix="SHIRIN_", env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore")

    @field_validator("superadmin_allowed_ids", "cors_allowed_origins", mode="before")
    @classmethod
    def csv(cls, value, info):
        if isinstance(value, str):
            value = [s.strip() for s in value.split(",") if s.strip()]
        return [int(s) for s in value] if info.field_name == "superadmin_allowed_ids" else value

    @model_validator(mode="after")
    def check_environment(self):
        if self.environment not in ("production", "development", "test"):
            raise ValueError("Invalid environment")
        if self.environment == "production":
            if len(self.auth_access_secret) < 32 or not self.auth_cookie_secure:
                raise ValueError("Production requires a unique access secret (32+ characters) and secure cookies")
            if any(value in self.auth_access_secret.lower() for value in ("replace_", "change_me", "synthetic", "test-secret")):
                raise ValueError("Replace the placeholder with a unique production access secret")
            if self.market_integration_secret and len(self.market_integration_secret) < 32:
                raise ValueError("Integration secret must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
