"""Workflow trace formatting derived only from recorded execution data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


class RunTracer:
    """Collect an ordered in-memory trace for one run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: List[Dict[str, Any]] = []

    def log_event(self, event_type: str, details: Dict[str, Any]) -> None:
        self.events.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "details": details,
            }
        )

    def get_trace(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": self.events,
        }


def format_run_trace(run_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build the public trace shape without estimating unavailable values."""
    trace_log = list(run_data.get("trace_log") or [])
    explicit_latency = run_data.get("total_latency_ms")
    total_latency_ms = (
        round(float(explicit_latency), 2)
        if explicit_latency is not None
        else round(
            sum(
                float(entry.get("latency_ms", 0.0))
                for entry in trace_log
                if isinstance(entry, dict)
            ),
            2,
        )
    )

    agent_executions: List[Dict[str, Any]] = []
    for entry in trace_log:
        if not isinstance(entry, dict):
            continue
        node = entry.get("node")
        common = {
            "status": entry.get("status"),
            "latency_ms": entry.get("latency_ms", 0.0),
            "timestamp": entry.get("timestamp"),
            "error": entry.get("error"),
        }
        if node == "agent_1_review":
            review = run_data.get("agent_1_review") or {}
            findings = review.get("findings", []) if isinstance(review, dict) else []
            agent_executions.append(
                {
                    "agent": "Agent 1 (Financial Review Agent)",
                    "node": node,
                    **common,
                    "findings_count": len(findings),
                }
            )
        elif node == "agent_2_analysis":
            agent_executions.append(
                {
                    "agent": "Agent 2 (Exception Analysis Agent)",
                    "node": node,
                    **common,
                    "analyses_count": len(run_data.get("agent_2_analyses") or []),
                    "recommendations_count": len(run_data.get("recommendations") or []),
                }
            )

    workflow_type = str(run_data.get("workflow_type", "reconciliation"))
    input_params = run_data.get("input_params") or {}
    financial_data = run_data.get("financial_data") or {}
    recorded_calls = financial_data.get("mcp_calls", []) if isinstance(financial_data, dict) else []
    mcp_calls: List[Dict[str, Any]] = []
    for call in recorded_calls:
        if not isinstance(call, dict):
            continue
        tool_name = call.get("tool", "")
        mcp_calls.append(
            {
                "node": call.get("node", "fetch_data"),
                "workflow_type": call.get("workflow_type", workflow_type),
                "tool": tool_name,
                "tools": [tool_name] if tool_name else list(call.get("tools") or []),
                "status": call.get("status"),
                "latency_ms": call.get("latency_ms", 0.0),
                "timestamp": call.get("timestamp"),
                "parameters": call.get("parameters", input_params),
                "records_fetched": call.get("records_fetched", 0),
                "error": call.get("error"),
            }
        )

    policy_contexts = run_data.get("policy_contexts") or []
    rag_retrievals: List[Dict[str, Any]] = []
    for entry in trace_log:
        if isinstance(entry, dict) and entry.get("node") == "retrieve_policy_evidence":
            rag_retrievals.append(
                {
                    "node": "retrieve_policy_evidence",
                    "status": entry.get("status"),
                    "latency_ms": entry.get("latency_ms", 0.0),
                    "timestamp": entry.get("timestamp"),
                    "contexts_count": len(policy_contexts),
                    "contexts": policy_contexts,
                    "error": entry.get("error"),
                }
            )

    decision = run_data.get("hitl_decision")
    human_decision = None
    if isinstance(decision, dict) and decision.get("decision"):
        human_decision = {
            "decision": decision.get("decision"),
            "reviewer": decision.get("reviewer", ""),
            "comments": decision.get("comments", ""),
        }

    return {
        "run_id": str(run_data.get("run_id", "")),
        "workflow_type": workflow_type,
        "period": str(run_data.get("period", "")),
        "status": str(run_data.get("status", "unknown")),
        "total_latency_ms": total_latency_ms,
        "token_usage": 0,
        "agent_executions": agent_executions,
        "mcp_calls": mcp_calls,
        "rag_retrievals": rag_retrievals,
        "human_decision": human_decision,
        "errors": list(run_data.get("errors") or []),
        "trace_log": trace_log,
        "created_at": run_data.get("created_at", ""),
    }
