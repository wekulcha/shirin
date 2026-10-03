import re
from decimal import Decimal
from typing import Literal
from urllib.parse import urlencode, urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductInput(StrictModel):
    sku: str = Field(min_length=1, max_length=100)
    brand: Literal["Ширин", "Сады Востока"]
    category: str = Field(min_length=1, max_length=100)
    name_ru: str = Field(min_length=1, max_length=300)
    name_uz: str = Field(min_length=1, max_length=300)
    description_ru: str | None = Field(None, max_length=3000)
    description_uz: str | None = Field(None, max_length=3000)
    volume_ml: int | None = Field(None, gt=0, le=100000)
    sell_by_unit: bool = True
    sell_by_package: bool = False
    units_per_package: int | None = None
    unit_price_uzs: Decimal | None = None
    package_price_uzs: Decimal | None = None
    is_active: bool = True

    @model_validator(mode="before")
    @classmethod
    def disabled_formats(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if value.get("sell_by_unit") is False:
                value["unit_price_uzs"] = None
            if value.get("sell_by_package", False) is False:
                value["package_price_uzs"] = None
                value["units_per_package"] = None
        return value

    @field_validator("unit_price_uzs", "package_price_uzs")
    @classmethod
    def money(cls, v):
        if v is not None and (not v.is_finite() or v < 0 or v >= Decimal("1000000000000000") or v != v.quantize(Decimal(".01"))):
            raise ValueError("invalid_money")
        return v.quantize(Decimal(".01")) if v is not None else None

    @model_validator(mode="after")
    def formats(self):
        if not self.sell_by_unit and not self.sell_by_package:
            raise ValueError("sale_format_required")
        if self.sell_by_unit and self.unit_price_uzs is None:
            raise ValueError("unit_price_required")
        if self.sell_by_package and (
            not self.units_per_package or self.units_per_package < 1 or self.units_per_package > 100000 or self.package_price_uzs is None
        ):
            raise ValueError("package_price_and_size_required")
        return self


class ProductUpdate(ProductInput):
    version: int = Field(gt=0)


class CustomerInput(StrictModel):
    code: str | None = Field(None, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    contact_name: str | None = Field(None, max_length=200)
    phone: str = Field(min_length=7, max_length=32)
    extra_contacts: str | None = Field(None, max_length=500)
    address: str = Field(min_length=3, max_length=1000)
    latitude: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)
    map_url: str | None = Field(None, max_length=2048)
    photo_reference: str | None = Field(None, max_length=2048)
    comment: str | None = Field(None, max_length=3000)
    is_active: bool = True

    @field_validator("phone")
    @classmethod
    def phone_number(cls, value):
        digits = re.sub(r"[\s()\-]", "", value)
        if re.fullmatch(r"\d{9}", digits):
            digits = "+998" + digits
        elif re.fullmatch(r"998\d{9}", digits):
            digits = "+" + digits
        if not re.fullmatch(r"\+[1-9]\d{6,14}", digits):
            raise ValueError("invalid_phone")
        return digits

    @field_validator("map_url")
    @classmethod
    def safe_map(cls, value):
        if value:
            u = urlparse(value)
            if u.scheme != "https" or not u.hostname or u.username or u.password or any(x in value for x in ("\n", "\r")):
                raise ValueError("invalid_map_url")
        return value or None

    @model_validator(mode="after")
    def location(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("coordinates_pair_required")
        if self.latitude is not None:
            self.map_url = "https://yandex.uz/maps/?" + urlencode({"pt": f"{self.longitude},{self.latitude}", "z": 17, "l": "map"})
        return self


class CustomerUpdate(CustomerInput):
    version: int = Field(gt=0)


class CartLine(StrictModel):
    product_id: int = Field(gt=0)
    sale_format: Literal["unit", "package"]
    quantity: int = Field(gt=0, le=100000, strict=True)


class Checkout(StrictModel):
    lines: list[CartLine] = Field(min_length=1, max_length=100)
    customer: CustomerInput
    customer_id: int | None = Field(None, gt=0)
    save_customer: bool = False

    @model_validator(mode="after")
    def distinct_lines(self):
        keys = [(line.product_id, line.sale_format) for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_cart_line")
        return self


class CreateOrder(Checkout):
    attempt_key: str = Field(min_length=16, max_length=100)
    quote_token: str = Field(max_length=256)


class Transition(StrictModel):
    status: Literal["READY", "DELIVERED"] | None = None
    payment_status: Literal["PAID"] | None = None


class AccessInput(StrictModel):
    user_id: int = Field(gt=0)
    permissions: list[Literal["CAN_EDIT_MENU", "CAN_LOOK_ORDERS"]]


class Login(StrictModel):
    init_data: str = Field(min_length=1, max_length=16384)
