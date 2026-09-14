"""
Trial Balance Validation Engine

Deterministic trial balance verification:
- Debit/credit equilibrium proof
- Row-level continuity equation: closing = opening ± debits ∓ credits
- Material variance detection
- Journal line aggregation by account/period
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List


class TrialBalanceEngine:
    """Deterministic Trial Balance Validation Engine.

    Parameters
    ----------
    tolerance : float, default 0.01
        Maximum allowed imbalance between total debits and total credits.
    """

    def __init__(self, tolerance: float = 0.01) -> None:
        self.tolerance = max(Decimal("0"), Decimal(str(tolerance)))

    def validate_trial_balance(
        self,
        trial_balance_records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Validate trial balance records for equilibrium and row-level continuity.

        Parameters
        ----------
        trial_balance_records : list of dict
            Trial balance rows. Expected keys:
            - account_code, account_name, account_type (optional)
            - opening_balance, period_debit, period_credit, closing_balance
            - fiscal_period (optional), currency_code (optional)

        Returns
        -------
        dict
            Deterministic validation report with totals, continuity checks,
            out-of-balance lines, and overall status.
        """
        self._validate_scope(trial_balance_records)
        account_codes = [row.get("account_code") for row in trial_balance_records]
        if len(account_codes) != len(set(account_codes)):
            raise ValueError("Provide one trial balance snapshot per account")
        total_debits = Decimal("0")
        total_credits = Decimal("0")
        total_opening = Decimal("0")
        total_closing = Decimal("0")
        continuity_errors: List[Dict[str, Any]] = []
        valid_rows: List[Dict[str, Any]] = []

        for row in trial_balance_records:
            opening = Decimal(str(row.get("exact_amounts", row).get("opening_balance", 0)))
            debit = Decimal(str(row.get("exact_amounts", row).get("period_debit", 0)))
            credit = Decimal(str(row.get("exact_amounts", row).get("period_credit", 0)))
            closing = Decimal(str(row.get("exact_amounts", row).get("closing_balance", 0)))
            account_code = row.get("account_code", "N/A")
            account_name = row.get("account_name", "")
            account_type = str(row.get("account_type", "")).upper()

            total_debits += debit
            total_credits += credit
            total_opening += opening
            total_closing += closing

            # Continuity equation:
            # Debit-normal accounts (ASSET, EXPENSE): closing = opening + debit - credit
            # Credit-normal accounts (LIABILITY, EQUITY, REVENUE): closing = opening + credit - debit
            normal_balance = row.get("normal_balance") or ("CREDIT" if account_type in ("LIABILITY", "EQUITY", "REVENUE") else "DEBIT")
            if normal_balance not in ("DEBIT", "CREDIT"):
                raise ValueError("normal_balance must be DEBIT or CREDIT")
            if normal_balance == "CREDIT":
                calculated_closing = opening + credit - debit
            else:
                # Default to debit-normal (ASSET, EXPENSE, or unspecified)
                calculated_closing = opening + debit - credit

            variance = closing - calculated_closing

            row_info = {
                "id": row.get("id"),
                "import_batch_id": row.get("import_batch_id"),
                "fiscal_period": row.get("fiscal_period"),
                "currency_code": row.get("currency_code"),
                "normal_balance": normal_balance,
                "account_code": account_code,
                "account_name": account_name,
                "account_type": account_type,
                "opening_balance": opening,
                "period_debit": debit,
                "period_credit": credit,
                "closing_balance": closing,
                "calculated_closing": calculated_closing,
                "variance": variance,
            }

            if abs(variance) > self.tolerance:
                continuity_errors.append({
                    **row_info,
                    "reason": (
                        f"Continuity break for account {account_code}: "
                        f"expected closing {calculated_closing}, "
                        f"actual closing {closing}, variance {variance}."
                    ),
                })
            else:
                valid_rows.append(row_info)

        debit_credit_difference = total_debits - total_credits
        is_balanced = abs(debit_credit_difference) <= self.tolerance

        return self._serialize({
            "record_ids": [row["id"] for row in trial_balance_records if row.get("id")],
            "total_rows": len(trial_balance_records),
            "valid_rows_count": len(valid_rows),
            "continuity_errors_count": len(continuity_errors),
            "valid_rows": valid_rows,
            "continuity_errors": continuity_errors,
            "total_debits": total_debits,
            "total_credits": total_credits,
            "total_opening": total_opening,
            "total_closing": total_closing,
            "debit_credit_difference": debit_credit_difference,
            "is_balanced": is_balanced,
            "status": ("NO_DATA" if not trial_balance_records else
                       "BALANCED" if is_balanced and not continuity_errors else "IMBALANCED"),
        })

    def aggregate_journal_lines(
        self,
        journal_lines: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Aggregate journal lines into debit/credit totals grouped by account code.

        Parameters
        ----------
        journal_lines : list of dict
            Journal line items. Expected keys: account_code, debit_amount, credit_amount.

        Returns
        -------
        dict
            Aggregation report with per-account breakdowns and grand totals.
        """
        self._validate_scope(journal_lines)
        accounts: Dict[str, Dict[str, Any]] = {}
        grand_debit = Decimal("0")
        grand_credit = Decimal("0")

        for line in journal_lines:
            account_code = str(line.get("account_code", "UNKNOWN"))
            debit = Decimal(str(line.get("debit_amount", 0)))
            credit = Decimal(str(line.get("credit_amount", 0)))

            grand_debit += debit
            grand_credit += credit

            if account_code not in accounts:
                accounts[account_code] = {"debit_total": Decimal("0"), "credit_total": Decimal("0"), "line_count": 0}
            accounts[account_code]["debit_total"] += debit
            accounts[account_code]["credit_total"] += credit
            accounts[account_code]["line_count"] += 1

        account_summaries = [
            {
                "account_code": code,
                "debit_total": data["debit_total"],
                "credit_total": data["credit_total"],
                "net_balance": data["debit_total"] - data["credit_total"],
                "line_count": data["line_count"],
            }
            for code, data in sorted(accounts.items())
        ]


        return self._serialize({
            "total_lines": len(journal_lines),
            "total_accounts": len(accounts),
            "account_summaries": account_summaries,
            "grand_debit_total": grand_debit,
            "grand_credit_total": grand_credit,
            "grand_net_balance": grand_debit - grand_credit,
            "is_balanced": abs(grand_debit - grand_credit) <= self.tolerance,
        })

    @staticmethod
    def _validate_scope(rows):
        """Never let different periods/currencies cancel each other's breaks."""
        for key in ("fiscal_period", "currency_code"):
            if len({row.get(key) for row in rows}) > 1:
                raise ValueError(f"Validate one {key} at a time")

    @staticmethod
    def _serialize(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {key: TrialBalanceEngine._serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [TrialBalanceEngine._serialize(item) for item in value]
        return value
