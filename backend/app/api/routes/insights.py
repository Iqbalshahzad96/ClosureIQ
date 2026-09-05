"""
AI Agent Insights & Recommendations API Routes
"""

from fastapi import APIRouter
from typing import Dict, Any, List

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/", response_model=List[Dict[str, Any]])
async def list_agent_insights() -> List[Dict[str, Any]]:
    """
    List AI agent recommendations and reasoning.
    Placeholder for Milestone 1.
    """
    return []


@router.post("/generate", response_model=Dict[str, Any])
async def trigger_agent_analysis() -> Dict[str, Any]:
    """
    Trigger LangGraph AI orchestration for financial review & exception analysis.
    """
    return {
        "status": "queued",
        "orchestrator_run_id": "orch_run_placeholder_001",
        "message": "AI analysis job queued"
    }
