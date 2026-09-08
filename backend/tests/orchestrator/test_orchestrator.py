"""
LangGraph Orchestrator Tests

All tests use deterministic async fakes, MemorySaver checkpointer, unique
run_ids, pytest.mark.asyncio, and await graph.ainvoke(). Zero network,
LLM, database, MCP, or RAG calls.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from app.orchestrator.graph import build_financial_close_graph
from app.orchestrator.nodes import WorkflowDeps, normalize_json_safe
from app.orchestrator.state import OrchestratorState


# ---------------------------------------------------------------------------
# Deterministic async fakes
# ---------------------------------------------------------------------------

class FakeTracker:
    """Records calls to fakes for assertion."""

    def __init__(self) -> None:
        self.calls: Dict[str, List[Any]] = {}

    def record(self, name: str, *args: Any) -> None:
        self.calls.setdefault(name, []).append(args)


def make_fakes(
    tracker: FakeTracker,
    *,
    fetch_data_result: Any = None,
    validation_result: Any = None,
    exceptions_result: Any = None,
    agent_1_result: Any = None,
    policy_result: Any = None,
    policy_fn: Any = None,
    agent_2_result: Any = None,
    fetch_error: Exception | None = None,
    validation_error: Exception | None = None,
    detect_error: Exception | None = None,
    agent_1_error: Exception | None = None,
    rag_error: Exception | None = None,
    agent_2_error: Exception | None = None,
) -> WorkflowDeps:
    """Build a WorkflowDeps with deterministic async fakes."""

    async def fake_fetch(wf_type: str, params: Dict[str, Any]) -> Any:
        tracker.record("fetch_data", wf_type, params)
        if fetch_error:
            raise fetch_error
        return fetch_data_result if fetch_data_result is not None else {"gl": [], "bank": []}

    async def fake_validate(wf_type: str, data: Dict[str, Any]) -> Any:
        tracker.record("run_validation", wf_type, data)
        if validation_error:
            raise validation_error
        return validation_result if validation_result is not None else {"matched": [], "unmatched": []}

    async def fake_detect(wf_type: str, results: Dict[str, Any]) -> Any:
        tracker.record("detect_exceptions", wf_type, results)
        if detect_error:
            raise detect_error
        return exceptions_result if exceptions_result is not None else []

    async def fake_agent_1(exceptions: List, validation: Dict) -> Any:
        tracker.record("run_agent_1", exceptions, validation)
        if agent_1_error:
            raise agent_1_error
        return agent_1_result if agent_1_result is not None else {"classification": "reviewed", "severity_summary": "ok"}

    async def fake_policies(exc: Dict, review: Dict) -> Any:
        tracker.record("retrieve_policies", exc, review)
        if rag_error:
            raise rag_error
        if policy_fn is not None:
            return policy_fn(exc, review)
        return policy_result if policy_result is not None else [{"policy": "SOP-001", "excerpt": "test evidence"}]

    async def fake_agent_2(exc: Dict, review: Dict, evidence: List) -> Any:
        tracker.record("run_agent_2", exc, review, evidence)
        if agent_2_error:
            raise agent_2_error
        return agent_2_result if agent_2_result is not None else {
            "root_cause_hypothesis": "fake hypothesis",
            "recommended_action": "adjust entry",
            "policy_citations": [],
        }

    async def fake_log(event_type: str, details: Dict[str, Any]) -> None:
        tracker.record("log_event", event_type, details)

    return WorkflowDeps(
        fetch_data=fake_fetch,
        run_validation=fake_validate,
        detect_exceptions=fake_detect,
        run_agent_1=fake_agent_1,
        retrieve_policies=fake_policies,
        run_agent_2=fake_agent_2,
        log_event=fake_log,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_EXCEPTIONS = [
    {"id": "exc_001", "category": "RECONCILIATION", "severity": "HIGH", "amount_variance": 500.0},
    {"id": "exc_002", "category": "RECONCILIATION", "severity": "MEDIUM", "amount_variance": 50.0},
]


def _unique_run_id() -> str:
    return f"test_{uuid.uuid4().hex[:8]}"


def _build(tracker: FakeTracker, **kwargs):
    """Build a compiled graph with fakes and a fresh MemorySaver."""
    deps = make_fakes(tracker, **kwargs)
    return build_financial_close_graph(deps, checkpointer=MemorySaver())


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


# ---------------------------------------------------------------------------
# State defaults & validation
# ---------------------------------------------------------------------------


def test_state_default_isolation():
    """Each OrchestratorState instance gets independent mutable defaults."""
    s1 = OrchestratorState()
    s2 = OrchestratorState()
    s1.errors.append("x")
    s1.exceptions.append({"id": "e1"})
    s1.trace_log.append({"node": "test"})
    assert s2.errors == []
    assert s2.exceptions == []
    assert s2.trace_log == []


def test_state_run_id_non_empty():
    """run_id defaults to a non-empty UUID-based string."""
    s = OrchestratorState()
    assert s.run_id
    assert s.run_id.startswith("run_")


def test_state_run_id_empty_raises():
    """Empty run_id raises ValueError."""
    with pytest.raises(ValueError, match="run_id cannot be empty"):
        OrchestratorState(run_id="")


def test_state_workflow_type_literal():
    """workflow_type accepts only the three valid values."""
    for wt in ("reconciliation", "accrual", "depreciation"):
        s = OrchestratorState(workflow_type=wt)
        assert s.workflow_type == wt


# ---------------------------------------------------------------------------
# Normalization helper unit tests
# ---------------------------------------------------------------------------


class ColorEnum(str, Enum):
    RED = "red"
    BLUE = "blue"


class DummyModel(BaseModel):
    name: str
    amount: Decimal
    timestamp: datetime


def test_normalize_json_safe_primitives():
    """Primitives are returned unchanged."""
    assert normalize_json_safe(1) == 1
    assert normalize_json_safe(3.14) == 3.14
    assert normalize_json_safe("hello") == "hello"
    assert normalize_json_safe(True) is True
    assert normalize_json_safe(None) is None


def test_normalize_json_safe_complex_types():
    """Decimal, date, datetime, UUID, Enum, and Pydantic models are normalized."""
    u = uuid.uuid4()
    d = Decimal("99.99")
    dt = datetime(2026, 3, 1, 10, 30, 0)
    dt_date = date(2026, 3, 1)

    assert normalize_json_safe(d) == "99.99"
    assert normalize_json_safe(u) == str(u)
    assert normalize_json_safe(dt) == dt.isoformat()
    assert normalize_json_safe(dt_date) == dt_date.isoformat()
    assert normalize_json_safe(ColorEnum.RED) == "red"

    model = DummyModel(name="test", amount=d, timestamp=dt)
    norm_model = normalize_json_safe(model)
    assert isinstance(norm_model, dict)
    assert norm_model["name"] == "test"
    assert json.dumps(norm_model)  # verifiable JSON-safe


def test_normalize_json_safe_unsupported_raises():
    """Unsupported non-JSON-safe objects raise TypeError."""
    with pytest.raises(TypeError, match="Unsupported non-JSON-safe type"):
        normalize_json_safe(lambda x: x)


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------


def test_graph_compiles():
    """build_financial_close_graph returns a compiled graph object."""
    tracker = FakeTracker()
    graph = _build(tracker)
    assert hasattr(graph, "ainvoke")


# ---------------------------------------------------------------------------
# Workflow dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_reconciliation():
    """workflow_type='reconciliation' propagates to fetch_data and run_validation."""
    tracker = FakeTracker()
    graph = _build(tracker)
    run_id = _unique_run_id()
    await graph.ainvoke(
        OrchestratorState(run_id=run_id, workflow_type="reconciliation"),
        _config(run_id),
    )
    assert tracker.calls["fetch_data"][0][0] == "reconciliation"
    assert tracker.calls["run_validation"][0][0] == "reconciliation"


@pytest.mark.asyncio
async def test_dispatch_accrual():
    """workflow_type='accrual' propagates correctly."""
    tracker = FakeTracker()
    graph = _build(tracker)
    run_id = _unique_run_id()
    await graph.ainvoke(
        OrchestratorState(run_id=run_id, workflow_type="accrual"),
        _config(run_id),
    )
    assert tracker.calls["fetch_data"][0][0] == "accrual"
    assert tracker.calls["run_validation"][0][0] == "accrual"


@pytest.mark.asyncio
async def test_dispatch_depreciation():
    """workflow_type='depreciation' propagates correctly."""
    tracker = FakeTracker()
    graph = _build(tracker)
    run_id = _unique_run_id()
    await graph.ainvoke(
        OrchestratorState(run_id=run_id, workflow_type="depreciation"),
        _config(run_id),
    )
    assert tracker.calls["fetch_data"][0][0] == "depreciation"
    assert tracker.calls["run_validation"][0][0] == "depreciation"


# ---------------------------------------------------------------------------
# Call count and single execution verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dependency_call_counts_single_execution():
    """Every external dependency is invoked exactly once per intended operation."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()

    # Run to HITL pause
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    assert len(tracker.calls["fetch_data"]) == 1
    assert len(tracker.calls["run_validation"]) == 1
    assert len(tracker.calls["detect_exceptions"]) == 1
    assert len(tracker.calls["run_agent_1"]) == 1
    assert len(tracker.calls["retrieve_policies"]) == len(SAMPLE_EXCEPTIONS)
    assert len(tracker.calls["run_agent_2"]) == len(SAMPLE_EXCEPTIONS)

    # Verify Agent 1 received exactly two arguments: (exceptions, validation_results)
    assert len(tracker.calls["run_agent_1"][0]) == 2
    assert tracker.calls["run_agent_1"][0][0] == SAMPLE_EXCEPTIONS


