"""Bounded OOXML values-only import/export for the deployed Python backend.

No formulas, macros, external relationships or images are evaluated/imported.
The file contract is shared by the bot and both administrative interfaces.
"""

import hashlib
import io
import posixpath
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ImportLog, ImportPreview, Product
from app.models.business import Permission, now
from app.schemas import ProductInput
from app.services.access import Actor
from app.services.catalog import serialize

COLUMNS = [
    "sku",
    "action",
    "brand",
    "category",
    "name_ru",
    "name_uz",
    "description_ru",
    "description_uz",
    "volume_ml",
    "sell_by_unit",
    "sell_by_package",
    "units_per_package",
    "unit_price_uzs",
    "package_price_uzs",
    "is_active",
    "photo_reference",
]
BOOLS = {"sell_by_unit", "sell_by_package", "is_active"}
INTS = {"volume_ml", "units_per_package"}
MONEY = {"unit_price_uzs", "package_price_uzs"}
CLEARABLE = {"description_ru", "description_uz", "volume_ml", "units_per_package", "unit_price_uzs", "package_price_uzs"}
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAIN = NS["s"]
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def letter(index: int) -> str:
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def worksheet(rows: list[list], widths: list[int], freeze: bool = False) -> bytes:
    root = ET.Element("worksheet", xmlns=MAIN)
    views = ET.SubElement(root, "sheetViews")
    view = ET.SubElement(views, "sheetView", workbookViewId="0", showGridLines="0")
    if freeze:
        ET.SubElement(view, "pane", ySplit="1", topLeftCell="A2", activePane="bottomLeft", state="frozen")
    cols = ET.SubElement(root, "cols")
    for index, width in enumerate(widths, 1):
        ET.SubElement(cols, "col", min=str(index), max=str(index), width=str(width), customWidth="1", style='3' if index == 1 else '0')
    data = ET.SubElement(root, "sheetData")
    for rn, values in enumerate(rows, 1):
        row = ET.SubElement(data, "row", r=str(rn), ht="30" if rn == 1 else "24", customHeight="1")
        for ci, value in enumerate(values, 1):
            if value is None:
                continue
            numeric = isinstance(value, (Decimal, int)) and not isinstance(value, bool)
            style = "1" if rn == 1 else "3" if ci == 1 else "4" if numeric else "2"
            cell = ET.SubElement(row, "c", r=f"{letter(ci)}{rn}", s=style)
            if isinstance(value, bool):
                cell.set("t", "b")
                ET.SubElement(cell, "v").text = "1" if value else "0"
            elif numeric:
                ET.SubElement(cell, "v").text = str(value)
            else:
                cell.set("t", "inlineStr")
                inline = ET.SubElement(cell, "is")
                ET.SubElement(inline, "t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = str(value)
    if freeze:
        ET.SubElement(root, "autoFilter", ref=f"A1:P{max(1, len(rows))}")
        validations = ET.SubElement(root, "dataValidations", count="3")
        for column, formula in [("B", '"upsert,archive"'), ("C", '"Ширин,Сады Востока"'), ("J:K", '"true,false"')]:
            target = "J2:K3001" if ":" in column else f"{column}2:{column}3001"
            validation = ET.SubElement(validations, "dataValidation", type="list", allowBlank="1", sqref=target)
            ET.SubElement(validation, "formula1").text = formula
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_workbook(products: list[Product], template: bool = False) -> bytes:
    rows = [COLUMNS]
    for product in [] if template else products:
        values = serialize(product)
        values["action"] = "upsert"
        rows.append([getattr(product, key) if key in MONEY else values.get(key) for key in COLUMNS])
    settings = get_settings()
    instructions = [
        ["Ширин · Каталог / Katalog", "Русский", "O‘zbekcha"],
        [
            "Лимиты / Cheklovlar",
            f"До {settings.max_import_rows} строк, {settings.max_upload_bytes // 1048576} MB.",
            f"{settings.max_import_rows} qatorgacha, {settings.max_upload_bytes // 1048576} MB.",
        ],
        [
            "Проверка / Tekshirish",
            "Загрузите файл, проверьте изменения, затем нажмите Применить.",
            "Faylni yuklang, o‘zgarishlarni tekshiring, so‘ng Qo‘llash tugmasini bosing.",
        ],
        [
            "Пусто / Bo‘sh",
            "Пустая ячейка сохраняет прежнее значение. 0 и false — значения.",
            "Bo‘sh katak avvalgi qiymatni saqlaydi. 0 va false — qiymatlar.",
        ],
        [
            "__CLEAR__",
            "Очистка необязательных описаний/объёма/отключённых цен. Обязательные поля не очищаются.",
            "Ixtiyoriy tavsif/hajm/o‘chirilgan narxlarni tozalash. Majburiy maydonlar tozalanmaydi.",
        ],
        [
            "sku",
            "Текстовый уникальный артикул. Ведущие нули сохраняются; менять SKU нельзя.",
            "Noyob matnli artikul. Boshlang‘ich nollar saqlanadi; SKU o‘zgarmaydi.",
        ],
        [
            "action",
            "upsert = создать/обновить; archive = скрыть. Отсутствующие товары не меняются.",
            "upsert = yaratish/yangilash; archive = yashirish. Faylda yo‘q mahsulotlar o‘zgarmaydi.",
        ],
        ["brand", "Ширин или Сады Востока.", "Ширин yoki Сады Востока."],
        ["category", "Название категории, без числового ID.", "Kategoriya nomi, raqamli ID emas."],
        [
            "name_ru / name_uz",
            "Название на русском / узбекском (латиница). Оба обязательны для нового SKU.",
            "Ruscha / o‘zbekcha nom (lotin). Yangi SKU uchun ikkalasi majburiy.",
        ],
        ["description_ru / description_uz", "Необязательные описания.", "Ixtiyoriy tavsiflar."],
        ["volume_ml", "Положительный целый объём в мл; необязательно.", "Ml dagi musbat butun hajm; ixtiyoriy."],
        [
            "sell_by_unit / sell_by_package",
            "true/false, 1/0. Хотя бы один способ включён.",
            "true/false, 1/0. Kamida bir sotish usuli yoqilgan.",
        ],
        [
            "units_per_package",
            "Положительное число бутылок в ящике. Обязательно для ящиков.",
            "Qutidagi shishalar soni. Quti sotishda majburiy.",
        ],
        [
            "unit_price_uzs / package_price_uzs",
            "Независимые цены UZS ≥ 0, до 2 знаков после точки.",
            "Mustaqil UZS narxlari ≥ 0, nuqtadan keyin 2 raqamgacha.",
        ],
        ["is_active", "false скрывает товар, история заказов сохраняется.", "false mahsulotni yashiradi, buyurtma tarixi saqlanadi."],
        [
            "photo_reference",
            "Информационное поле. Фото сохраняется. Новые фото загружайте в админке или боте.",
            "Axborot maydoni. Surat saqlanadi. Yangi suratni boshqaruv yoki bot orqali yuklang.",
        ],
        [
            "Без формул / Formulasiz",
            "Формулы запрещены: вставляйте значения. Макросы и внешние подключения запрещены.",
            "Formulalar taqiqlangan: qiymatlarni joylashtiring. Makros va tashqi ulanishlar taqiqlangan.",
        ],
        [
            "Пример / Misol",
            "sku: 000123; brand: Ширин; category: Соки; name_ru: Сок; name_uz: Sharbat",
            "sell_by_unit: true; unit_price_uzs: 12000; sell_by_package: true; units_per_package: 12; package_price_uzs: 135000",
        ],
    ]
    styles = """<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><color rgb="FF183E32"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF185B43"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>"""
    out = io.BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in (1, 2)
            )
            + "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets><sheet name="Products" sheetId="1" r:id="rId1"/><sheet name="Instructions" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="{REL}/styles" Target="styles.xml"/></Relationships>',
        )
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", worksheet(rows, [18, 12, 20, 22, 32, 32, 38, 38, 16, 20, 22, 24, 22, 24, 16, 38], True))
        z.writestr("xl/worksheets/sheet2.xml", worksheet(instructions, [35, 85, 90]))
    return out.getvalue()


