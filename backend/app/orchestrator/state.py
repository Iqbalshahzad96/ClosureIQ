"""
Orchestration State Definition for LangGraph
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class OrchestratorState(BaseModel):
    """Workflow state tracked across nodes during financial close review."""

    run_id: str = Field(default="", description="Unique identifier for the run")
    period: str = Field(default="", description="Financial close period (e.g., 2026-Q1)")
    reconciliation_results: Dict[str, Any] = Field(default_factory=dict)
    exceptions: List[Dict[str, Any]] = Field(default_factory=list)
    agent_1_review: Dict[str, Any] = Field(default_factory=dict)
    agent_2_analyses: List[Dict[str, Any]] = Field(default_factory=list)
    policy_contexts: List[Dict[str, Any]] = Field(default_factory=list)
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    requires_human_approval: bool = Field(default=True)
    status: str = Field(default="initialized")
    errors: List[str] = Field(default_factory=list)