# ---------------------------------------------------------------------------
# Clean-close path (no exceptions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_close_no_exceptions():
    """When no exceptions are detected, agents are skipped and status is clean_close."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=[])
    run_id = _unique_run_id()
    result = await graph.ainvoke(
        OrchestratorState(run_id=run_id),
        _config(run_id),
    )
    assert result["status"] == "clean_close"
    assert "run_agent_1" not in tracker.calls
    assert "run_agent_2" not in tracker.calls
    assert "retrieve_policies" not in tracker.calls


# ---------------------------------------------------------------------------
# Agents skipped on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_skipped_on_error():
    """When fetch_data fails, no downstream business node executes."""
    tracker = FakeTracker()
    graph = _build(tracker, fetch_error=RuntimeError("network down"))
    run_id = _unique_run_id()
    result = await graph.ainvoke(
        OrchestratorState(run_id=run_id),
        _config(run_id),
    )
    assert result["status"] == "error"
    assert "run_validation" not in tracker.calls
    assert "run_agent_1" not in tracker.calls
    assert "run_agent_2" not in tracker.calls


# ---------------------------------------------------------------------------
# Exception path with HITL interrupt & resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exception_path_pauses_at_hitl():
    """With exceptions, graph pauses at hitl_gate interrupt."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()
    result = await graph.ainvoke(
        OrchestratorState(run_id=run_id),
        _config(run_id),
    )
    assert "__interrupt__" in result
    snap = await graph.aget_state(_config(run_id))
    assert "hitl_gate" in snap.next


