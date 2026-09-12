"""
LangGraph Orchestrator Tests
"""

import asyncio
from app.orchestrator.state import OrchestratorState
from app.orchestrator.graph import build_financial_close_graph
from app.orchestrator.nodes import (
    deterministic_reconciliation_node,
    financial_review_node,
    exception_analysis_node,
    human_in_the_loop_gate_node,
)


def test_orchestrator_state_defaults():
    state = OrchestratorState(run_id="run_test_01", period="2026-Q1")
    assert state.run_id == "run_test_01"
    assert state.period == "2026-Q1"
    assert state.requires_human_approval is True
    assert state.status == "initialized"


def test_build_graph():
    graph = build_financial_close_graph()
    assert "nodes" in graph
    assert len(graph["nodes"]) == 4


def test_nodes_execution():
    state = OrchestratorState(run_id="run_01")
    res1 = asyncio.run(deterministic_reconciliation_node(state))
    assert res1["status"] == "reconciled"

    res2 = asyncio.run(financial_review_node(state))
    assert res2["status"] == "review_complete"

    res3 = asyncio.run(exception_analysis_node(state))
    assert res3["status"] == "exceptions_analyzed"

    res4 = asyncio.run(human_in_the_loop_gate_node(state))
    assert res4["status"] == "awaiting_human_decision"
