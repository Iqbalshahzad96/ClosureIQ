"""
Generic Bank Statement Adapter.

Supports CSV and Excel bank statement exports.
Extracts: booking_date, value_date, amount (signed), bank_reference, description, running_balance.
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


class GenericBankStatementAdapter(BaseAdapter):
    """Adapter for CSV and Excel generic bank statements."""

    DATE_ALIASES = ["booking_date", "transaction_date", "date", "tx_date", "post_date", "value_date"]
    AMOUNT_ALIASES = ["amount", "transaction_amount", "amount_signed", "net_amount"]
    DEPOSIT_ALIASES = ["deposit", "credit", "inflow", "cr", "deposits", "cr_amount"]
    WITHDRAWAL_ALIASES = ["withdrawal", "debit", "outflow", "dr", "withdrawals", "dr_amount"]
    REF_ALIASES = ["bank_reference", "reference", "ref_no", "ref", "trans_id", "cheque_no", "txn_id"]
    DESC_ALIASES = ["description", "narration", "particulars", "memo", "details"]
    BAL_ALIASES = ["balance", "running_balance", "closing_balance", "available_balance"]

    def get_adapter_key(self) -> str:
        return "generic_bank"

    def _is_header(self, names):
        return bool(names.intersection(self.DATE_ALIASES)) and bool(names.intersection(self.AMOUNT_ALIASES + self.DEPOSIT_ALIASES + self.WITHDRAWAL_ALIASES)) and not {"vendor_name", "invoice_number"} <= names

    def can_handle(self, file_bytes, filename):
        return detects(file_bytes, self._is_header)

    def parse_file(self, file_bytes, filename, options=None):
        yield from parse_table(file_bytes, filename, self._is_header)

    def map_to_canonical(
        self, raw_rows: List[RawSourceRow], options: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalRecordPayload]:
        options = options or {}
        bank_account_id = options.get("bank_account_id")
        currency_code = options.get("currency_code")
        payloads: List[CanonicalRecordPayload] = []

        for row in raw_rows:
            if row.role != RowRole.TRANSACTION:
                continue

            v = row.raw_values
            # 1. Booking & Value Date
            b_date = self._find_and_parse_date(v, self.DATE_ALIASES)
            v_date = self._find_and_parse_date(v, ["value_date", "effective_date"])

            # 2. Signed Amount Calculation
            signed_amount = self._calculate_signed_amount(v)

            # 3. Reference, Description, Balance
            ref = self._find_str(v, self.REF_ALIASES)
            desc = self._find_str(v, self.DESC_ALIASES)
            bal = self._find_decimal(v, self.BAL_ALIASES)

            tx_data = {
                "bank_account_id": bank_account_id,
                "external_transaction_id": pick(v, ["external_transaction_id", "trans_id", "txn_id"]),
                "booking_date": b_date,
                "value_date": v_date,
                "amount": signed_amount,
                "currency_code": v.get("currency_code") or v.get("currency") or currency_code,
                "bank_reference": ref,
                "description": desc,
                "running_balance": bal,
                "source_row_identifier": f"{row.sheet_name}:R{row.row_number}",
            }

            payloads.append(
                CanonicalRecordPayload(
                    entity_type="BANK_TRANSACTION",
                    data=tx_data,
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

    def _calculate_signed_amount(self, row):
        direct = self._find_decimal(row, self.AMOUNT_ALIASES)
        if direct is not None:
            return direct
        deposit = self._find_decimal(row, self.DEPOSIT_ALIASES)
        withdrawal = self._find_decimal(row, self.WITHDRAWAL_ALIASES)
        # An absent opposite side is structural, not a missing transaction amount.
        if deposit is None and withdrawal is None:
            return None
        if deposit is not None and (not isinstance(deposit, Decimal) or not deposit.is_finite() or deposit < 0):
            return "INVALID_DEPOSIT"
        if withdrawal is not None and (not isinstance(withdrawal, Decimal) or not withdrawal.is_finite() or withdrawal < 0):
            return "INVALID_WITHDRAWAL"
        if deposit and withdrawal:
            return "AMBIGUOUS_DUAL_BANK_AMOUNT"
        return deposit if deposit is not None and deposit != 0 else -withdrawal if withdrawal is not None else deposit
