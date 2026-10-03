from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Permission(str, Enum):
    CAN_EDIT_MENU = "CAN_EDIT_MENU"
    CAN_LOOK_ORDERS = "CAN_LOOK_ORDERS"


class Staff(Base):
    __tablename__ = "staff"
    __table_args__ = (UniqueConstraint("user_id", "permission"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    permission: Mapped[str] = mapped_column(String(64))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("sell_by_unit OR sell_by_package"),
        CheckConstraint("NOT sell_by_unit OR (unit_price_uzs IS NOT NULL AND unit_price_uzs >= 0)"),
        CheckConstraint("NOT sell_by_package OR (units_per_package IS NOT NULL AND units_per_package > 0 AND package_price_uzs IS NOT NULL AND package_price_uzs >= 0)"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True)
    brand: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    name_ru: Mapped[str] = mapped_column(String(300))
    name_uz: Mapped[str] = mapped_column(String(300))
    description_ru: Mapped[str | None] = mapped_column(String(3000))
    description_uz: Mapped[str | None] = mapped_column(String(3000))
    volume_ml: Mapped[int | None] = mapped_column(Integer)
    sell_by_unit: Mapped[bool] = mapped_column(Boolean, default=True)
    sell_by_package: Mapped[bool] = mapped_column(Boolean, default=False)
    units_per_package: Mapped[int | None] = mapped_column(Integer)
    unit_price_uzs: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    package_price_uzs: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    photo_reference: Mapped[str | None] = mapped_column(String(2048))
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __mapper_args__ = {"version_id_col": version}


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32), index=True)
    extra_contacts: Mapped[str | None] = mapped_column(String(500))
    address: Mapped[str] = mapped_column(String(1000))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    map_url: Mapped[str | None] = mapped_column(String(2048))
    photo_reference: Mapped[str | None] = mapped_column(String(2048))
    comment: Mapped[str | None] = mapped_column(String(3000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("author_id", "attempt_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    attempt_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    customer_snapshot: Mapped[dict] = mapped_column(JSON)
    author_snapshot: Mapped[dict] = mapped_column(JSON)
    lines: Mapped[list] = mapped_column(JSON)
    total_uzs: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(32), default="ACCEPTED")
    payment_status: Mapped[str] = mapped_column(String(16), default="UNPAID")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {"version_id_col": version}


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(150), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    last_error: Mapped[str | None] = mapped_column(String(200))


class ImportPreview(Base):
    __tablename__ = "import_previews"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    file_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(16), default="PENDING")


class ImportLog(Base):
    __tablename__ = "import_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    preview_id: Mapped[str] = mapped_column(ForeignKey("import_previews.id"), unique=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    summary: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BotState(Base):
    __tablename__ = "bot_states"
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class WebhookUpdate(Base):
    __tablename__ = "webhook_updates"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Media(Base):
    __tablename__ = "media"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))
    storage_path: Mapped[str] = mapped_column(String(2048))
    content_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