@pytest.mark.asyncio
async def test_hitl_approved():
    """Resuming with 'approved' sets status to 'approved'."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    result = await graph.ainvoke(
        Command(resume={"decision": "approved"}), _config(run_id)
    )
    assert result["status"] == "approved"
    assert result["hitl_decision"]["decision"] == "approved"


@pytest.mark.asyncio
async def test_hitl_rejected():
    """Resuming with 'rejected' sets status to 'rejected'."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    result = await graph.ainvoke(
        Command(resume={"decision": "rejected"}), _config(run_id)
    )
    assert result["status"] == "rejected"
    assert result["hitl_decision"]["decision"] == "rejected"


@pytest.mark.asyncio
async def test_hitl_invalid_decision():
    """Resuming with an invalid decision sets status to 'error'."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    result = await graph.ainvoke(
        Command(resume={"decision": "maybe"}), _config(run_id)
    )
    assert result["status"] == "error"
    assert any("Invalid HITL decision" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Per-exception RAG evidence association (list-position preservation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_exception_rag_and_agent2_input():
    """RAG is called per-exception. Agent 2 receives exception, A1 review, and matched evidence."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    assert len(tracker.calls["retrieve_policies"]) == 2
    assert len(tracker.calls["run_agent_2"]) == 2
    for call in tracker.calls["run_agent_2"]:
        exc_arg, review_arg, evidence_arg = call
        assert "id" in exc_arg
        assert isinstance(review_arg, dict)
        assert isinstance(evidence_arg, list)


