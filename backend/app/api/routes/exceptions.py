"""
Financial Exceptions API Routes
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import ExceptionRecord
from app.database.schemas import ExceptionRecordResponse

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])


@router.get("/summary")
async def get_exceptions_summary(
    period: Optional[str] = Query(default=None, description="Filter by period"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieve aggregated summary metrics across all matching exceptions in the database.
    """
    if db is None:
        return {
            "total_count": 0,
            "open_count": 0,
            "in_review_count": 0,
            "resolved_count": 0,
            "high_severity_count": 0,
            "gross_variance_volume": 0.0,
            "unposted_bank_fees": 0.0,
        }

    query = db.query(ExceptionRecord)
    if period and isinstance(period, str):
        query = query.filter(ExceptionRecord.period == period.strip())
    if status_filter and isinstance(status_filter, str):
        query = query.filter(ExceptionRecord.status == status_filter.strip().upper())
    if category and isinstance(category, str):
        query = query.filter(ExceptionRecord.category == category.strip().upper())

    all_records = query.all()
    total_count = len(all_records)
    open_count = sum(1 for r in all_records if (r.status or "").upper() == "OPEN")
    in_review_count = sum(1 for r in all_records if (r.status or "").upper() == "IN_REVIEW")
    resolved_count = sum(1 for r in all_records if (r.status or "").upper() == "RESOLVED")
    high_count = sum(1 for r in all_records if (r.severity or "").upper() in ["HIGH", "CRITICAL"])
    gross_variance = sum(abs(float(r.amount_variance or 0)) for r in all_records)
    bank_fees = sum(
        abs(float(r.amount_variance or 0))
        for r in all_records
        if r.bank_transaction_id and any(
            kw in (r.description or "").lower() for kw in ["fee", "charge", "pb-", "sc-", "tariff"]
        )
    )

    return {
        "total_count": total_count,
        "open_count": open_count,
        "in_review_count": in_review_count,
        "resolved_count": resolved_count,
        "high_severity_count": high_count,
        "gross_variance_volume": gross_variance,
        "unposted_bank_fees": bank_fees,
    }


@router.get("/", response_model=List[ExceptionRecordResponse])
async def list_exceptions(
    period: Optional[str] = Query(default=None, description="Filter by period (e.g. 2026-Q1)"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (OPEN, IN_REVIEW, RESOLVED)"),
    category: Optional[str] = Query(default=None, description="Filter by category (RECONCILIATION, ACCRUAL, DEPRECIATION)"),
    limit: int = Query(default=50, ge=1, le=500, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Offset / skip count for pagination"),
    response: Response = None,
    db: Session = Depends(get_db),
) -> List[ExceptionRecordResponse]:
    """
    List detected financial exceptions persisted in the database with pagination support.
    """
    if db is None:
        return []

    limit_val = limit if isinstance(limit, int) else 50
    offset_val = offset if isinstance(offset, int) else 0

    query = db.query(ExceptionRecord)
    if period and isinstance(period, str):
        query = query.filter(ExceptionRecord.period == period.strip())
    if status_filter and isinstance(status_filter, str):
        query = query.filter(ExceptionRecord.status == status_filter.strip().upper())
    if category and isinstance(category, str):
        query = query.filter(ExceptionRecord.category == category.strip().upper())

    total_count = query.count()
    if response is not None and hasattr(response, "headers"):
        response.headers["X-Total-Count"] = str(total_count)
        response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"

    records = query.order_by(ExceptionRecord.created_at.desc()).offset(offset_val).limit(limit_val).all()
    return records


@router.get("/{exception_id}", response_model=ExceptionRecordResponse)
async def get_exception_detail(
    exception_id: str,
    db: Session = Depends(get_db),
) -> ExceptionRecordResponse:
    """
    Retrieve details for a specific persisted financial exception by ID.
    """
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database session unavailable",
        )

    record = db.get(ExceptionRecord, exception_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception '{exception_id}' not found",
        )
    return record
