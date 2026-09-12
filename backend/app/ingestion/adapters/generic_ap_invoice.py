"""
Generic Accounts Payable (AP) Invoice Register Adapter.

Supports CSV and Excel invoice register exports.
Extracts: vendor_name, vendor_code, invoice_number, invoice_date, due_date,
          subtotal_amount, tax_amount, total_amount, paid_amount, outstanding_amount, status.
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


class GenericAPInvoiceAdapter(BaseAdapter):
    """Adapter for AP Invoice register files."""

    VENDOR_ALIASES = ["vendor_name", "vendor", "supplier_name", "supplier", "payee", "creditor"]
    INV_NUM_ALIASES = ["invoice_number", "invoice_no", "inv_num", "bill_no", "document_no", "ref_no"]
    INV_DATE_ALIASES = ["invoice_date", "bill_date", "inv_date", "doc_date", "date"]
    DUE_DATE_ALIASES = ["due_date", "payment_due", "expiry_date"]
    TOTAL_ALIASES = ["total_amount", "gross_amount", "invoice_total", "total", "amount", "balance"]
    TAX_ALIASES = ["tax_amount", "vat_amount", "tax", "vat"]
    SUBTOTAL_ALIASES = ["subtotal_amount", "subtotal", "net_amount", "base_amount"]

    def get_adapter_key(self) -> str:
        return "generic_ap_invoice"

    def _is_header(self, names):
        return bool(names.intersection(self.VENDOR_ALIASES)) and bool(names.intersection(self.INV_NUM_ALIASES))

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
            vendor_name = self._find_str(v, self.VENDOR_ALIASES)
            inv_no = self._find_str(v, self.INV_NUM_ALIASES)

            inv_date = self._find_and_parse_date(v, self.INV_DATE_ALIASES)
            due_date = self._find_and_parse_date(v, self.DUE_DATE_ALIASES)

            total_amt = self._find_decimal(v, self.TOTAL_ALIASES)
            tax_amt = self._find_decimal(v, self.TAX_ALIASES)
            subtotal_amt = self._find_decimal(v, self.SUBTOTAL_ALIASES)
            if subtotal_amt is None and isinstance(total_amt, Decimal) and isinstance(tax_amt, Decimal):
                subtotal_amt = total_amt - tax_amt
            paid_amt = self._find_decimal(v, ["paid_amount", "paid"])
            out_amt = self._find_decimal(v, ["outstanding_amount", "balance_due"])
            status = v.get("status") or "OPEN"

            inv_data = {
                "vendor_name": vendor_name,
                "vendor_code": str(v.get("vendor_code") or "").strip(),
                "invoice_number": inv_no,
                "invoice_date": inv_date,
                "due_date": due_date,
                "currency_code": v.get("currency_code") or v.get("currency") or currency_code,
                "subtotal_amount": subtotal_amt,
                "tax_amount": tax_amt,
                "total_amount": total_amt,
                "paid_amount": paid_amt,
                "outstanding_amount": out_amt,
                "status": status,
                "description": str(v.get("description") or v.get("memo") or "").strip(),
            }

            payloads.append(
                CanonicalRecordPayload(
                    entity_type="AP_INVOICE",
                    data=inv_data,
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
