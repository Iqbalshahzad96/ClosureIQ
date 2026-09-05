"""
Financial Exception Generator

Generates structured exception objects when tolerances, reconciliations, or rules fail.
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field


class FinancialException(BaseModel):
    """Structured representation of a financial exception."""

    id: str
    category: str  # "RECONCILIATION" | "ACCRUAL" | "DEPRECIATION"
    severity: str  # "HIGH" | "MEDIUM" | "LOW"
    amount_variance: float
    description: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExceptionGenerator:
    """Generates categorized exceptions from engine discrepancies."""

    def generate_exceptions(
        self,
        engine_output: Dict[str, Any]
    ) -> List[FinancialException]:
        """Convert engine discrepancies into standardized exception models."""
        return []