def read_xml(z: ZipFile, path: str):
    data = z.read(path)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("unsafe_xml")
    return ET.fromstring(data)


def parse_workbook(content: bytes) -> tuple[list[tuple[int, dict]], list[dict]]:
    settings = get_settings()
    if not content or len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "file_too_large")
    try:
        with ZipFile(io.BytesIO(content)) as z:
            entries = z.infolist()
            if (
                len(entries) > 250
                or sum(e.file_size for e in entries) > 40 * 1024 * 1024
                or len({e.filename for e in entries}) != len(entries)
            ):
                raise ValueError("unsafe_workbook")
            for e in entries:
                if any(s in e.filename.lower() for s in ("vbaproject", "externallinks", "connections.xml")):
                    raise ValueError("unsafe_workbook")
                if e.filename.endswith(".rels"):
                    if any(r.get("TargetMode") == "External" for r in read_xml(z, e.filename)):
                        raise ValueError("unsafe_workbook")
            workbook = read_xml(z, "xl/workbook.xml")
            sheet = next((s for s in workbook.findall("s:sheets/s:sheet", NS) if s.get("name") == "Products"), None)
            if sheet is None:
                raise ValueError("products_sheet_required")
            rid = sheet.get(f"{{{REL}}}id")
            rels = read_xml(z, "xl/_rels/workbook.xml.rels")
            target = next(r.get("Target") for r in rels if r.get("Id") == rid)
            path = posixpath.normpath(posixpath.join("xl", target)) if not target.startswith("/") else target.lstrip("/")
            if not path.startswith("xl/worksheets/"):
                raise ValueError("unsafe_workbook")
            strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                strings = ["".join(si.itertext()) for si in read_xml(z, "xl/sharedStrings.xml")]
            root = read_xml(z, path)
            errors, rows = [], []
            parsed_rows = root.findall("s:sheetData/s:row", NS)
            if len(parsed_rows) > settings.max_import_rows + 1:
                raise HTTPException(413, "too_many_rows")
            for row in parsed_rows:
                rn = int(row.get("r", "0"))
                if rn < 1 or rn > settings.max_import_rows + 1:
                    raise HTTPException(413, "too_many_rows")
                cells = {}
                for c in row.findall("s:c", NS):
                    ref = c.get("r", "")
                    match = re.fullmatch(r"([A-Z]+)\d+", ref)
                    if not match:
                        raise ValueError("invalid_cell")
                    column = 0
                    for char in match[1]:
                        column = column * 26 + ord(char) - 64
                    if column > len(COLUMNS):
                        continue
                    key = COLUMNS[column - 1]
                    if c.find("s:f", NS) is not None:
                        errors.append({"row": rn, "column": key, "code": "formula_not_allowed"})
                        continue
                    kind = c.get("t", "n")
                    raw = c.findtext("s:v", default="", namespaces=NS)
                    if kind == "inlineStr":
                        value = "".join(c.find("s:is", NS).itertext())
                    elif kind == "s":
                        value = strings[int(raw)]
                    elif kind == "b":
                        value = raw == "1"
                    else:
                        value = Decimal(raw) if raw else None
                    if key == "sku" and rn > 1 and value is not None and not isinstance(value, str):
                        errors.append({"row": rn, "column": key, "code": "sku_must_be_text"})
                    cells[key] = value
                if rn == 1:
                    if [cells.get(c) for c in COLUMNS] != COLUMNS:
                        raise ValueError("invalid_columns")
                elif any(v is not None and v != "" for v in cells.values()):
                    rows.append((rn, cells))
            if not parsed_rows or int(parsed_rows[0].get("r", 0)) != 1:
                raise ValueError("invalid_columns")
            return rows, errors
    except HTTPException:
        raise
    except (BadZipFile, KeyError, ValueError, StopIteration, ET.ParseError, IndexError, InvalidOperation, AttributeError):
        raise HTTPException(422, "invalid_workbook") from None


