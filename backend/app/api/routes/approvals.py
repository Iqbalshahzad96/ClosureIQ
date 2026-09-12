"""
Human-in-the-Loop (HITL) Approvals API Routes
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.workflow_service import (
    RunConflictError,
    RunNotFoundError,
    WorkflowService,
    get_workflow_service,
)

router = APIRouter(prefix="/approvals", tags=["Approvals"])


class ApprovalActionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    decision: str = Field(..., description="Approval decision: 'approved' | 'rejected' (case-insensitive)")
    reviewer: str = Field(default="Accountant", description="Name or role of the human reviewer")
    comments: str = Field(default="", description="Optional audit notes or reason")

    @field_validator("decision")
    @classmethod
    def validate_decision_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Decision cannot be blank or whitespace")
        return v


@router.get("/pending", response_model=List[Dict[str, Any]])
async def list_pending_approvals(
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> List[Dict[str, Any]]:
    """
    List workflows currently paused at the HITL gate awaiting human review and approval.
    """
    return await workflow_service.list_pending_approvals()


@router.post("/{run_id}/decision", response_model=Dict[str, Any])
async def submit_approval_decision(
    run_id: str,
    action: ApprovalActionRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Submit human review decision (Approve or Reject) to resume the paused LangGraph workflow checkpoint.
    """
    if not run_id or not run_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id cannot be blank or whitespace",
        )

    try:
        result = await workflow_service.resume_decision(
            run_id=run_id,
            decision=action.decision,
            reviewer=action.reviewer,
            comments=action.comments,
        )
        return result
    except RunConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (RunNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Approval resume failed: {exc}",
        )
