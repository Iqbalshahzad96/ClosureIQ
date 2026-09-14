"""
Accounts Payable (AP) Validation Engine

Validates AP invoices, detects duplicate invoices (exact and suspect),
checks calculation integrity (subtotal + tax = total), verifies payment balances,
and flags overdue obligations deterministically.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union


class APEngine:
    """Deterministic Accounts Payable Validation and Duplicate Detection Engine.

    Parameters
    ----------
    tolerance : float, default 0.01
        Maximum allowed calculation/amount variance before flagging a discrepancy.
    """

    def __init__(self, tolerance: float = 0.01) -> None:
        self.tolerance = max(0.0, float(tolerance))

    @staticmethod
    def _parse_date(val: Any) -> Optional[datetime]:
        """Normalize string or datetime values to datetime for comparison."""
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, date):
            return datetime.combine(val, datetime.min.time())
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00").split("+")[0])
            except (ValueError, TypeError):
                for fmt in ("%Y-%m-%d", "%Y-%m", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d-%m-%Y"):
                    try:
                        return datetime.strptime(val.strip(), fmt)
                    except ValueError:
                        pass
        return None

    @staticmethod
    def _normalize_str(val: Any) -> str:
        """Trim and uppercase strings for reliable comparison."""
        if not val:
            return ""
        return str(val).strip().upper()

    def validate_ap_invoices(
        self,
        invoices: List[Dict[str, Any]],
        as_of_date: Optional[Union[datetime, date, str]] = None,
    ) -> Dict[str, Any]:
        """Validate accounts payable invoices deterministically.

        Parameters
        ----------
        invoices : list of dict
            List of AP invoice records containing:
            - id, invoice_number, vendor_name, vendor_code (optional)
            - subtotal_amount, tax_amount, total_amount, paid_amount, outstanding_amount
            - invoice_date, due_date, status, currency_code
        as_of_date : datetime or date or str, optional
            Reference date for checking overdue invoices. Defaults to now.

        Returns
        -------
        dict
            Deterministic AP evaluation report with validation metrics, duplicates,
            calculation breaks, and payment discrepancies.
        """
        ref_date = self._parse_date(as_of_date) or datetime.now(timezone.utc)

        duplicates: List[Dict[str, Any]] = []
        calculation_errors: List[Dict[str, Any]] = []
        payment_discrepancies: List[Dict[str, Any]] = []
        overdue_invoices: List[Dict[str, Any]] = []
        valid_invoices: List[Dict[str, Any]] = []

        seen_invoice_numbers: Dict[tuple[str, str], Dict[str, Any]] = {}
        seen_amount_dates: Dict[tuple[str, float, Optional[str]], Dict[str, Any]] = {}

        total_amount = 0.0
        total_outstanding = 0.0

        for inv in invoices:
            inv_id = str(inv.get("id") or "")
            inv_num = self._normalize_str(inv.get("invoice_number"))
            vendor = self._normalize_str(inv.get("vendor_name") or inv.get("vendor_code") or "UNKNOWN_VENDOR")
            vendor_key = vendor

            subtotal = round(float(inv.get("subtotal_amount", 0.0)), 2)
            tax = round(float(inv.get("tax_amount", 0.0)), 2)
            total = round(float(inv.get("total_amount", 0.0)), 2)
            paid = round(float(inv.get("paid_amount", 0.0)), 2)
            outstanding = round(float(inv.get("outstanding_amount", total - paid)), 2)

            inv_date = self._parse_date(inv.get("invoice_date"))
            due_date = self._parse_date(inv.get("due_date"))
            status = self._normalize_str(inv.get("status") or "OPEN")

            total_amount += total
            total_outstanding += outstanding

            has_error = False

            # 1. Duplicate Detection
            is_exact_dup = False
            if inv_num:
                key = (vendor_key, inv_num)
                if key in seen_invoice_numbers:
                    has_error = True
                    is_exact_dup = True
                    prev = seen_invoice_numbers[key]
                    duplicates.append({
                        "type": "EXACT_DUPLICATE_INVOICE_NUMBER",
                        "invoice_id": inv_id,
                        "invoice_number": inv_num,
                        "vendor_name": inv.get("vendor_name", vendor),
                        "original_invoice_id": prev.get("id"),
                        "total_amount": total,
                        "variance_amount": total,
                        "reason": f"Duplicate invoice number '{inv_num}' for vendor '{vendor}'.",
                    })
                else:
                    seen_invoice_numbers[key] = inv

            date_str = inv_date.strftime("%Y-%m-%d") if inv_date else None
            if total > 0 and date_str:
                amt_date_key = (vendor_key, total, date_str)
                if amt_date_key in seen_amount_dates and not is_exact_dup:
                    prev = seen_amount_dates[amt_date_key]
                    if prev.get("invoice_number") != inv_num:
                        has_error = True
                        duplicates.append({
                            "type": "SUSPECT_DUPLICATE_BILLING",
                            "invoice_id": inv_id,
                            "invoice_number": inv_num,
                            "vendor_name": inv.get("vendor_name", vendor),
                            "original_invoice_id": prev.get("id"),
                            "original_invoice_number": prev.get("invoice_number"),
                            "total_amount": total,
                            "variance_amount": total,
                            "reason": f"Potential duplicate billing: same vendor '{vendor}', date '{date_str}', and amount ${total:,.2f}.",
                        })
                else:
                    seen_amount_dates[amt_date_key] = inv

            # 2. Mathematical Consistency (subtotal + tax == total)
            expected_total = round(subtotal + tax, 2)
            if abs(expected_total - total) > self.tolerance and (subtotal > 0 or tax > 0):
                has_error = True
                diff = round(abs(expected_total - total), 2)
                calculation_errors.append({
                    "type": "SUBTOTAL_TAX_SUM_MISMATCH",
                    "invoice_id": inv_id,
                    "invoice_number": inv_num,
                    "vendor_name": inv.get("vendor_name", vendor),
                    "subtotal_amount": subtotal,
                    "tax_amount": tax,
                    "expected_total": expected_total,
                    "actual_total": total,
                    "variance_amount": diff,
                    "reason": f"Subtotal (${subtotal:,.2f}) + Tax (${tax:,.2f}) = ${expected_total:,.2f}, but total is ${total:,.2f} (diff ${diff:,.2f}).",
                })

            # 3. Payment & Balance Discrepancies
            if paid > (total + self.tolerance):
                has_error = True
                overpay = round(paid - total, 2)
                payment_discrepancies.append({
                    "type": "OVERPAYMENT_DETECTED",
                    "invoice_id": inv_id,
                    "invoice_number": inv_num,
                    "vendor_name": inv.get("vendor_name", vendor),
                    "total_amount": total,
                    "paid_amount": paid,
                    "variance_amount": overpay,
                    "reason": f"Paid amount (${paid:,.2f}) exceeds invoice total (${total:,.2f}) by ${overpay:,.2f}.",
                })

            expected_outstanding = round(max(0.0, total - paid), 2)
            if abs(expected_outstanding - outstanding) > self.tolerance:
                has_error = True
                out_diff = round(abs(expected_outstanding - outstanding), 2)
                payment_discrepancies.append({
                    "type": "OUTSTANDING_BALANCE_MISMATCH",
                    "invoice_id": inv_id,
                    "invoice_number": inv_num,
                    "vendor_name": inv.get("vendor_name", vendor),
                    "total_amount": total,
                    "paid_amount": paid,
                    "expected_outstanding": expected_outstanding,
                    "actual_outstanding": outstanding,
                    "variance_amount": out_diff,
                    "reason": f"Expected outstanding balance (${expected_outstanding:,.2f}) differs from recorded outstanding (${outstanding:,.2f}).",
                })

            # 4. Overdue Invoices
            if due_date and due_date.date() < ref_date.date() and outstanding > self.tolerance and status != "PAID":
                days_overdue = (ref_date.date() - due_date.date()).days
                overdue_invoices.append({
                    "type": "OVERDUE_INVOICE",
                    "invoice_id": inv_id,
                    "invoice_number": inv_num,
                    "vendor_name": inv.get("vendor_name", vendor),
                    "due_date": due_date.strftime("%Y-%m-%d"),
                    "days_overdue": days_overdue,
                    "outstanding_amount": outstanding,
                    "variance_amount": outstanding,
                    "reason": f"Invoice '{inv_num}' is overdue by {days_overdue} days (due {due_date.strftime('%Y-%m-%d')}) with ${outstanding:,.2f} outstanding.",
                })

            if not has_error:
                valid_invoices.append(inv)

        has_discrepancies = bool(duplicates or calculation_errors or payment_discrepancies)

        return {
            "total_invoices": len(invoices),
            "valid_invoices_count": len(valid_invoices),
            "duplicates_count": len(duplicates),
            "calculation_errors_count": len(calculation_errors),
            "payment_discrepancies_count": len(payment_discrepancies),
            "overdue_invoices_count": len(overdue_invoices),
            "total_amount": round(total_amount, 2),
            "total_outstanding": round(total_outstanding, 2),
            "duplicates": duplicates,
            "calculation_errors": calculation_errors,
            "payment_discrepancies": payment_discrepancies,
            "overdue_invoices": overdue_invoices,
            "valid_invoices": valid_invoices,
            "status": "CLEAN" if not has_discrepancies else "DISCREPANCIES_DETECTED",
        }
