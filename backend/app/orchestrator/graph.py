"""
LangGraph Workflow Graph Builder

Builds and compiles the StateGraph for the financial close workflow.
Dependencies are injected via WorkflowDeps; the checkpointer is injected
for testability (MemorySaver in tests, persistent store in production).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.orchestrator.nodes import (
    WorkflowDeps,
    make_agent_1_review_node,
    make_agent_2_analysis_node,
    make_detect_exceptions_node,
    make_fetch_data_node,
    make_finalize_node,
    make_hitl_gate_node,
    make_retrieve_policy_evidence_node,
    make_validate_financials_node,
    route_after_business_node,
    route_after_detect,
    route_after_hitl,
)
from app.orchestrator.state import OrchestratorState


def build_financial_close_graph(deps: WorkflowDeps, checkpointer: Any) -> Any:
    """Build and compile the financial close workflow graph.

    Parameters
    ----------
    deps : WorkflowDeps
        Async callable dependencies for MCP, engines, agents, RAG, and logging.
    checkpointer
        A LangGraph-compatible checkpointer (e.g. ``MemorySaver``).

    Returns
    -------
    CompiledStateGraph
        A compiled graph ready for ``ainvoke`` / ``astream``.
    """
    graph = StateGraph(OrchestratorState)

    # --- Register nodes ---
    graph.add_node("fetch_data", make_fetch_data_node(deps))
    graph.add_node("validate_financials", make_validate_financials_node(deps))
    graph.add_node("detect_exceptions", make_detect_exceptions_node(deps))
    graph.add_node("agent_1_review", make_agent_1_review_node(deps))
    graph.add_node("retrieve_policy_evidence", make_retrieve_policy_evidence_node(deps))
    graph.add_node("agent_2_analysis", make_agent_2_analysis_node(deps))
    graph.add_node("hitl_gate", make_hitl_gate_node(deps))
    graph.add_node("finalize", make_finalize_node(deps))

    # --- Linear edges ---
    graph.add_edge(START, "fetch_data")

    # fetch_data → validate (or finalize on error)
    graph.add_conditional_edges(
        "fetch_data",
        route_after_business_node,
        {"continue": "validate_financials", "finalize": "finalize"},
    )

    # validate → detect (or finalize on error)
    graph.add_conditional_edges(
        "validate_financials",
        route_after_business_node,
        {"continue": "detect_exceptions", "finalize": "finalize"},
    )

    # detect → agent_1 | finalize (branching on exceptions & error)
    graph.add_conditional_edges(
        "detect_exceptions",
        route_after_detect,
        {
            "agent_1_review": "agent_1_review",
            "finalize": "finalize",
        },
    )

    # agent_1 → retrieve_policy (or finalize on error)
    graph.add_conditional_edges(
        "agent_1_review",
        route_after_business_node,
        {"continue": "retrieve_policy_evidence", "finalize": "finalize"},
    )

    # retrieve_policy → agent_2 (or finalize on error)
    graph.add_conditional_edges(
        "retrieve_policy_evidence",
        route_after_business_node,
        {"continue": "agent_2_analysis", "finalize": "finalize"},
    )

    # agent_2 → hitl_gate (or finalize on error)
    graph.add_conditional_edges(
        "agent_2_analysis",
        route_after_business_node,
        {"continue": "hitl_gate", "finalize": "finalize"},
    )

    # hitl_gate → finalize (always)
    graph.add_conditional_edges(
        "hitl_gate",
        route_after_hitl,
        {"finalize": "finalize"},
    )

    # finalize → END
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