@pytest.mark.asyncio
async def test_per_exception_rag_with_duplicate_and_missing_ids():
    """Duplicate or missing exception IDs do not overwrite or collapse policy evidence."""
    exceptions_fixture = [
        {"id": "duplicate_id", "category": "CATEGORY_A", "amount": 100.0},
        {"id": "duplicate_id", "category": "CATEGORY_B", "amount": 200.0},
        {"category": "MISSING_ID", "amount": 300.0},
    ]

    def policy_dispatch(exc: Dict[str, Any], review: Dict[str, Any]) -> List[Dict[str, Any]]:
        category = exc.get("category")
        return [{"policy": f"POL_{category}", "detail": f"evidence_for_{category}"}]

    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=exceptions_fixture, policy_fn=policy_dispatch)
    run_id = _unique_run_id()
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    assert len(tracker.calls["run_agent_2"]) == 3
    # Check that each Agent 2 invocation received the distinct evidence corresponding to its position
    call_0_evidence = tracker.calls["run_agent_2"][0][2]
    call_1_evidence = tracker.calls["run_agent_2"][1][2]
    call_2_evidence = tracker.calls["run_agent_2"][2][2]

    assert call_0_evidence == [{"policy": "POL_CATEGORY_A", "detail": "evidence_for_CATEGORY_A"}]
    assert call_1_evidence == [{"policy": "POL_CATEGORY_B", "detail": "evidence_for_CATEGORY_B"}]
    assert call_2_evidence == [{"policy": "POL_MISSING_ID", "detail": "evidence_for_MISSING_ID"}]


