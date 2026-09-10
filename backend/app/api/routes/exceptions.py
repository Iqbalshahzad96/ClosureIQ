"""
Financial Exceptions API Routes
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import ExceptionRecord
from app.database.schemas import ExceptionRecordResponse

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])


@router.get("/", response_model=List[ExceptionRecordResponse])
async def list_exceptions(
    period: Optional[str] = Query(default=None, description="Filter by period (e.g. 2026-Q1)"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (OPEN, IN_REVIEW, RESOLVED)"),
    category: Optional[str] = Query(default=None, description="Filter by category (RECONCILIATION, ACCRUAL, DEPRECIATION)"),
    limit: int = Query(default=100, ge=1, le=500, description="Max records to return"),
    db: Session = Depends(get_db),
) -> List[ExceptionRecordResponse]:
    """
    List detected financial exceptions persisted in the database.
    """
    if db is None:
        return []

    query = db.query(ExceptionRecord)
    if period:
        query = query.filter(ExceptionRecord.period == period)
    if status_filter:
        query = query.filter(ExceptionRecord.status == status_filter.upper())
    if category:
        query = query.filter(ExceptionRecord.category == category.upper())

    records = query.order_by(ExceptionRecord.created_at.desc()).limit(limit).all()
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
