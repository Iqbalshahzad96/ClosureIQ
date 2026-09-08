"""
LangGraph Workflow Nodes

Each node is produced by a factory that closes over injected async dependencies.
Nodes receive state as an OrchestratorState Pydantic model and return a dict of updates.

Observability is cross-cutting: every node appends to trace_log.
Error routing: on failure, a node sets status="error", appends to errors,
and the conditional edge in graph.py routes to finalize — no downstream
business node executes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence
from uuid import UUID

from langgraph.types import interrupt
from pydantic import BaseModel

from app.orchestrator.state import OrchestratorState


# ---------------------------------------------------------------------------
# Dependency container
# ---------------------------------------------------------------------------

@dataclass
class WorkflowDeps:
    """Async callable dependencies injected into the graph builder.

    Each slot is an async callable. Production code wires real implementations;
    tests inject deterministic fakes. These are *never* stored in graph state.
    """

    fetch_data: Callable[..., Awaitable[Dict[str, Any]]]
    run_validation: Callable[..., Awaitable[Dict[str, Any]]]
    detect_exceptions: Callable[..., Awaitable[List[Dict[str, Any]]]]
    run_agent_1: Callable[..., Awaitable[Dict[str, Any]]]
    retrieve_policies: Callable[..., Awaitable[List[Dict[str, Any]]]]
    run_agent_2: Callable[..., Awaitable[Dict[str, Any]]]
    log_event: Callable[..., Awaitable[None]]


# ---------------------------------------------------------------------------
# JSON-safe normalization helper
# ---------------------------------------------------------------------------

def normalize_json_safe(obj: Any) -> Any:
    """Recursively normalize data to standard JSON-safe Python primitives.

    Supported types:
    - None, bool, int, float, str (returned as-is)
    - Decimal -> str (preserves exact financial precision)
    - date, datetime -> str (ISO-8601)
    - UUID -> str
    - Enum -> value normalized
    - BaseModel -> model_dump(mode="json") recursively normalized
    - Mapping -> dict with str keys and normalized values
    - Sequence (except str, bytes) -> list of normalized values

    Raises TypeError for unsupported types (e.g. callables, complex objects).
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, Decimal):
        return str(obj)

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    if isinstance(obj, UUID):
        return str(obj)

    if isinstance(obj, Enum):
        return normalize_json_safe(obj.value)

    if isinstance(obj, BaseModel):
        return normalize_json_safe(obj.model_dump(mode="json"))

    if isinstance(obj, Mapping):
        return {str(k): normalize_json_safe(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set, Sequence)) and not isinstance(obj, (str, bytes)):
        return [normalize_json_safe(item) for item in obj]

    raise TypeError(f"Unsupported non-JSON-safe type: {type(obj).__name__}")


# ---------------------------------------------------------------------------
# Trace helper (cross-cutting, JSON-safe)
# ---------------------------------------------------------------------------

