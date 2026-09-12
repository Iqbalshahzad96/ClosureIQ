"""
Enquest ERP Trial Balance Adapter.

Handles:
- Extracting account opening balance, period debits, period credits, and closing balance
- Mapping into canonical TrialBalanceRecord payloads
- Quarantining malformed or non-workbook files
"""

from decimal import Decimal, InvalidOperation
import io
import re
from typing import Any, Dict, Generator, List, Optional

import openpyxl
from app.ingestion.adapters.tabular import detects, parse_table, decimal_value, lineage

from app.ingestion.base import (
    BaseAdapter,
    CanonicalRecordPayload,
    RawSourceRow,
    RowRole,
)


class EnquestTBAdapter(BaseAdapter):
    """Adapter for Enquest ERP Trial Balance reports."""

    HEADER_SIGNATURES = ["account", "opening", "debit", "credit", "closing"]

    def get_adapter_key(self) -> str:
        return "enquest_tb"

    def _is_header(self, names):
        return {"account", "opening", "debit", "credit", "closing"} <= names

    def can_handle(self, file_bytes, filename):
        return detects(file_bytes, self._is_header, self._normalize_col)

    def parse_file(self, file_bytes, filename, options=None):
        if not file_bytes.startswith((b"PK", bytes.fromhex("d0cf11e0a1b11ae1"))):
            raise ValueError("Expected an Excel trial balance")
        def classify(values):
            label = str(values.get("account") or "").strip().lower()
            return RowRole.TOTAL if label in ("total", "grand total", "all account", "all accounts") else RowRole.TRANSACTION
        # Enquest report hierarchy uses indentation. Retain parent controls separately
        # rather than double-counting them alongside the child account balances.
        previous = None
        for row in parse_table(file_bytes, filename, self._is_header, self._normalize_col, classify):
            if previous is not None:
                before = str(previous.raw_values.get("account") or "")
                after = str(row.raw_values.get("account") or "")
                if (previous.role == RowRole.TRANSACTION and row.role == RowRole.TRANSACTION
                        and previous.sheet_name == row.sheet_name
                        and len(after) - len(after.lstrip()) > len(before) - len(before.lstrip())):
                    previous.role = RowRole.SUBTOTAL
                yield previous
            previous = row
        if previous is not None:
            yield previous

    def map_to_canonical(
        self, raw_rows: List[RawSourceRow], options: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalRecordPayload]:
        """Map TB rows into TrialBalanceRecord payloads."""
        options = options or {}
        fiscal_period = options.get("fiscal_period")
        currency_code = options.get("currency_code")
        payloads: List[CanonicalRecordPayload] = []

        for row in raw_rows:
            if row.role != RowRole.TRANSACTION:
                continue

            v = row.raw_values
            acc_name = str(v.get("account") or v.get("particulars") or "").strip()

            opening = self._parse_decimal(v.get("opening"))
            debit = self._parse_decimal(v.get("debit"))
            credit = self._parse_decimal(v.get("credit"))
            closing = self._parse_decimal(v.get("closing"))

            tb_data = {
                "account_name_raw": acc_name,
                "fiscal_period": fiscal_period,
                "opening_balance": opening,
                "period_debit": debit,
                "period_credit": credit,
                "closing_balance": closing,
                "currency_code": currency_code,
            }

            payloads.append(
                CanonicalRecordPayload(
                    entity_type="TRIAL_BALANCE",
                    data=tb_data,
                    source_row_number=row.row_number,
                    sheet_name=row.sheet_name,
                    raw_lineage=lineage(row),
                )
            )

        return payloads

    def _normalize_col(self, col: str) -> str:
        s = str(col or "").strip().lower()
        if "account" in s or "ledger" in s:
            return "account"
        if "open" in s:
            return "opening"
        if "deb" in s:
            return "debit"
        if "cred" in s:
            return "credit"
        if "clos" in s or "bal" in s:
            return "closing"
        return re.sub(r"\s+", "_", s)

    def _parse_decimal(self, value):
        return decimal_value(value)
