"""
Pydantic Schemas for Request and Response Models
"""

from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class FinancialRecordBase(BaseModel):
    id: str
    source: str
    account_code: str
    amount: float
    description: Optional[str] = None
    reference: Optional[str] = None
    is_reconciled: bool = False

    model_config = ConfigDict(from_attributes=True)


class ExceptionRecordResponse(BaseModel):
    id: str
    period: str
    category: str
    severity: str
    amount_variance: float
    description: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditTrailRecordResponse(BaseModel):
    id: str
    run_id: str
    event_type: str
    details: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
