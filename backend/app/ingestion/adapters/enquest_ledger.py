"""
Enquest ERP Account Ledger Adapter.

Handles:
- Dynamic header detection
- OOXML workbooks named .xls
- Missing Remarks column
- Excel serial date and decimal parsing
- Row-role classification (filtering header, opening, total rows)
- Preserving Is Bank Reconciliated as source metadata only
- Flagging dual-sided debit+credit rows
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import io
import os
import re
from typing import Any, Dict, Generator, List, Optional, Tuple

import openpyxl
from app.ingestion.adapters.tabular import detects, parse_table, decimal_value, date_value, lineage

from app.ingestion.base import (
    BaseAdapter,
    CanonicalRecordPayload,
    RawSourceRow,
    RowRole,
)


class EnquestLedgerAdapter(BaseAdapter):
    """Adapter for Enquest ERP standard account ledger exports."""

    HEADER_SIGNATURES = [
        "voucher date",
        "particulars",
        "voucher type",
        "debit amount",
        "credit amount",
    ]

    def get_adapter_key(self) -> str:
        return "enquest_ledger"

    def can_handle(self, file_bytes, filename):
        return detects(file_bytes, self._is_header, self._normalize_column_name)

    def _is_header(self, names):
        return {"voucher_date", "voucher_type", "debit_amount", "credit_amount"} <= names

    def parse_file(self, file_bytes, filename, options=None):
        if not file_bytes.startswith((b"PK", bytes.fromhex("d0cf11e0a1b11ae1"))):
            raise ValueError("Expected an Excel ledger")
        for row in parse_table(file_bytes, filename, self._is_header,
                               self._normalize_column_name, self._classify_row):
            row.metadata["account_name_raw"] = self._extract_account_name(filename)
            yield row

    def map_to_canonical(
        self, raw_rows: List[RawSourceRow], options: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalRecordPayload]:
        """Convert transaction rows into canonical JournalEntry payloads."""
        options = options or {}
        payloads: List[CanonicalRecordPayload] = []

        for row in raw_rows:
            if row.role != RowRole.TRANSACTION:
                continue

            v = row.raw_values
            meta = row.metadata

            # 1. Parse date
            parsed_date = date_value(v.get("voucher_date"), meta.get("excel_epoch"))

            # 2. Parse debit and credit
            debit_amt = self._parse_decimal(v.get("debit_amount"))
            credit_amt = self._parse_decimal(v.get("credit_amount"))
            balance_amt = self._parse_decimal(v.get("balance_amount"))

            # 3. Currency & exchange rate
            curr = v.get("curr") or options.get("currency_code")
            ex_rate = decimal_value(v.get("ex_rate"))

            # 4. Check for dual-sided debit + credit
            flags = []
            if isinstance(debit_amt, Decimal) and debit_amt.is_finite() and isinstance(credit_amt, Decimal) and credit_amt.is_finite() and debit_amt > 0 and credit_amt > 0:
                flags.extend(["FLAG_DUAL_SIDED_POSTING", "WARN_DUAL_SIDED_POSTING"])

            # 5. Build canonical JournalLine dict
            account_name_raw = meta.get("account_name_raw") or "Unknown Account"
            particulars = str(v.get("particulars") or "").strip()
            voucher_type = str(v.get("voucher_type") or "JOURNAL").strip()
            voucher_no = str(v.get("voucher_no") or "").strip()
            ref_no = str(v.get("ref_no") or "").strip()
            remarks = str(v.get("remarks") or "").strip()

            description = particulars
            if remarks:
                description = f"{particulars} - {remarks}" if particulars else remarks

            is_recon_raw = str(v.get("is_bank_reconciliated") or "").strip()

            line_payload = {
                "account_name_raw": account_name_raw,
                "description": description,
                "debit_amount": debit_amt,
                "credit_amount": credit_amt,
                "source_running_balance": balance_amt,
                "source_row_identifier": f"{row.sheet_name}:R{row.row_number}",
                "dimensions_json": {
                    "source_is_bank_reconciled": is_recon_raw,
                    "cuin_fda": str(v.get("cuin_fda") or "").strip(),
                    "cheque_no": str(v.get("cheque_no") or "").strip(),
                    "raw_particulars": particulars,
                    "raw_remarks": remarks,
                },
            }

            # 6. Build entry payload
            fiscal_period = None
            if isinstance(parsed_date, datetime):
                fiscal_period = f"{parsed_date.year:04d}-{parsed_date.month:02d}"

            entry_data = {
                "external_entry_id": voucher_no or None,
                "entry_number": voucher_no,
                "entry_type": voucher_type,
                "entry_date": parsed_date,
                "posting_date": None,
                "partial_journal": True,
                "status": "DRAFT",
                "fiscal_period": fiscal_period,
                "reference": ref_no,
                "description": description,
                "currency_code": curr,
                "exchange_rate": ex_rate,
                "lines": [line_payload],
            }

            payloads.append(
                CanonicalRecordPayload(
                    entity_type="JOURNAL_ENTRY",
                    data=entry_data,
                    source_row_number=row.row_number,
                    sheet_name=row.sheet_name,
                    raw_lineage=lineage(row),
                    flags=flags,
                )
            )

        return payloads

    def _normalize_column_name(self, col: str) -> str:
        """Standardize column names to snake_case keys."""
        cleaned = str(col or "").strip().lower()
        cleaned = cleaned.replace(".", "").replace("/", "_").replace("&", "and")
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned)
        if cleaned in ("curr", "curr."):
            return "curr"
        if cleaned in ("exrate", "ex_rate"):
            return "ex_rate"
        if "reconcil" in cleaned:
            return "is_bank_reconciliated"
        if "cuin" in cleaned or "fda" in cleaned:
            return "cuin_fda"
        return cleaned

    def _classify_row(self, values):
        labels = [str(values.get(k) or "").strip().lower()
                  for k in ("particulars", "voucher_type", "voucher_no")]
        if any(v in ("opening", "opening balance", "balance brought forward") for v in labels):
            return RowRole.OPENING_BALANCE
        if any(v in ("subtotal", "sub total", "sub-total") for v in labels):
            return RowRole.SUBTOTAL
        if any(v in ("total", "grand total", "closing balance") for v in labels):
            return RowRole.TOTAL
        if values.get("voucher_date") is not None or values.get("voucher_no"):
            return RowRole.TRANSACTION
        if any(v not in (None, "") for v in (values.get("debit_amount"), values.get("credit_amount"))):
            return RowRole.TOTAL
        return RowRole.FOOTER

    def _parse_date(self, value):
        return date_value(value)

    def _parse_decimal(self, value, default=None):
        return decimal_value(value)

    def _extract_account_name(self, filename: str) -> str:
        """Extract clean account name from filename stem."""
        base = os.path.splitext(os.path.basename(filename))[0]
        # Remove trailing .xls if present in stem
        base = re.sub(r"\.xlsx?$", "", base, flags=re.IGNORECASE).strip()
        return base