# ---------------------------------------------------------------------------
# Error routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_error_routing():
    """Fetch failure routes to finalize with error status."""
    tracker = FakeTracker()
    graph = _build(tracker, fetch_error=RuntimeError("MCP unavailable"))
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("fetch_data" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_validation_error_routing():
    """Validation failure routes to finalize with error status."""
    tracker = FakeTracker()
    graph = _build(tracker, validation_error=RuntimeError("engine crash"))
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("validate_financials" in e for e in result["errors"])
    assert "run_agent_1" not in tracker.calls


@pytest.mark.asyncio
async def test_detect_exceptions_error_routing():
    """Exception detection failure routes to finalize with error status."""
    tracker = FakeTracker()
    graph = _build(tracker, detect_error=RuntimeError("detection failed"))
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("detect_exceptions" in e for e in result["errors"])
    assert "run_agent_1" not in tracker.calls


@pytest.mark.asyncio
async def test_agent_1_error_routing():
    """Agent 1 failure routes to finalize without running Agent 2."""
    tracker = FakeTracker()
    graph = _build(
        tracker,
        exceptions_result=SAMPLE_EXCEPTIONS,
        agent_1_error=RuntimeError("agent 1 down"),
    )
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("agent_1_review" in e for e in result["errors"])
    assert "run_agent_2" not in tracker.calls


@pytest.mark.asyncio
async def test_rag_error_routing():
    """RAG failure routes to finalize without running Agent 2."""
    tracker = FakeTracker()
    graph = _build(
        tracker,
        exceptions_result=SAMPLE_EXCEPTIONS,
        rag_error=RuntimeError("chromadb unavailable"),
    )
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("retrieve_policy_evidence" in e for e in result["errors"])
    assert "run_agent_2" not in tracker.calls


@pytest.mark.asyncio
async def test_agent_2_error_routing():
    """Agent 2 failure routes to finalize with error status."""
    tracker = FakeTracker()
    graph = _build(
        tracker,
        exceptions_result=SAMPLE_EXCEPTIONS,
        agent_2_error=RuntimeError("agent 2 failed"),
    )
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("agent_2_analysis" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_unsupported_dependency_output_routes_to_error():
    """Returning an unsupported non-JSON-safe object triggers normal error routing."""
    tracker = FakeTracker()
    # Return a function/callable which cannot be serialized
    graph = _build(tracker, fetch_data_result={"unsupported_func": lambda: 42})
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    assert result["status"] == "error"
    assert any("Unsupported non-JSON-safe type" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Realistic Decimal, datetime, UUID, Pydantic outputs & JSON serialization
# ---------------------------------------------------------------------------


class SampleValidationModel(BaseModel):
    summary_id: UUID
    reconciliation_variance: Decimal
    generated_at: datetime


@pytest.mark.asyncio
async def test_realistic_outputs_and_complete_json_serialization():
    """Realistic Decimal, datetime, UUID, and Pydantic outputs normalize and serialize cleanly."""
    sample_uuid = uuid.uuid4()
    sample_dt = datetime(2026, 3, 1, 12, 0, 0)
    sample_decimal = Decimal("14250.75")

    validation_pydantic = SampleValidationModel(
        summary_id=sample_uuid,
        reconciliation_variance=sample_decimal,
        generated_at=sample_dt,
    )

    fetch_output = {
        "gl": [{"id": sample_uuid, "amount": sample_decimal, "date": sample_dt.date()}],
        "bank": [{"id": sample_uuid, "amount": sample_decimal, "date": sample_dt.date()}],
    }

    tracker = FakeTracker()
    graph = _build(
        tracker,
        fetch_data_result=fetch_output,
        validation_result=validation_pydantic,
        exceptions_result=SAMPLE_EXCEPTIONS,
    )
    run_id = _unique_run_id()

    # 1. Run until HITL pause
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))

    # Verify Decimal became string in state
    assert result["financial_data"]["gl"][0]["amount"] == "14250.75"
    assert result["validation_results"]["reconciliation_variance"] == "14250.75"

    # Verify actual interrupt payload is JSON serializable
    interrupts = result.get("__interrupt__", [])
    assert len(interrupts) > 0
    payload = interrupts[0].value
    assert isinstance(json.dumps(payload), str)

    # Verify checkpoint snapshot is JSON serializable
    snapshot = await graph.aget_state(_config(run_id))
    assert isinstance(json.dumps(snapshot.values), str)

    # 2. Resume with approval
    resumed = await graph.ainvoke(
        Command(resume={"decision": "approved"}), _config(run_id)
    )
    assert resumed["status"] == "approved"

    # Verify complete final state (excluding internal __interrupt__) is JSON serializable
    clean_state = {k: v for k, v in resumed.items() if not k.startswith("__")}
    assert isinstance(json.dumps(clean_state), str)

    # Verify all trace entries are JSON serializable
    assert isinstance(json.dumps(resumed["trace_log"]), str)


# ---------------------------------------------------------------------------
# Trace log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_log_completeness_clean_close():
    """On clean close, trace_log has entries for fetch, validate, detect, finalize."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=[])
    run_id = _unique_run_id()
    result = await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    nodes_logged = [e["node"] for e in result["trace_log"]]
    assert "fetch_data" in nodes_logged
    assert "validate_financials" in nodes_logged
    assert "detect_exceptions" in nodes_logged
    assert "finalize" in nodes_logged
    for entry in result["trace_log"]:
        assert "latency_ms" in entry


@pytest.mark.asyncio
async def test_trace_no_duplicate_hitl_events():
    """HITL trace entry appears exactly once after resume, not duplicated."""
    tracker = FakeTracker()
    graph = _build(tracker, exceptions_result=SAMPLE_EXCEPTIONS)
    run_id = _unique_run_id()
    await graph.ainvoke(OrchestratorState(run_id=run_id), _config(run_id))
    result = await graph.ainvoke(
        Command(resume={"decision": "approved"}), _config(run_id)
    )
    hitl_entries = [e for e in result["trace_log"] if e["node"] == "hitl_gate"]
    assert len(hitl_entries) == 1
