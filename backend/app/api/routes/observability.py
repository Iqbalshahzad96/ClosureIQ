"""
Observability, Metrics, and Run Traces API Routes
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status

from app.services.workflow_service import (
    ObservabilityStorageError,
    WorkflowService,
    get_workflow_service,
)

logger = logging.getLogger("closureiq.observability")

router = APIRouter(prefix="/observability", tags=["Observability"])


@router.get("/metrics", response_model=Dict[str, Any])
async def get_metrics(
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Retrieve operational metrics (latency, token usage, runs, errors, HITL approvals).
    """
    try:
        return await workflow_service.metrics_collector.get_summary()
    except ObservabilityStorageError as exc:
        logger.error("Failed to retrieve metrics: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Observability storage unavailable",
        )
    except Exception as exc:
        logger.error("Unexpected error retrieving metrics: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Observability storage unavailable",
        )


@router.get("/runs", response_model=List[Dict[str, Any]])
async def list_runs(
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> List[Dict[str, Any]]:
    """
    List historical and active LangGraph runs and agent execution logs.
    """
    try:
        return await workflow_service.list_runs()
    except ObservabilityStorageError as exc:
        logger.error("Database error listing runs: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Observability storage unavailable",
        )
    except Exception as exc:
        logger.error("Unexpected error listing runs: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Observability storage unavailable",
        )


@router.get("/runs/{run_id}", response_model=Dict[str, Any])
async def get_run_trace(
    run_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> Dict[str, Any]:
    """
    Retrieve full trace and audit trail for a specific run ID.
    Returns HTTP 404 if the run ID cannot be found.
    """
    if not run_id or not run_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id cannot be blank or whitespace",
        )

    try:
        trace = await workflow_service.get_run_trace(run_id)
    except ObservabilityStorageError as exc:
        logger.error("Database error retrieving run trace for %s: %s", run_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Observability storage unavailable",
        )
    except Exception as exc:
        logger.error("Unexpected error retrieving run trace for %s: %s", run_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Observability storage unavailable",
        )

    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run trace '{run_id}' not found",
        )
    return trace
