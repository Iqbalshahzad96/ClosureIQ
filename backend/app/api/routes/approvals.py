"""
Human-in-the-Loop (HITL) Approvals API Routes
"""

from fastapi import APIRouter
from typing import Dict, Any, List
from pydantic import BaseModel

router = APIRouter(prefix="/approvals", tags=["Approvals"])


class ApprovalActionRequest(BaseModel):
    decision: str  # "APPROVED" | "REJECTED"
    reviewer: str
    comments: str = ""


@router.get("/pending", response_model=List[Dict[str, Any]])
async def list_pending_approvals() -> List[Dict[str, Any]]:
    """
    List AI recommendations pending human review and approval.
    """
    return []


@router.post("/{item_id}/decision", response_model=Dict[str, Any])
async def submit_approval_decision(
    item_id: str,
    action: ApprovalActionRequest
) -> Dict[str, Any]:
    """
    Submit human review decision (Approve or Reject) for an AI recommendation.
    """
    return {
        "item_id": item_id,
        "decision": action.decision,
        "reviewer": action.reviewer,
        "status": "completed",
        "message": f"Recommendation successfully {action.decision.lower()}."
    }