def _trace_entry(
    node_name: str,
    status: str,
    latency_ms: float,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "node": node_name,
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if error is not None:
        entry["error"] = error
    return entry


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------

def make_fetch_data_node(deps: WorkflowDeps):
    """Fetch raw financial data via MCP for the given workflow_type."""

    async def fetch_data_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            raw_data = await deps.fetch_data(state.workflow_type, state.input_params)
            data = normalize_json_safe(raw_data)
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("fetch_data", "ok", elapsed)
            try:
                await deps.log_event("node_complete", {"node": "fetch_data"})
            except Exception:
                pass  # logging failure must not hide success
            return {
                "financial_data": data,
                "trace_log": list(state.trace_log) + [trace],
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("fetch_data", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "fetch_data", "error": str(exc)})
            except Exception:
                pass
            return {
                "status": "error",
                "errors": list(state.errors) + [f"fetch_data: {exc}"],
                "trace_log": list(state.trace_log) + [trace],
            }

    return fetch_data_node


def make_validate_financials_node(deps: WorkflowDeps):
    """Run deterministic validation for the workflow_type."""

    async def validate_financials_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            raw_results = await deps.run_validation(state.workflow_type, state.financial_data)
            results = normalize_json_safe(raw_results)
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("validate_financials", "ok", elapsed)
            try:
                await deps.log_event("node_complete", {"node": "validate_financials"})
            except Exception:
                pass
            return {
                "validation_results": results,
                "trace_log": list(state.trace_log) + [trace],
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("validate_financials", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "validate_financials", "error": str(exc)})
            except Exception:
                pass
            return {
                "status": "error",
                "errors": list(state.errors) + [f"validate_financials: {exc}"],
                "trace_log": list(state.trace_log) + [trace],
            }

    return validate_financials_node


def make_detect_exceptions_node(deps: WorkflowDeps):
    """Detect exceptions from validation results."""

    async def detect_exceptions_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            raw_exceptions = await deps.detect_exceptions(state.workflow_type, state.validation_results)
            exceptions = normalize_json_safe(raw_exceptions)
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("detect_exceptions", "ok", elapsed)
            try:
                await deps.log_event("node_complete", {"node": "detect_exceptions"})
            except Exception:
                pass
            return {
                "exceptions": exceptions,
                "trace_log": list(state.trace_log) + [trace],
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("detect_exceptions", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "detect_exceptions", "error": str(exc)})
            except Exception:
                pass
            return {
                "status": "error",
                "errors": list(state.errors) + [f"detect_exceptions: {exc}"],
                "trace_log": list(state.trace_log) + [trace],
            }

    return detect_exceptions_node


def make_agent_1_review_node(deps: WorkflowDeps):
    """Agent 1 reviews exceptions with deterministic validation context."""

    async def agent_1_review_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            raw_review = await deps.run_agent_1(state.exceptions, state.validation_results)
            review = normalize_json_safe(raw_review)
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("agent_1_review", "ok", elapsed)
            try:
                await deps.log_event("node_complete", {"node": "agent_1_review"})
            except Exception:
                pass
            return {
                "agent_1_review": review,
                "trace_log": list(state.trace_log) + [trace],
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("agent_1_review", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "agent_1_review", "error": str(exc)})
            except Exception:
                pass
            return {
                "status": "error",
                "errors": list(state.errors) + [f"agent_1_review: {exc}"],
                "trace_log": list(state.trace_log) + [trace],
            }

    return agent_1_review_node


def make_retrieve_policy_evidence_node(deps: WorkflowDeps):
    """Retrieve RAG policy evidence per exception, using Agent 1's classification."""

    async def retrieve_policy_evidence_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            per_exception_evidence: List[Dict[str, Any]] = []

            for exc in state.exceptions:
                raw_evidence = await deps.retrieve_policies(exc, state.agent_1_review)
                evidence = normalize_json_safe(raw_evidence)
                exc_id = exc.get("id") if isinstance(exc, dict) else getattr(exc, "id", None)
                per_exception_evidence.append({
                    "exception_id": exc_id,
                    "evidence": evidence,
                })

            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("retrieve_policy_evidence", "ok", elapsed)
            try:
                await deps.log_event("node_complete", {"node": "retrieve_policy_evidence"})
            except Exception:
                pass
            return {
                "policy_contexts": per_exception_evidence,
                "trace_log": list(state.trace_log) + [trace],
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("retrieve_policy_evidence", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "retrieve_policy_evidence", "error": str(exc)})
            except Exception:
                pass
            return {
                "status": "error",
                "errors": list(state.errors) + [f"retrieve_policy_evidence: {exc}"],
                "trace_log": list(state.trace_log) + [trace],
            }

    return retrieve_policy_evidence_node


def make_agent_2_analysis_node(deps: WorkflowDeps):
    """Agent 2 analyzes each exception with Agent 1 review and matched RAG evidence."""

    async def agent_2_analysis_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()
        try:
            exceptions = state.exceptions
            policy_contexts = state.policy_contexts

            analyses: List[Dict[str, Any]] = []
            recommendations: List[Dict[str, Any]] = []

            for idx, exc in enumerate(exceptions):
                # Preserve evidence by list position / per-exception record
                if idx < len(policy_contexts):
                    pc = policy_contexts[idx]
                    matched_evidence = pc.get("evidence", []) if isinstance(pc, dict) else pc
                else:
                    matched_evidence = []

                raw_analysis = await deps.run_agent_2(exc, state.agent_1_review, matched_evidence)
                analysis = normalize_json_safe(raw_analysis)
                analyses.append(analysis)

                if isinstance(analysis, dict) and "recommended_action" in analysis:
                    exc_id = exc.get("id") if isinstance(exc, dict) else getattr(exc, "id", None)
                    recommendations.append({
                        "exception_id": exc_id,
                        "action": analysis["recommended_action"],
                        "analysis_summary": analysis.get("root_cause_hypothesis", ""),
                    })

            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("agent_2_analysis", "ok", elapsed)
            try:
                await deps.log_event("node_complete", {"node": "agent_2_analysis"})
            except Exception:
                pass
            return {
                "agent_2_analyses": analyses,
                "recommendations": recommendations,
                "trace_log": list(state.trace_log) + [trace],
            }
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("agent_2_analysis", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "agent_2_analysis", "error": str(exc)})
            except Exception:
                pass
            return {
                "status": "error",
                "errors": list(state.errors) + [f"agent_2_analysis: {exc}"],
                "trace_log": list(state.trace_log) + [trace],
            }

    return agent_2_analysis_node


