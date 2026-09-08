"""
GL-to-Bank Reconciliation Engine

Performs exact and deterministic transaction matching between general ledger (GL)
and bank statement line items. Supports configurable tolerances and audit-ready breakdowns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


class ReconciliationEngine:
    """Deterministic GL-to-Bank Reconciliation Engine.

    Parameters
    ----------
    tolerance : float, default 0.01
        Maximum allowed difference between GL and Bank amounts to consider a match.
    date_window_days : int, default 3
        Maximum day difference between GL and Bank transaction dates for secondary matching.
    """

    def __init__(self, tolerance: float = 0.01, date_window_days: int = 3) -> None:
        self.tolerance = max(0.0, float(tolerance))
        self.date_window_days = max(0, int(date_window_days))

    @staticmethod
    def _parse_date(val: Any) -> Optional[datetime]:
        """Normalize string or datetime values to datetime for comparison."""
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                # Handle ISO formats
                return datetime.fromisoformat(val.replace("Z", "+00:00").split("+")[0])
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def _normalize_ref(val: Any) -> str:
        """Normalize reference string for robust matching."""
        if not val:
            return ""
        return str(val).strip().upper()

    def reconcile(
        self,
        gl_transactions: List[Dict[str, Any]],
        bank_transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Match GL transactions against bank statement records.

        Parameters
        ----------
        gl_transactions : list of dict
            General ledger transactions (must contain 'id', 'amount', and optionally 'reference', 'transaction_date').
        bank_transactions : list of dict
            Bank statement transactions (must contain 'id', 'amount', and optionally 'reference', 'transaction_date').

        Returns
        -------
        dict
            Deterministic reconciliation report with matched pairs, unmatched records, and totals.
        """
        matched: List[Dict[str, Any]] = []
        unmatched_gl: List[Dict[str, Any]] = []
        unmatched_bank: List[Dict[str, Any]] = []

        unmatched_bank_indices = set(range(len(bank_transactions)))
        matched_gl_indices = set()

        # Pass 1: Exact Match on Non-Empty Reference + Amount within Tolerance
        for gl_idx, gl_item in enumerate(gl_transactions):
            gl_ref = self._normalize_ref(gl_item.get("reference"))
            gl_amount = float(gl_item.get("amount", 0.0))

            if not gl_ref:
                continue

            found_bank_idx = None
            for b_idx in unmatched_bank_indices:
                b_item = bank_transactions[b_idx]
                b_ref = self._normalize_ref(b_item.get("reference"))
                b_amount = float(b_item.get("amount", 0.0))

                if gl_ref == b_ref and abs(gl_amount - b_amount) <= self.tolerance:
                    found_bank_idx = b_idx
                    break

            if found_bank_idx is not None:
                matched_gl_indices.add(gl_idx)
                unmatched_bank_indices.remove(found_bank_idx)
                bank_item = bank_transactions[found_bank_idx]
                matched.append({
                    "gl_record": gl_item,
                    "bank_record": bank_item,
                    "amount_difference": round(abs(gl_amount - float(bank_item.get("amount", 0.0))), 4),
                    "match_type": "EXACT_REFERENCE_AND_AMOUNT",
                    "match_confidence": 1.0,
                })

        # Pass 2: Fallback Match on Amount + Date Window (for remaining unmatched items)
        for gl_idx, gl_item in enumerate(gl_transactions):
            if gl_idx in matched_gl_indices:
                continue

            gl_amount = float(gl_item.get("amount", 0.0))
            gl_date = self._parse_date(gl_item.get("transaction_date"))

            found_bank_idx = None
            for b_idx in unmatched_bank_indices:
                b_item = bank_transactions[b_idx]
                b_amount = float(b_item.get("amount", 0.0))
                b_date = self._parse_date(b_item.get("transaction_date"))

                # Check amount tolerance
                if abs(gl_amount - b_amount) <= self.tolerance:
                    # If both dates are present, check date window; otherwise match on exact amount
                    if gl_date and b_date:
                        days_diff = abs((gl_date.date() - b_date.date()).days)
                        if days_diff <= self.date_window_days:
                            found_bank_idx = b_idx
                            break
                    else:
                        found_bank_idx = b_idx
                        break

            if found_bank_idx is not None:
                matched_gl_indices.add(gl_idx)
                unmatched_bank_indices.remove(found_bank_idx)
                bank_item = bank_transactions[found_bank_idx]
                matched.append({
                    "gl_record": gl_item,
                    "bank_record": bank_item,
                    "amount_difference": round(abs(gl_amount - float(bank_item.get("amount", 0.0))), 4),
                    "match_type": "AMOUNT_AND_DATE_WINDOW",
                    "match_confidence": 0.9,
                })

        # Collect remaining unmatched items
        for gl_idx, gl_item in enumerate(gl_transactions):
            if gl_idx not in matched_gl_indices:
                unmatched_gl.append(gl_item)

        for b_idx in sorted(unmatched_bank_indices):
            unmatched_bank.append(bank_transactions[b_idx])

        # Compute deterministic summaries
        total_gl_amount = round(sum(float(g.get("amount", 0.0)) for g in gl_transactions), 2)
        total_bank_amount = round(sum(float(b.get("amount", 0.0)) for b in bank_transactions), 2)
        reconciled_gl_amount = round(
            sum(float(m["gl_record"].get("amount", 0.0)) for m in matched), 2
        )
        reconciled_bank_amount = round(
            sum(float(m["bank_record"].get("amount", 0.0)) for m in matched), 2
        )
        net_variance = round(total_gl_amount - total_bank_amount, 2)
        unreconciled_variance = round(
            sum(float(g.get("amount", 0.0)) for g in unmatched_gl)
            - sum(float(b.get("amount", 0.0)) for b in unmatched_bank),
            2,
        )

        max_records = max(len(gl_transactions), len(bank_transactions), 1)
        reconciliation_rate = round((len(matched) / max_records) * 100.0, 2) if gl_transactions or bank_transactions else 100.0

        return {
            "total_gl": len(gl_transactions),
            "total_bank": len(bank_transactions),
            "matched_count": len(matched),
            "unmatched_gl_count": len(unmatched_gl),
            "unmatched_bank_count": len(unmatched_bank),
            "matched": matched,
            "unmatched_gl": unmatched_gl,
            "unmatched_bank": unmatched_bank,
            "total_gl_amount": total_gl_amount,
            "total_bank_amount": total_bank_amount,
            "reconciled_gl_amount": reconciled_gl_amount,
            "reconciled_bank_amount": reconciled_bank_amount,
            "net_variance": net_variance,
            "unreconciled_variance": unreconciled_variance,
            "reconciliation_rate": reconciliation_rate,
            "status": "RECONCILED" if len(unmatched_gl) == 0 and len(unmatched_bank) == 0 else "UNRESOLVED_DISCREPANCIES",
        }