def parse_value(column: str, value):
    if column in BOOLS:
        if isinstance(value, bool):
            return value
        raw = str(value).lower()
        if raw in ("true", "1"):
            return True
        if raw in ("false", "0"):
            return False
        raise ValueError("invalid_boolean")
    if column in INTS:
        d = Decimal(str(value))
        if not d.is_finite() or d != int(d):
            raise ValueError("invalid_integer")
        return int(d)
    if column in MONEY:
        return Decimal(str(value))
    return str(value)


async def preview_import(db: AsyncSession, actor: Actor, content: bytes) -> ImportPreview:
    actor.require(Permission.CAN_EDIT_MENU)
    file_hash = hashlib.sha256(content).hexdigest()
    old = await db.scalar(
        select(ImportPreview).where(
            ImportPreview.actor_id == actor.user.id,
            ImportPreview.file_hash == file_hash,
            ImportPreview.state == "PENDING",
            ImportPreview.expires_at > now(),
        )
    )
    if old:
        return old
    rows, errors = parse_workbook(content)
    products = {p.sku: p for p in (await db.scalars(select(Product))).all()}
    seen, changes = set(), []
    counts = {"added": 0, "updated": 0, "archived": 0, "unchanged": 0}
    warnings = []
    for rn, cells in rows:
        sku = str(cells.get("sku") or "").strip()
        if not sku or sku in seen:
            errors.append({"row": rn, "column": "sku", "code": "duplicate_sku" if sku in seen else "sku_required"})
            continue
        seen.add(sku)
        action = str(cells.get("action") or "upsert").strip().lower()
        if action not in ("upsert", "archive"):
            errors.append({"row": rn, "column": "action", "code": "invalid_action"})
            continue
        product = products.get(sku)
        if action == "archive" and not product:
            errors.append({"row": rn, "column": "sku", "code": "product_not_found"})
            continue
        original = {key: serialize(product)[key] for key in ProductInput.model_fields} if product else {}
        values = dict(original)
        row_error = False
        for column in ProductInput.model_fields:
            value = cells.get(column)
            if value is None or value == "":
                continue
            try:
                if value == "__CLEAR__":
                    if column not in CLEARABLE:
                        raise ValueError("field_cannot_be_cleared")
                    values[column] = None
                else:
                    values[column] = parse_value(column, value)
            except (ValueError, InvalidOperation, OverflowError):
                errors.append({"row": rn, "column": column, "code": "invalid_value"})
                row_error = True
        if action == "archive":
            values["is_active"] = False
        if row_error:
            continue
        try:
            validated = ProductInput.model_validate(values).model_dump(mode="json")
        except ValidationError as exc:
            for error in exc.errors():
                errors.append({"row": rn, "column": ".".join(map(str, error["loc"])) or "sale_format", "code": "invalid_product"})
            continue
        diff = {key: {"before": original.get(key), "after": value} for key, value in validated.items() if original.get(key) != value}
        kind = (
            "added"
            if not product
            else "archived"
            if product.is_active and not validated["is_active"]
            else "updated"
            if diff
            else "unchanged"
        )
        counts[kind] += 1
        for key in MONEY:
            before, after = original.get(key), validated.get(key)
            if (
                before is not None
                and after is not None
                and Decimal(before) > 0
                and abs(Decimal(after) / Decimal(before) - 1) >= Decimal(".2")
            ):
                warnings.append({"row": rn, "column": key, "code": "price_changed_significantly"})
        changes.append(
            {
                "row": rn,
                "sku": sku,
                "id": product.id if product else None,
                "version": product.version if product else None,
                "kind": kind,
                "values": validated,
                "diff": diff,
            }
        )
    preview = ImportPreview(
        id=secrets.token_urlsafe(24),
        actor_id=actor.user.id,
        file_hash=file_hash,
        payload={"counts": counts, "changes": changes, "errors": errors, "warnings": warnings},
        expires_at=now() + timedelta(minutes=get_settings().import_ttl_minutes),
    )
    db.add(preview)
    await db.flush()
    return preview