def make_hitl_gate_node(deps: WorkflowDeps):
    """HITL gate: pause execution and wait for human approval/rejection.

    CRITICAL: interrupt() must NOT be wrapped in try/except Exception,
    because LangGraph uses a special internal exception to pause execution.
    The node re-executes from the top on resume, so no non-idempotent
    side effects may precede the interrupt() call.
    """

    async def hitl_gate_node(state: OrchestratorState) -> Dict[str, Any]:
        # Build the payload that the human reviewer will see.
        payload = normalize_json_safe({
            "run_id": state.run_id,
            "workflow_type": state.workflow_type,
            "exceptions_count": len(state.exceptions),
            "recommendations": state.recommendations,
        })

        # interrupt() MUST be outside try/except — LangGraph raises internally.
        decision = interrupt(payload)

        # --- Node resumes here after Command(resume=...) ---
        t0 = time.monotonic()
        try:
            # Validate the human's decision
            if not isinstance(decision, dict) or decision.get("decision") not in (
                "approved",
                "rejected",
            ):
                raise ValueError(
                    f"Invalid HITL decision: expected {{'decision': 'approved'|'rejected'}}, "
                    f"got {decision!r}"
                )

            norm_decision = normalize_json_safe(decision)
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("hitl_gate", norm_decision["decision"], elapsed)
            try:
                await deps.log_event(
                    "hitl_decision",
                    {"node": "hitl_gate", "decision": norm_decision["decision"]},
                )
            except Exception:
                pass

            return {
                "hitl_decision": norm_decision,
                "trace_log": list(state.trace_log) + [trace],
            }
        except ValueError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            trace = _trace_entry("hitl_gate", "error", elapsed, error=str(exc))
            try:
                await deps.log_event("node_error", {"node": "hitl_gate", "error": str(exc)})
            except Exception:
                pass
            raw_decision = (
                normalize_json_safe(decision)
                if isinstance(decision, dict)
                else {"raw": str(decision)}
            )
            return {
                "status": "error",
                "errors": list(state.errors) + [f"hitl_gate: {exc}"],
                "hitl_decision": raw_decision,
                "trace_log": list(state.trace_log) + [trace],
            }

    return hitl_gate_node


def make_finalize_node(deps: WorkflowDeps):
    """Terminal node: set final status based on state."""

    async def finalize_node(state: OrchestratorState) -> Dict[str, Any]:
        t0 = time.monotonic()

        # Determine terminal status
        if state.status == "error":
            final_status = "error"
        elif not state.exceptions:
            final_status = "clean_close"
        else:
            decision = (
                state.hitl_decision.get("decision", "")
                if isinstance(state.hitl_decision, dict)
                else ""
            )
            if decision == "approved":
                final_status = "approved"
            elif decision == "rejected":
                final_status = "rejected"
            else:
                final_status = "error"

        elapsed = (time.monotonic() - t0) * 1000
        trace = _trace_entry("finalize", final_status, elapsed)
        try:
            await deps.log_event("workflow_complete", {"status": final_status})
        except Exception:
            pass

        return {
            "status": final_status,
            "trace_log": list(state.trace_log) + [trace],
        }

    return finalize_node


# ---------------------------------------------------------------------------
# Conditional-edge routing functions
# ---------------------------------------------------------------------------

def route_after_detect(state: OrchestratorState) -> str:
    """After detect_exceptions: error → finalize, no exceptions → finalize, else → agent_1."""
    if state.status == "error":
        return "finalize"
    if not state.exceptions:
        return "finalize"
    return "agent_1_review"


def route_after_business_node(state: OrchestratorState) -> str:
    """Generic: error → finalize, else → next (returned by the edge map)."""
    if state.status == "error":
        return "finalize"
    return "continue"


def route_after_hitl(state: OrchestratorState) -> str:
    """After HITL: always go to finalize (decision is recorded in state)."""
    return "finalize"
