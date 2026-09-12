"""
Orchestration State Definition for LangGraph

Pydantic BaseModel state tracked across nodes during financial close review.
All mutable defaults use Field(default_factory=...) for isolation.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class OrchestratorState(BaseModel):
    """Workflow state tracked across nodes during financial close review."""

    # --- Run identity ---
    run_id: str = Field(
        default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}",
        description="Unique run identifier, doubles as LangGraph thread_id.",
    )
    workflow_type: Literal["reconciliation", "accrual", "depreciation"] = Field(
        default="reconciliation",
        description="Financial workflow to execute.",
    )
    period: str = Field(default="", description="Financial close period (e.g., 2026-Q1)")

    # --- Generic workflow data ---
    input_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Generic workflow inputs (account_code, asset_id, etc.)",
    )
    financial_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw records from MCP, keyed by workflow-type needs.",
    )

    # --- Deterministic engine output ---
    validation_results: Dict[str, Any] = Field(
        default_factory=dict,
        description="Output from the deterministic financial engine for the current workflow_type.",
    )
    # Retained for backward compatibility with existing code that references it.
    reconciliation_results: Dict[str, Any] = Field(
        default_factory=dict,
        description="(Legacy) Reconciliation-specific engine output.",
    )

    # --- Exceptions ---
    exceptions: List[Dict[str, Any]] = Field(default_factory=list)

    # --- Agent outputs ---
    agent_1_review: Dict[str, Any] = Field(
        default_factory=dict,
        description="Agent 1 review: classification and assessment of exceptions.",
    )
    agent_2_analyses: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-exception analyses from Agent 2, each with matched RAG evidence.",
    )
    policy_contexts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-exception RAG evidence, populated by retrieve_policy_evidence node.",
    )
    recommendations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Final recommendations extracted from Agent 2 analyses.",
    )

    # --- HITL ---
    requires_human_approval: bool = Field(default=True)
    hitl_decision: Dict[str, Any] = Field(
        default_factory=dict,
        description='Human decision: {"decision": "approved"|"rejected", ...}',
    )

    # --- Observability ---
    status: str = Field(
        default="initialized",
        description="Current workflow status. Terminal: clean_close | approved | rejected | error",
    )
    errors: List[str] = Field(default_factory=list)
    trace_log: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Cross-cutting observability events appended by every node.",
    )

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("run_id cannot be empty")
        return str(v)