async def apply_import(db: AsyncSession, actor: Actor, preview_id: str) -> dict:
    actor.require(Permission.CAN_EDIT_MENU)
    preview = await db.scalar(select(ImportPreview).where(ImportPreview.id == preview_id).with_for_update())
    if not preview or preview.actor_id != actor.user.id:
        raise HTTPException(404, "preview_not_found")
    if preview.state == "APPLIED":
        return preview.payload["counts"]
    if preview.state != "PENDING" or preview.expires_at <= now():
        raise HTTPException(409, "preview_expired")
    if preview.payload["errors"]:
        raise HTTPException(422, "import_has_errors")
    changes = preview.payload["changes"]
    if changes:
        products = {
            p.sku: p
            for p in (
                await db.scalars(
                    select(Product).where(Product.sku.in_([c["sku"] for c in changes])).order_by(Product.sku).with_for_update()
                )
            ).all()
        }
        for c in changes:
            p = products.get(c["sku"])
            if (p and (p.id != c["id"] or p.version != c["version"])) or (not p and c["id"] is not None):
                raise HTTPException(409, "changed_since_preview")
        for c in changes:
            if c["kind"] == "unchanged":
                continue
            values = ProductInput.model_validate(c["values"]).model_dump()
            p = products.get(c["sku"])
            if p:
                for key, value in values.items():
                    setattr(p, key, value)
                p.updated_at = now()
            else:
                db.add(Product(**values))
    preview.state = "APPLIED"
    db.add(ImportLog(preview_id=preview.id, actor_id=actor.user.id, summary=preview.payload["counts"]))
    await db.flush()
    return preview.payload["counts"]
