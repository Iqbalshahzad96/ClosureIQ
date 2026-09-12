"""
Financial Exceptions API Routes
"""

from fastapi import APIRouter
from typing import Dict, Any, List

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])


@router.get("/", response_model=List[Dict[str, Any]])
async def list_exceptions() -> List[Dict[str, Any]]:
    """
    List detected financial exceptions.
    Placeholder for Milestone 1.
    """
    return []


@router.get("/{exception_id}", response_model=Dict[str, Any])
async def get_exception_detail(exception_id: str) -> Dict[str, Any]:
    """
    Retrieve exception detail by ID.
    """
    return {
        "exception_id": exception_id,
        "type": "unmatched_transaction",
        "severity": "medium",
        "status": "open",
        "description": "Placeholder exception item"
    }
