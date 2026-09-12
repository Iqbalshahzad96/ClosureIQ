"""
Financial Exception Generator

Transforms discrepancies from reconciliation, accruals, and depreciation engines
into standardized, structured, auditable FinancialException models matching the database schema.
"""

from __future__ import annotations

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
            "amount_variance": round(self.amount_variance, 2),
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class ExceptionGenerator:
    """Generates standardized financial exceptions with deterministic severity grading."""

    def __init__(
        self,
        high_severity_threshold: float = 1000.0,
        medium_severity_threshold: float = 50.0,
    ) -> None:
        self.high_threshold = max(0.0, float(high_severity_threshold))
        self.medium_threshold = max(0.0, float(medium_severity_threshold))

    def determine_severity(
        self,
        amount_variance: float,
        override_severity: Optional[str] = None,
    ) -> str:
        """Deterministically determine exception severity based on dollar variance amount."""
        if override_severity in {"HIGH", "MEDIUM", "LOW"}:
            return override_severity

        abs_amount = abs(amount_variance)
        if abs_amount >= self.high_threshold:
            return "HIGH"
        elif abs_amount >= self.medium_threshold:
            return "MEDIUM"
        else:
            return "LOW"

    def from_reconciliation(
        self,
        reconciliation_output: Dict[str, Any],
        period: str = "CURRENT",
    ) -> List[FinancialException]:
        """Convert unmatched GL and bank items from reconciliation into exceptions."""
        exceptions: List[FinancialException] = []

        # Unmatched GL lines
        for gl_item in reconciliation_output.get("unmatched_gl", []):
            amount = float(gl_item.get("amount", 0.0))
            ref = gl_item.get("reference") or gl_item.get("id") or "N/A"
            account_code = gl_item.get("account_code") or "N/A"
            desc = (
                f"Unmatched GL transaction: Ref={ref}, Account={account_code}, "
                f"Amount=${amount:,.2f}. No corresponding bank entry found."
            )
            exceptions.append(
                FinancialException(
                    id=f"exc_rec_gl_{uuid.uuid4().hex[:8]}",
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
            desc = (
                f"Unmatched Bank statement transaction: Ref={ref}, Account={account_code}, "
                f"Amount=${amount:,.2f}. No corresponding GL entry posted."
            )
            exceptions.append(
                FinancialException(
                    id=f"exc_rec_bank_{uuid.uuid4().hex[:8]}",
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

    def generate_exceptions(
        self,
        engine_output: Dict[str, Any],
        period: str = "CURRENT",
        category: Optional[str] = None,
    ) -> List[FinancialException]:
        """Dispatch and generate exceptions from any financial engine output dictionary."""
        # Auto-detect category or use provided category
        if category == "RECONCILIATION" or ("unmatched_gl" in engine_output or "unmatched_bank" in engine_output):
            return self.from_reconciliation(engine_output, period=period)
        elif category == "ACCRUAL" or "anomalies" in engine_output:
            return self.from_accruals(engine_output, period=period)
        elif category == "DEPRECIATION" or "discrepancies" in engine_output:
            return self.from_depreciation(engine_output, period=period)
        return []
