"""Format-aware, streaming table utilities. No ERP field mappings live here."""
import csv
import io
import re
from itertools import islice
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import openpyxl
from openpyxl.utils.datetime import from_excel

from app.ingestion.base import RawSourceRow, RowRole


def normalize_header(value):
    return re.sub(r"[^\w]+", "_", str(value or "").strip().lower()).strip("_")


def pick(values, aliases):
    """Exact normalized aliases, in priority order; never substring-match amount/date."""
    for key in aliases:
        if key in values and values[key] is not None and str(values[key]).strip():
            return values[key]
    return None


def decimal_value(value):
    """Return missing as None and invalid as the original value for pipeline errors."""
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool):
        return value
    try:
        text = str(value).strip().replace(",", "")
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        parsed = Decimal(text)
        return parsed if parsed.is_finite() else value
    except (InvalidOperation, ValueError):
        return value


def date_value(value, epoch=None):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            result = from_excel(value, epoch=epoch) if epoch else from_excel(value)
            return result if isinstance(result, datetime) else value
        except (ValueError, OverflowError):
            return value
    if isinstance(value, str):
        try:
            return date_value(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(value.strip(), fmt)
                except ValueError:
                    continue
    return value


def physical_rows(content, row_limit=None):
    """Yield sheet, row, values, Excel epoch. OOXML ignores the filename suffix."""
    if content.startswith(b"PK\x03\x04"):
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            for sheet in workbook:
                for number, values in enumerate(islice(sheet.iter_rows(values_only=True), row_limit), 1):
                    yield sheet.title, number, values, workbook.epoch
        finally:
            workbook.close()
    elif content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        import xlrd
        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            for sheet in workbook.sheets():
                for number in range(min(sheet.nrows, row_limit or sheet.nrows)):
                    values = [xlrd.xldate_as_datetime(c.value, workbook.datemode)
                              if c.ctype == xlrd.XL_CELL_DATE else c.value
                              for c in sheet.row(number)]
                    epoch = datetime(1904, 1, 1) if workbook.datemode else datetime(1899, 12, 30)
                    yield sheet.name, number + 1, values, epoch
        finally:
            workbook.release_resources()
    else:
        text = content.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Unsupported binary format")
        for number, values in enumerate(islice(csv.reader(io.StringIO(text)), row_limit), 1):
            yield "CSV", number, values, None


def parse_table(content, filename, is_header, normalize=normalize_header, classify=None):
    headers = {}
    found = False
    for sheet, number, cells, epoch in physical_rows(content):
        if not any(v is not None and str(v).strip() for v in cells):
            continue
        names = [normalize(v) for v in cells]
        metadata = {"filename": filename, "excel_epoch": epoch}
        if is_header(set(names)):
            named = [n for n in names if n]
            if len(named) != len(set(named)):
                raise ValueError("Ambiguous duplicate headers")
            headers[sheet] = {i: n for i, n in enumerate(names) if n}
            found = True
            yield RawSourceRow(number, sheet, {"header": list(cells)}, RowRole.HEADER, metadata)
        elif sheet not in headers:
            yield RawSourceRow(number, sheet, {"title": list(cells)}, RowRole.TITLE, metadata)
        else:
            values = {name: cells[i] if i < len(cells) else None for i, name in headers[sheet].items()}
            role = classify(values) if classify else RowRole.TRANSACTION
            yield RawSourceRow(number, sheet, values, role, metadata)
    if not found:
        raise ValueError("Required table headers not found")


def detects(content, predicate, normalize=normalize_header):
    rows = physical_rows(content, row_limit=100)
    try:
        # Bound detection work per sheet; full parsing validates all rows later.
        for sheet, number, values, epoch in rows:
            if number <= 100 and predicate({normalize(v) for v in values}):
                return True
        return False
    except Exception:
        return False
    finally:
        rows.close()


def lineage(row):
    return {"filename": row.metadata.get("filename"), "sheet_name": row.sheet_name,
            "row_number": row.row_number, "raw_values": dict(row.raw_values)}
