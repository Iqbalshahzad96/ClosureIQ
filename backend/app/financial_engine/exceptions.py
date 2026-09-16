"""
Financial Exception Generator

Transforms discrepancies from reconciliation, accruals, and depreciation engines
into standardized, structured, auditable FinancialException models matching the database schema.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FinancialException(BaseModel):
    """Structured representation of a financial exception for audits and AI agents."""

    id: str = Field(default_factory=lambda: f"exc_{uuid.uuid4().hex[:10]}")
    period: str = "CURRENT"
    category: str  # "RECONCILIATION" | "ACCRUAL" | "DEPRECIATION" | "GENERAL"
    severity: str = "MEDIUM"  # "HIGH" | "MEDIUM" | "LOW"
    amount_variance: float = 0.0
    description: str = ""
    status: str = "OPEN"  # "OPEN" | "IN_REVIEW" | "RESOLVED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize exception to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "period": self.period,
            "category": self.category,
            "severity": self.severity,
            "amount_variance": self.amount_variance,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class ExceptionGenerator:
    """Standardizes anomalies across reconciliation, accrual, and depreciation engines."""

    HIGH_THRESHOLD: float = 10000.0
    MEDIUM_THRESHOLD: float = 1000.0

    def determine_severity(self, amount: float) -> str:
        """Assign severity based on financial materiality thresholds."""
        abs_amt = abs(amount)
        if abs_amt >= self.HIGH_THRESHOLD:
            return "HIGH"
        if abs_amt >= self.MEDIUM_THRESHOLD:
            return "MEDIUM"
        return "LOW"

    def from_reconciliation(
        self,
        reconciliation_output: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[FinancialException]:
        """Convert unmatched GL and bank items from reconciliation into exceptions with deterministic stable IDs."""
        exceptions: List[FinancialException] = []

        # Unmatched GL lines
        for gl_item in reconciliation_output.get("unmatched_gl", []):
            amount = float(gl_item.get("amount", 0.0))
            ref = gl_item.get("reference") or gl_item.get("id") or "N/A"
            account_code = gl_item.get("account_code") or "N/A"
            gl_key = gl_item.get("id") or ref
            stable_id = f"exc_rec_gl_{hashlib.sha256(f'{period}:GL:{gl_key}:{amount:.2f}'.encode()).hexdigest()[:12]}"
            desc = (
                f"Unmatched GL transaction: Ref={ref}, Account={account_code}, "
                f"Amount=${amount:,.2f}. No corresponding bank entry found."
            )
            exceptions.append(
                FinancialException(
                    id=stable_id,
                    period=period,
                    category="RECONCILIATION",
                    severity=self.determine_severity(amount),
                    amount_variance=round(amount, 2),
                    description=desc,
                    metadata={"source": "GL", "record": gl_item},
                )
            )

        # Unmatched Bank statement lines
        for b_item in reconciliation_output.get("unmatched_bank", []):
            amount = float(b_item.get("amount", 0.0))
            ref = b_item.get("reference") or b_item.get("id") or "N/A"
            account_code = b_item.get("account_code") or "N/A"
            bank_key = b_item.get("id") or ref
            stable_id = f"exc_rec_bank_{hashlib.sha256(f'{period}:BANK:{bank_key}:{amount:.2f}'.encode()).hexdigest()[:12]}"
            desc = (
                f"Unmatched Bank statement transaction: Ref={ref}, Account={account_code}, "
                f"Amount=${amount:,.2f}. No corresponding GL entry posted."
            )
            exceptions.append(
                FinancialException(
                    id=stable_id,
                    period=period,
                    category="RECONCILIATION",
                    severity=self.determine_severity(amount),
                    amount_variance=round(amount, 2),
                    description=desc,
                    metadata={"source": "BANK", "record": b_item},
                )
            )

        return exceptions

    def from_accruals(
        self,
        accrual_output: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[FinancialException]:
        """Convert accrual anomalies and missing accruals into exceptions."""
        exceptions: List[FinancialException] = []

        for anomaly in accrual_output.get("anomalies", []):
            variance_amt = float(anomaly.get("variance_amount", 0.0))
            anomaly_type = anomaly.get("type", "ACCRUAL_ANOMALY")
            reason = anomaly.get("reason", "Accrual anomaly detected.")

            exceptions.append(
                FinancialException(
                    id=f"exc_acc_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="ACCRUAL",
                    severity=self.determine_severity(variance_amt),
                    amount_variance=round(variance_amt, 2),
                    description=f"[{anomaly_type}] {reason}",
                    metadata=anomaly,
                )
            )

        return exceptions

    def from_depreciation(
        self,
        depreciation_output: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[FinancialException]:
        """Convert depreciation discrepancies into exceptions."""
        exceptions: List[FinancialException] = []

        for disc in depreciation_output.get("discrepancies", []):
            variance = float(disc.get("variance", 0.0))
            reason = disc.get("reason", "DEPRECIATION_DISCREPANCY")
            details = disc.get("details", "")

            exceptions.append(
                FinancialException(
                    id=f"exc_dep_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="DEPRECIATION",
                    severity=self.determine_severity(variance),
                    amount_variance=round(variance, 2),
                    description=f"[{reason}] {details}",
                    metadata=disc,
                )
            )

        return exceptions

    def from_ap(
        self,
        ap_output: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[FinancialException]:
        """Convert AP duplicates, calculation breaks, and payment discrepancies into exceptions."""
        exceptions: List[FinancialException] = []

        # Duplicate invoices
        for dup in ap_output.get("duplicates", []):
            amt = float(dup.get("variance_amount", dup.get("total_amount", 0.0)))
            dtype = dup.get("type", "DUPLICATE_INVOICE")
            reason = dup.get("reason", "Duplicate invoice detected.")
            exceptions.append(
                FinancialException(
                    id=f"exc_ap_dup_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="AP_REVIEW",
                    severity=self.determine_severity(amt),
                    amount_variance=round(amt, 2),
                    description=f"[{dtype}] {reason}",
                    metadata=dup,
                )
            )

        # Calculation errors (subtotal + tax != total)
        for calc in ap_output.get("calculation_errors", []):
            diff = float(calc.get("variance_amount", 0.0))
            reason = calc.get("reason", "AP calculation mismatch.")
            exceptions.append(
                FinancialException(
                    id=f"exc_ap_calc_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="AP_REVIEW",
                    severity=self.determine_severity(diff),
                    amount_variance=round(diff, 2),
                    description=f"[CALCULATION_MISMATCH] {reason}",
                    metadata=calc,
                )
            )

        # Payment & balance discrepancies
        for pmt in ap_output.get("payment_discrepancies", []):
            amt = float(pmt.get("variance_amount", 0.0))
            ptype = pmt.get("type", "PAYMENT_DISCREPANCY")
            reason = pmt.get("reason", "AP payment balance discrepancy.")
            exceptions.append(
                FinancialException(
                    id=f"exc_ap_pmt_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="AP_REVIEW",
                    severity=self.determine_severity(amt),
                    amount_variance=round(amt, 2),
                    description=f"[{ptype}] {reason}",
                    metadata=pmt,
                )
            )

        # Overdue invoices
        for ovd in ap_output.get("overdue_invoices", []):
            amt = float(ovd.get("outstanding_amount", 0.0))
            reason = ovd.get("reason", "Overdue AP obligation.")
            exceptions.append(
                FinancialException(
                    id=f"exc_ap_ovd_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="AP_REVIEW",
                    severity=self.determine_severity(amt),
                    amount_variance=round(amt, 2),
                    description=f"[OVERDUE_INVOICE] {reason}",
                    metadata=ovd,
                )
            )

        return exceptions

    def from_trial_balance(
        self,
        tb_output: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[FinancialException]:
        """Convert trial balance continuity errors and imbalance into exceptions."""
        exceptions: List[FinancialException] = []

        # Debit/credit imbalance
        if not tb_output.get("is_balanced", True):
            diff = float(tb_output.get("debit_credit_difference", 0.0))
            exceptions.append(
                FinancialException(
                    id=f"exc_tb_bal_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="TRIAL_BALANCE",
                    severity=self.determine_severity(diff),
                    amount_variance=round(diff, 2),
                    description=(
                        f"Trial balance debit/credit imbalance: "
                        f"total debits={tb_output.get('total_debits', 0.0)}, "
                        f"total credits={tb_output.get('total_credits', 0.0)}, "
                        f"difference={diff}."
                    ),
                    metadata={"total_debits": tb_output.get("total_debits"),
                              "total_credits": tb_output.get("total_credits"),
                              "exact_variance": tb_output.get("debit_credit_difference"),
                              "record_ids": tb_output.get("record_ids", [])},
                )
            )

        # Row-level continuity errors
        for err in tb_output.get("continuity_errors", []):
            variance = float(err.get("variance", 0.0))
            reason = err.get("reason", "Continuity equation break.")
            exceptions.append(
                FinancialException(
                    id=f"exc_tb_cont_{uuid.uuid4().hex[:8]}",
                    period=period,
                    category="TRIAL_BALANCE",
                    severity=self.determine_severity(variance),
                    amount_variance=round(variance, 2),
                    description=f"[CONTINUITY_BREAK] {reason}",
                    metadata=err,
                )
            )

        return exceptions

    def generate_exceptions(
        self,
        engine_output: Dict[str, Any],
        period: str = "CURRENT",
        category: Optional[str] = None,
    ) -> List[FinancialException]:
        """Dispatch and generate exceptions from any financial engine output dictionary."""
        # Auto-detect category or use provided category
        if category in ("RECONCILIATION", "BANK_RECONCILIATION") or ("unmatched_gl" in engine_output or "unmatched_bank" in engine_output):
            return self.from_reconciliation(engine_output, period=period)
        elif category == "ACCRUAL" or "anomalies" in engine_output:
            return self.from_accruals(engine_output, period=period)
        elif category == "DEPRECIATION" or "discrepancies" in engine_output:
            return self.from_depreciation(engine_output, period=period)
        elif category in ("AP_REVIEW", "AP", "DUPLICATE") or ("duplicates" in engine_output or "calculation_errors" in engine_output or "payment_discrepancies" in engine_output):
            return self.from_ap(engine_output, period=period)
        elif category == "TRIAL_BALANCE" or "continuity_errors" in engine_output:
            return self.from_trial_balance(engine_output, period=period)
        return []
