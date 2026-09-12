"""
Generic Fixed Asset Register Adapter.

Supports CSV and Excel fixed asset register exports.
Extracts: asset_code, asset_name, category, acquisition_date, in_service_date,
          acquisition_cost, salvage_value, useful_life_months, depreciation_method,
          accumulated_depreciation, book_value, status, disposal_date.
"""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import re
from typing import Any, Dict, Generator, List, Optional

import openpyxl
from app.ingestion.adapters.tabular import detects, parse_table, normalize_header, pick, decimal_value, date_value, lineage

from app.ingestion.base import (
    BaseAdapter,
    CanonicalRecordPayload,
    RawSourceRow,
    RowRole,
)


class GenericFixedAssetAdapter(BaseAdapter):
    """Adapter for Fixed Asset Register schedules."""

    ASSET_NAME_ALIASES = ["asset_name", "description", "asset_description", "asset", "name", "equipment_name"]
    ASSET_CODE_ALIASES = ["asset_code", "asset_id", "tag_number", "serial_no", "code", "fa_number", "id"]
    CATEGORY_ALIASES = ["category", "asset_class", "class", "asset_type", "type", "group"]
    ACQ_DATE_ALIASES = ["acquisition_date", "purchase_date", "acq_date", "date_purchased", "date"]
    IN_SERVICE_ALIASES = ["in_service_date", "service_date", "commission_date", "start_date"]
    COST_ALIASES = ["acquisition_cost", "cost", "purchase_cost", "original_cost", "historical_cost", "gross_book_value"]
    SALVAGE_ALIASES = ["salvage_value", "residual_value", "scrap_value", "salvage"]
    LIFE_ALIASES = ["useful_life_months", "useful_life", "life_months", "life_years", "months"]
    ACCUM_DEP_ALIASES = ["accumulated_depreciation", "accum_dep", "accum_deprec", "total_depreciation", "depreciation_to_date"]
    BOOK_VAL_ALIASES = ["book_value", "net_book_value", "nbv", "carrying_amount", "current_value"]

    def get_adapter_key(self) -> str:
        return "generic_fixed_asset"

    def _is_header(self, names):
        return bool(names.intersection(self.ASSET_NAME_ALIASES)) and bool(names.intersection(self.COST_ALIASES))

    def can_handle(self, file_bytes, filename):
        return detects(file_bytes, self._is_header)

    def parse_file(self, file_bytes, filename, options=None):
        yield from parse_table(file_bytes, filename, self._is_header)

    def map_to_canonical(
        self, raw_rows: List[RawSourceRow], options: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalRecordPayload]:
        options = options or {}
        currency_code = options.get("currency_code")
        payloads: List[CanonicalRecordPayload] = []

        for row in raw_rows:
            if row.role != RowRole.TRANSACTION:
                continue

            v = row.raw_values
            asset_name = self._find_str(v, self.ASSET_NAME_ALIASES)
            asset_code = self._find_str(v, self.ASSET_CODE_ALIASES)

            category = self._find_str(v, self.CATEGORY_ALIASES)
            acq_date = self._find_and_parse_date(v, self.ACQ_DATE_ALIASES)
            in_svc_date = self._find_and_parse_date(v, self.IN_SERVICE_ALIASES)

            cost = self._find_decimal(v, self.COST_ALIASES)
            salvage = self._find_decimal(v, self.SALVAGE_ALIASES)
            accum_dep = self._find_decimal(v, self.ACCUM_DEP_ALIASES)
            book_val = self._find_decimal(v, self.BOOK_VAL_ALIASES)

            life_val = pick(v, ["useful_life_months", "life_months", "months"])
            years = pick(v, ["life_years", "useful_life_years"])
            if life_val is None and years is None and pick(v, ["useful_life"]) is not None:
                unit = options.get("useful_life_unit")
                if unit == "years":
                    years = v["useful_life"]
                elif unit == "months":
                    life_val = v["useful_life"]
                else:
                    life_val = "AMBIGUOUS_LIFE_UNIT"
            if years is not None:
                parsed_years = decimal_value(years)
                life_val = parsed_years * 12 if isinstance(parsed_years, Decimal) else years

            dep_method = str(v.get("depreciation_method") or v.get("method") or "STRAIGHT_LINE").strip().upper()
            status = str(v.get("status") or "ACTIVE").strip().upper()
            disposal_date = self._find_and_parse_date(v, ["disposal_date", "date_disposed"])

            asset_data = {
                "asset_code": asset_code,
                "asset_name": asset_name,
                "category": category,
                "acquisition_date": acq_date,
                "in_service_date": in_svc_date,
                "acquisition_cost": cost,
                "salvage_value": salvage,
                "useful_life_months": life_val,
                "depreciation_method": dep_method,
                "accumulated_depreciation": accum_dep,
                "book_value": book_val,
                "currency_code": v.get("currency_code") or v.get("currency") or currency_code,
                "status": status,
                "disposal_date": disposal_date,
            }

            payloads.append(
                CanonicalRecordPayload(
                    entity_type="FIXED_ASSET",
                    data=asset_data,
                    source_row_number=row.row_number,
                    sheet_name=row.sheet_name,
                    raw_lineage=lineage(row),
                )
            )

        return payloads

    def _normalize_header(self, value):
        return normalize_header(value)

    def _find_str(self, row, aliases):
        return pick(row, aliases)

    def _find_decimal(self, row, aliases):
        return decimal_value(pick(row, aliases))

    def _find_and_parse_date(self, row, aliases):
        return date_value(pick(row, aliases))
