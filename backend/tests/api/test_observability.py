"""
Focused Offline Test Suite for Developer 1 Observability Feature

Tests cover:
- Initial empty metrics
- Unique run counting (start registers run, HITL pause marks pending, resume updates same run)
- HITL pause/resume without double counting total_runs
- Approved, rejected, and error counts in metrics
- Audit events persisted to AuditTrailRecord (RUN_STARTED, HITL_PENDING, RUN_COMPLETED, RUN_ERROR, HITL_DECISION)
- Idempotent audit event persistence
- Persistence failure rollback and session close
- List runs endpoint (/api/v1/observability/runs)
- Run trace detail endpoint (/api/v1/observability/runs/{run_id}) with real MCP/Agent/RAG/HITL trace decomposition
- Unknown run returns 404
- Deterministic offline execution with zero network / Gemini calls
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.agents.exception_analysis import ExceptionAnalysisAgent
from app.agents.financial_review import FinancialReviewAgent
from app.database.database import Base, get_db
from app.database.models import AuditTrailRecord, FinancialRecord
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator
from app.financial_engine.reconciliation import ReconciliationEngine
from app.main import app
from app.mcp.tools import FinancialMCPTools
from app.observability.metrics import MetricsCollector
from app.observability.tracing import format_run_trace
from app.orchestrator.graph import build_financial_close_graph
from app.services.workflow_service import (
    ObservabilityStorageError,
    RunConflictError,
    WorkflowService,
    _build_production_deps,
    get_workflow_service,
)


# ---------------------------------------------------------------------------
# Offline Socket Guard
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def block_external_sockets(monkeypatch):
    """Ensure tests are strictly offline by intercepting external socket connections."""
    original_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        if str(host) in ("127.0.0.1", "localhost", "::1", "testserver"):
            return original_connect(self, address)
        raise RuntimeError(f"External network call blocked during offline test: {address}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


# ---------------------------------------------------------------------------
# Test Fixtures (Isolated In-Memory SQLite, Deterministic Fakes)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session_factory():
    """Isolated SQLite in-memory database with StaticPool."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakePolicyRetriever:
    """Deterministic local policy retriever for fast offline testing."""

    async def retrieve_policy_context(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "chunk_id": "chunk_001",
                "content": "All cash GL accounts must be reconciled against bank statements.",
                "metadata": {"policy_id": "POL-001", "category": "BANK_RECONCILIATION"},
                "distance": 0.05,
                "citation": "[POL-001] Section: Bank Reconciliation",
            }
        ]


@pytest.fixture()
def fake_agents():
    """Deterministic offline fakes for Agent 1 and Agent 2 matching model schemas."""
    async def fake_model_1(system_instruction: str, user_content: str) -> str:
        data = json.loads(user_content.split("\n", 1)[1].rsplit("\n", 1)[0])
        exceptions = data.get("exceptions", [])
        findings = []
        for exc in exceptions:
            findings.append({
                "exception_index": exc.get("exception_index", 0),
                "classification": "TIMING_DIFFERENCE",
                "financial_context": f"Timing variance for {exc.get('id', 'exception')}",
            })
        return json.dumps({
            "summary_assessment": f"Reviewed {len(exceptions)} exception(s). Timing variances noted.",
            "findings": findings,
        })

    async def fake_model_2(system_instruction: str, user_content: str) -> str:
        data = json.loads(user_content.split("\n", 1)[1].rsplit("\n", 1)[0])
        evidence = data.get("rag_evidence", [])
        evidence_indices = [0] if evidence else []
        return json.dumps({
            "analysis": "Identified timing mismatch in bank feed.",
            "root_cause": "Delayed settlement from clearing house.",
            "recommendation": "Post accrual adjustment voucher.",
            "evidence_indices": evidence_indices,
        })

    agent_1 = FinancialReviewAgent(model_callable=fake_model_1)
    agent_2 = ExceptionAnalysisAgent(model_callable=fake_model_2)
    return agent_1, agent_2


@pytest.fixture()
def test_workflow_service(db_session_factory, fake_agents):
    """Create a fresh WorkflowService instance with injected in-memory metrics and DB."""
    agent_1, agent_2 = fake_agents
    metrics = MetricsCollector()
    service = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=FinancialMCPTools(session_factory=db_session_factory),
        reconciliation_engine=ReconciliationEngine(tolerance=0.01),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=agent_1,
        policy_retriever=FakePolicyRetriever(),
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
        metrics_collector=metrics,
    )
    return service


@pytest.fixture()
def test_client(test_workflow_service, db_session_factory):
    """FastAPI TestClient with overridden get_workflow_service and get_db."""
    app.state.workflow_service = test_workflow_service
    app.dependency_overrides[get_workflow_service] = lambda: test_workflow_service

    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_initial_empty_metrics(test_client):
    """Verify that metrics start at zero for an empty service."""
    response = test_client.get("/api/v1/observability/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 0
    assert data["avg_latency_ms"] == 0.0
    assert data["total_token_usage"] == 0
    assert data["error_count"] == 0
    assert data["hitl_approvals_count"] == 0


def test_unique_run_counting_and_clean_close(test_client, db_session_factory):
    """Verify clean run records 1 run, 0 errors, 0 approvals, and persists audit events."""
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_1", source="GL", account_code="1010", amount=100.0, description="Dep", is_reconciled=False, transaction_date=now))
    db.add(FinancialRecord(id="bk_1", source="BANK", account_code="1010", amount=100.0, description="Dep", is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    run_payload = {
        "workflow_type": "reconciliation",
        "account_code": "1010",
        "limit": 10,
        "period": "2026-Q1",
        "run_id": "run_clean_001",
    }
    run_resp = test_client.post("/api/v1/reconciliation/run", json=run_payload)
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "clean_close"

    # Check metrics
    metrics_resp = test_client.get("/api/v1/observability/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["total_runs"] == 1
    assert metrics["avg_latency_ms"] > 0
    assert metrics["error_count"] == 0
    assert metrics["hitl_approvals_count"] == 0

    # Verify audit trail records in DB
    db = db_session_factory()
    audit_records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == "run_clean_001").all()
    event_types = {r.event_type for r in audit_records}
    assert "RUN_STARTED" in event_types
    assert "RUN_COMPLETED" in event_types
    db.close()


def test_hitl_pause_and_resume_without_double_counting(test_client, db_session_factory):
    """Verify HITL pause and resume updates the run without double counting total_runs."""
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_unmatched_1", source="GL", account_code="2020", amount=500.0, description="Missing bank item", is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    run_payload = {
        "workflow_type": "reconciliation",
        "account_code": "2020",
        "limit": 10,
        "period": "2026-Q1",
        "run_id": "run_hitl_001",
    }
    run_resp = test_client.post("/api/v1/reconciliation/run", json=run_payload)
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "hitl_pending"

    # Metrics during HITL pause: total_runs should be 1
    m1 = test_client.get("/api/v1/observability/metrics").json()
    assert m1["total_runs"] == 1
    assert m1["hitl_approvals_count"] == 0

    # Verify audit records after pause
    db = db_session_factory()
    pause_records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == "run_hitl_001").all()
    pause_event_types = {r.event_type for r in pause_records}
    assert "RUN_STARTED" in pause_event_types
    assert "HITL_PENDING" in pause_event_types
    db.close()

    # Resume with approval
    approval_resp = test_client.post(
        "/api/v1/approvals/run_hitl_001/decision",
        json={"decision": "approved", "reviewer": "Lead Accountant", "comments": "Approved timing difference"},
    )
    assert approval_resp.status_code == 200
    assert approval_resp.json()["status"] == "approved"

    # Metrics after approval: total_runs must STILL be 1 (no double counting), approvals count is 1
    m2 = test_client.get("/api/v1/observability/metrics").json()
    assert m2["total_runs"] == 1
    assert m2["hitl_approvals_count"] == 1
    assert m2["error_count"] == 0

    # Verify audit records after approval
    db = db_session_factory()
    resumed_records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == "run_hitl_001").all()
    all_events = [r.event_type for r in resumed_records]
    assert "RUN_STARTED" in all_events
    assert "HITL_PENDING" in all_events
    assert "HITL_DECISION" in all_events
    assert "RUN_COMPLETED" in all_events
    assert all_events.count("RUN_STARTED") == 1
    db.close()


def test_rejected_decision_counting(test_client, db_session_factory):
    """Verify rejected HITL decision is counted correctly and not counted as approval."""
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_rej_1", source="GL", account_code="3030", amount=999.0, is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    run_payload = {
        "workflow_type": "reconciliation",
        "account_code": "3030",
        "period": "2026-Q1",
        "run_id": "run_reject_001",
    }
    run_resp = test_client.post("/api/v1/reconciliation/run", json=run_payload)
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "hitl_pending"

    # Reject
    rej_resp = test_client.post(
        "/api/v1/approvals/run_reject_001/decision",
        json={"decision": "rejected", "reviewer": "Audit Reviewer", "comments": "Missing supporting docs"},
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "rejected"

    m = test_client.get("/api/v1/observability/metrics").json()
    assert m["total_runs"] == 1
    assert m["hitl_approvals_count"] == 0
    assert m["error_count"] == 0


def test_get_run_trace_unknown_404(test_client):
    """Verify unknown run returns 404."""
    resp = test_client.get("/api/v1/observability/runs/nonexistent_run_999")
    assert resp.status_code == 404


def test_list_runs_endpoint(test_client, db_session_factory):
    """Verify /api/v1/observability/runs lists active and completed runs."""
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_list_1", source="GL", account_code="4040", amount=50.0, is_reconciled=False, transaction_date=now))
    db.add(FinancialRecord(id="bk_list_1", source="BANK", account_code="4040", amount=50.0, is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    test_client.post("/api/v1/reconciliation/run", json={
        "workflow_type": "reconciliation",
        "account_code": "4040",
        "period": "2026-Q1",
        "run_id": "run_list_001",
    })

    runs_resp = test_client.get("/api/v1/observability/runs")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()
    assert isinstance(runs, list)
    assert len(runs) >= 1
    found = next((r for r in runs if r["run_id"] == "run_list_001"), None)
    assert found is not None
    assert found["workflow_type"] == "reconciliation"
    assert found["status"] == "clean_close"
    assert "created_at" in found


def test_get_run_trace_detail_decomposition(test_client, db_session_factory):
    """Verify /api/v1/observability/runs/{run_id} returns detailed trace components."""
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_trace_1", source="GL", account_code="5050", amount=123.45, description="Trace Test", is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    run_resp = test_client.post("/api/v1/reconciliation/run", json={
        "workflow_type": "reconciliation",
        "account_code": "5050",
        "period": "2026-Q1",
        "run_id": "run_trace_decomp_001",
    })
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "hitl_pending"

    # Resume to complete
    approval_resp = test_client.post(
        "/api/v1/approvals/run_trace_decomp_001/decision",
        json={"decision": "approved", "reviewer": "Auditor", "comments": "Decomp check"},
    )
    assert approval_resp.status_code == 200
    assert approval_resp.json()["status"] == "approved"

    detail_resp = test_client.get("/api/v1/observability/runs/run_trace_decomp_001")
    assert detail_resp.status_code == 200
    trace = detail_resp.json()
    assert trace["run_id"] == "run_trace_decomp_001"
    assert trace["status"] == "approved"
    assert trace["workflow_type"] == "reconciliation"
    assert "total_latency_ms" in trace
    assert trace["total_latency_ms"] > 0
    assert "agent_executions" in trace
    assert len(trace["agent_executions"]) >= 2  # Agent 1 and Agent 2
    assert "mcp_calls" in trace
    assert len(trace["mcp_calls"]) >= 1  # fetch_data
    assert "rag_retrievals" in trace
    assert len(trace["rag_retrievals"]) >= 1  # retrieve_policy_evidence
    assert trace["human_decision"] is not None
    assert trace["human_decision"]["decision"] == "approved"
    assert "trace_log" in trace


def test_persistence_failure_rollback_and_session_close(test_workflow_service):
    """Verify that a database persistence error triggers rollback, close, and re-raises ObservabilityStorageError."""
    class FailingSession:
        def __init__(self):
            self.closed = False
            self.rolled_back = False

        def get(self, *args, **kwargs):
            return None

        def add(self, *args, **kwargs):
            pass

        def commit(self):
            raise RuntimeError("Disk I/O error during commit")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    failing_sess = FailingSession()
    test_workflow_service.session_factory = lambda: failing_sess

    with pytest.raises(ObservabilityStorageError, match="Observability storage unavailable") as exc_info:
        test_workflow_service._persist_audit_event(
            record_id="rec_err_1",
            run_id="run_fail_001",
            event_type="RUN_STARTED",
            details={"test": "data"},
        )

    assert failing_sess.rolled_back is True
    assert failing_sess.closed is True
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "Disk I/O error during commit" in str(exc_info.value.__cause__)


def test_error_count_in_metrics_on_workflow_failure(test_client, test_workflow_service, db_session_factory):
    """Verify that a failing workflow increments error_count and records RUN_ERROR."""
    # Force run_validation to fail
    async def failing_validation(*args, **kwargs):
        raise ValueError("Simulated engine failure during reconciliation math")

    test_workflow_service.deps.run_validation = failing_validation

    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_err_1", source="GL", account_code="9999", amount=10.0, is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    resp = test_client.post("/api/v1/reconciliation/run", json={
        "workflow_type": "reconciliation",
        "account_code": "9999",
        "period": "2026-Q1",
        "run_id": "run_error_test_001",
    })
    # Node failures inside graph produce error status in response or 500
    if resp.status_code == 200:
        assert resp.json()["status"] == "error"
    else:
        assert resp.status_code in (400, 500)

    # Check metrics
    m = test_client.get("/api/v1/observability/metrics").json()
    assert m["total_runs"] == 1
    assert m["error_count"] == 1


def test_audit_persistence_immutability(test_workflow_service, db_session_factory):
    """Verify that persisting an audit record with an existing ID does NOT overwrite existing records and rejects conflicting payloads."""
    test_workflow_service._persist_audit_event(
        record_id="idem_rec_1",
        run_id="run_idem_001",
        event_type="RUN_STARTED",
        details={"status": "initial"},
    )
    # Identical write with same ID and same payload must succeed idempotently
    test_workflow_service._persist_audit_event(
        record_id="idem_rec_1",
        run_id="run_idem_001",
        event_type="RUN_STARTED",
        details={"status": "initial"},
    )
    # Conflicting write with same ID but different payload must raise RunConflictError
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event(
            record_id="idem_rec_1",
            run_id="run_idem_001",
            event_type="RUN_STARTED",
            details={"status": "attempted_overwrite"},
        )

    db = db_session_factory()
    records = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "idem_rec_1").all()
    assert len(records) == 1
    assert records[0].details == {"status": "initial"}
    db.close()

    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event(
            record_id="idem_rec_1",
            run_id="different_run",
            event_type="RUN_ERROR",
            details={"status": "error"},
        )


def test_historical_duplicate_after_restart_raises_conflict(test_client, db_session_factory, fake_agents):
    """Finding 1 & 6: Historical duplicate after restart raises conflict and never overwrites previous audit records."""
    agent_1, agent_2 = fake_agents
    # Create an existing historical record in DB
    db = db_session_factory()
    hist_record = AuditTrailRecord(
        id="run_hist_001_RUN_STARTED",
        run_id="run_hist_001",
        event_type="RUN_STARTED",
        details={"status": "running", "workflow_type": "reconciliation", "period": "2026-Q1"},
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(hist_record)
    db.commit()
    db.close()

    # Fresh WorkflowService with empty in-memory state
    fresh_service = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=FinancialMCPTools(session_factory=db_session_factory),
        reconciliation_engine=ReconciliationEngine(tolerance=0.01),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=agent_1,
        policy_retriever=FakePolicyRetriever(),
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
        metrics_collector=MetricsCollector(),
    )

    # Calling start_workflow directly with the duplicate run_id must raise RunConflictError
    with pytest.raises(RunConflictError) as conflict:
        asyncio.run(
            fresh_service.start_workflow(
                workflow_type="reconciliation",
                period="2026-Q1",
                input_params={"account_code": "1010"},
                run_id="run_hist_001",
            )
        )
    assert isinstance(conflict.value.__cause__, IntegrityError)

    # Calling via API with fresh_service on app.state returns 409
    app.state.workflow_service = fresh_service
    app.dependency_overrides[get_workflow_service] = lambda: fresh_service
    resp = test_client.post(
        "/api/v1/reconciliation/run",
        json={"workflow_type": "reconciliation", "account_code": "1010", "run_id": "run_hist_001"},
    )
    assert resp.status_code == 409

    # Verify existing DB audit record was not modified
    db = db_session_factory()
    rec = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "run_hist_001_RUN_STARTED").first()
    assert rec is not None
    assert rec.details == {"status": "running", "workflow_type": "reconciliation", "period": "2026-Q1"}
    db.close()


@pytest.mark.asyncio
async def test_concurrent_hitl_idempotency(test_workflow_service, db_session_factory):
    """Finding 5 & 6: Concurrent HITL resume on the same run allows only one resolution."""
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_hitl_conc", source="GL", account_code="7777", amount=500.0, is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    run_id = "run_hitl_conc_001"
    res = await test_workflow_service.start_workflow(
        workflow_type="reconciliation",
        period="2026-Q1",
        input_params={"account_code": "7777"},
        run_id=run_id,
    )
    assert res["status"] == "hitl_pending"

    # Attempt two concurrent resume_decision calls
    results = await asyncio.gather(
        test_workflow_service.resume_decision(run_id, decision="approved", reviewer="Reviewer A"),
        test_workflow_service.resume_decision(run_id, decision="approved", reviewer="Reviewer B"),
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, dict)]
    conflicts = [r for r in results if isinstance(r, RunConflictError)]

    assert len(successes) == 1
    assert len(conflicts) == 1
    assert test_workflow_service.metrics_collector.hitl_approvals_count == 1
    assert test_workflow_service.metrics_collector.total_runs == 1


@pytest.mark.asyncio
async def test_full_trace_reconstruction_by_fresh_service(db_session_factory, fake_agents):
    """Finding 2 & 6: Fresh WorkflowService after restart reconstructs identical run trace details."""
    agent_1, agent_2 = fake_agents
    db = db_session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(FinancialRecord(id="gl_recon_fresh", source="GL", account_code="8888", amount=777.0, is_reconciled=False, transaction_date=now))
    db.commit()
    db.close()

    service_1 = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=FinancialMCPTools(session_factory=db_session_factory),
        reconciliation_engine=ReconciliationEngine(tolerance=0.01),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=agent_1,
        policy_retriever=FakePolicyRetriever(),
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
        metrics_collector=MetricsCollector(),
    )

    run_id = "run_reconstruct_001"
    res1 = await service_1.start_workflow(
        workflow_type="reconciliation",
        period="2026-Q1",
        input_params={"account_code": "8888", "limit": 10},
        run_id=run_id,
    )
    assert res1["status"] == "hitl_pending"

    resumed = await service_1.resume_decision(
        run_id=run_id,
        decision="approved",
        reviewer="Senior Accountant",
        comments="Fully resolved timing difference",
    )
    assert resumed["status"] == "approved"

    trace_original = await service_1.get_run_trace(run_id)
    assert trace_original is not None

    # Simulate restart: fresh service with empty memory
    service_fresh = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=FinancialMCPTools(session_factory=db_session_factory),
        reconciliation_engine=ReconciliationEngine(tolerance=0.01),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=agent_1,
        policy_retriever=FakePolicyRetriever(),
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
        metrics_collector=MetricsCollector(),
    )

    trace_reconstructed = await service_fresh.get_run_trace(run_id)
    assert trace_reconstructed is not None

    # Compare all fields for exact equivalence
    assert trace_reconstructed["run_id"] == trace_original["run_id"]
    assert trace_reconstructed["status"] == trace_original["status"] == "approved"
    assert trace_reconstructed["workflow_type"] == trace_original["workflow_type"]
    assert trace_reconstructed["period"] == trace_original["period"]
    assert trace_reconstructed["total_latency_ms"] == trace_original["total_latency_ms"]
    assert trace_reconstructed["agent_executions"] == trace_original["agent_executions"]
    assert trace_reconstructed["mcp_calls"] == trace_original["mcp_calls"]
    assert trace_reconstructed["rag_retrievals"] == trace_original["rag_retrievals"]
    assert trace_reconstructed["human_decision"] == trace_original["human_decision"]
    assert trace_reconstructed["errors"] == trace_original["errors"]
    assert trace_reconstructed["trace_log"] == trace_original["trace_log"]


def test_db_read_failure_raises_500(test_client, test_workflow_service):
    """Finding 4 & 6: DB read failure in list_runs and get_run_trace raises ObservabilityStorageError mapping to 500 with generic message."""
    class FailingQuerySession:
        def __init__(self):
            self.closed = False

        def query(self, *args, **kwargs):
            raise RuntimeError("Database connection timed out during query")

        def close(self):
            self.closed = True

    failing_sess = FailingQuerySession()
    test_workflow_service.session_factory = lambda: failing_sess

    # list_runs should return 500 (not swallow error, generic message)
    resp_list = test_client.get("/api/v1/observability/runs")
    assert resp_list.status_code == 500
    assert resp_list.json()["detail"] == "Observability storage unavailable"
    assert "Database connection timed out" not in resp_list.text
    assert failing_sess.closed is True

    # get_run_trace should return 500 (not 404!)
    failing_sess_trace = FailingQuerySession()
    test_workflow_service.session_factory = lambda: failing_sess_trace
    resp_trace = test_client.get("/api/v1/observability/runs/nonexistent_run_error_test")
    assert resp_trace.status_code == 500
    assert resp_trace.json()["detail"] == "Observability storage unavailable"
    assert "Database connection timed out" not in resp_trace.text
    assert failing_sess_trace.closed is True



@pytest.mark.asyncio
async def test_truthful_traces_for_failed_mcp_and_non_mcp_workflows(test_workflow_service):
    """Finding 3 & 6: Truthful traces: non-MCP workflows emit no MCP tools; failed MCP reflects reality."""
    # A. Non-MCP accrual workflow
    await test_workflow_service.start_workflow(
        workflow_type="accrual",
        period="2026-Q1",
        input_params={
            "accrual_entries": [{"vendor": "V1", "amount": 100.0}],
            "historical_baseline": {"V1": {"amount": 100.0}},
        },
        run_id="run_accrual_nomcp_001",
    )
    accrual_trace = await test_workflow_service.get_run_trace("run_accrual_nomcp_001")
    assert accrual_trace is not None
    # No fabricated MCP tools!
    assert accrual_trace["mcp_calls"] == []

    # B. Non-MCP depreciation workflow
    await test_workflow_service.start_workflow(
        workflow_type="depreciation",
        period="2026-Q1",
        input_params={
            "asset_records": [{"asset_id": "A1", "cost": 1000.0, "useful_life_months": 12}],
            "period_posted_depreciation": {"A1": {"amount": 83.33}},
        },
        run_id="run_deprec_nomcp_001",
    )
    deprec_trace = await test_workflow_service.get_run_trace("run_deprec_nomcp_001")
    assert deprec_trace is not None
    assert deprec_trace["mcp_calls"] == []

    # C. Failed MCP tool call during reconciliation
    async def failing_fetch_data(workflow_type, input_params):
        raise ConnectionError("GL database connection lost")

    test_workflow_service.deps.fetch_data = failing_fetch_data
    # Run reconciliation with failing MCP
    try:
        await test_workflow_service.start_workflow(
            workflow_type="reconciliation",
            period="2026-Q1",
            input_params={"account_code": "1010"},
            run_id="run_mcp_fail_001",
        )
    except Exception:
        pass

    failed_trace = await test_workflow_service.get_run_trace("run_mcp_fail_001")
    assert failed_trace is not None
    assert failed_trace["status"] == "error"


@pytest.mark.asyncio
async def test_zero_latency_without_fabrication():
    """Finding 3, 5 & 6: Zero latency is preserved as 0.0 without injecting a 0.01 floor."""
    run_data = {
        "run_id": "run_zero_lat_001",
        "workflow_type": "reconciliation",
        "period": "2026-Q1",
        "status": "completed",
        "total_latency_ms": 0.0,
        "trace_log": [
            {"node": "fetch_data", "status": "ok", "latency_ms": 0.0},
            {"node": "agent_1_review", "status": "ok", "latency_ms": 0.0},
        ],
        "financial_data": {},
        "errors": [],
    }
    trace = format_run_trace(run_data)
    assert trace["total_latency_ms"] == 0.0

    # Explicit total_latency_ms is None and trace_log has 0.0
    run_data_no_explicit = {
        "run_id": "run_zero_lat_002",
        "workflow_type": "reconciliation",
        "period": "2026-Q1",
        "status": "completed",
        "trace_log": [
            {"node": "fetch_data", "status": "ok", "latency_ms": 0.0},
        ],
        "financial_data": {},
        "errors": [],
    }
    trace_no_explicit = format_run_trace(run_data_no_explicit)
    assert trace_no_explicit["total_latency_ms"] == 0.0

    # MetricsCollector avg_latency_ms with 0.0 latency
    mc = MetricsCollector()
    await mc.register_run("r1")
    await mc.finalize_run("r1", status="completed", latency_ms=0.0, tokens=0, has_error=False)
    summary = await mc.get_summary()
    assert summary["avg_latency_ms"] == 0.0
    assert summary["total_runs"] == 1
    assert mc.finalized_runs_count == 1


# ---------------------------------------------------------------------------
# Regression tests for the final concurrency and durability contracts
# ---------------------------------------------------------------------------


def make_service(factory, fake_agents, *, mcp_tools=None) -> WorkflowService:
    agent_1, agent_2 = fake_agents
    return WorkflowService(
        session_factory=factory,
        mcp_tools=mcp_tools or FinancialMCPTools(session_factory=factory),
        reconciliation_engine=ReconciliationEngine(tolerance=0.01),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=agent_1,
        policy_retriever=FakePolicyRetriever(),
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
        metrics_collector=MetricsCollector(),
    )


@pytest.mark.asyncio
async def test_metrics_lock_contention_yields_to_event_loop_and_counts_once():
    collector = MetricsCollector()
    lock_held = asyncio.Event()
    release_lock = asyncio.Event()
    waiter_started = asyncio.Event()
    event_loop_progressed = asyncio.Event()

    async def holder():
        async with collector._lock:
            lock_held.set()
            await release_lock.wait()

    async def waiter():
        waiter_started.set()
        await collector.register_run("contended")

    holder_task = asyncio.create_task(holder())
    await lock_held.wait()
    waiter_task = asyncio.create_task(waiter())
    await waiter_started.wait()
    asyncio.get_running_loop().call_soon(event_loop_progressed.set)
    await event_loop_progressed.wait()
    assert not waiter_task.done()
    release_lock.set()
    await asyncio.gather(holder_task, waiter_task)

    await asyncio.gather(
        collector.finalize_run("contended", "approved", latency_ms=7.5),
        collector.finalize_run("contended", "approved", latency_ms=100.0),
    )
    assert await collector.get_summary() == {
        "total_runs": 1,
        "avg_latency_ms": 7.5,
        "total_token_usage": 0,
        "error_count": 0,
        "hitl_approvals_count": 1,
    }


@pytest.mark.asyncio
async def test_two_services_simultaneously_reserve_one_file_sqlite_run(tmp_path, fake_agents):
    reservation_barrier = threading.Barrier(2)

    class BarrierSession(Session):
        def commit(self):
            if any(
                isinstance(record, AuditTrailRecord) and record.event_type == "RUN_STARTED"
                for record in self.new
            ):
                reservation_barrier.wait()
            return super().commit()

    database_path = tmp_path / "reservation.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=BarrierSession, expire_on_commit=False)
    service_a = make_service(factory, fake_agents)
    service_b = make_service(factory, fake_agents)

    results = await asyncio.gather(
        service_a.start_workflow("reconciliation", input_params={"account_code": "A"}, run_id="shared"),
        service_b.start_workflow("reconciliation", input_params={"account_code": "B"}, run_id="shared"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, RunConflictError) for result in results) == 1
    with factory() as db:
        records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == "shared").all()
        assert sum(record.event_type == "RUN_STARTED" for record in records) == 1
        assert all((record.details or {}).get("input_params", {}).get("account_code") != "B" for record in records) or all(
            (record.details or {}).get("input_params", {}).get("account_code") != "A" for record in records
        )
    engine.dispose()


@pytest.mark.asyncio
async def test_non_integrity_reservation_failure_rolls_back_closes_and_stops_workflow(test_workflow_service):
    class FailingSession:
        rolled_back = False
        closed = False

        def add(self, record):
            self.record = record

        def commit(self):
            raise OSError("disk unavailable")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    session = FailingSession()
    test_workflow_service.session_factory = lambda: session
    with pytest.raises(ObservabilityStorageError):
        await test_workflow_service.start_workflow(
            "reconciliation", input_params={"account_code": "never-runs"}, run_id="storage-failure"
        )
    assert session.rolled_back and session.closed
    assert "storage-failure" not in test_workflow_service._runs
    assert (await test_workflow_service.metrics_collector.get_summary())["total_runs"] == 0


@pytest.mark.asyncio
async def test_interleaved_mcp_calls_are_isolated_and_preserve_partial_failure(db_session_factory, fake_agents):
    gl_barrier = asyncio.Barrier(2)
    bank_barrier = asyncio.Barrier(2)

    class InterleavedMCP:
        async def query_gl_transactions(self, account_code: str, limit: int = 50):
            await gl_barrier.wait()
            return [{"id": f"gl-{account_code}", "account_code": account_code, "amount": float(limit)}]

        async def query_bank_transactions(self, account_code: str, limit: int = 50):
            await bank_barrier.wait()
            if account_code == "FAIL":
                raise ConnectionError("FAIL bank unavailable")
            return [{"id": f"bank-{account_code}", "account_code": account_code, "amount": float(limit)}]

    service = make_service(db_session_factory, fake_agents, mcp_tools=InterleavedMCP())
    failed, succeeded = await asyncio.gather(
        service.start_workflow("reconciliation", input_params={"account_code": "FAIL", "limit": 11}, run_id="mcp-fail"),
        service.start_workflow("reconciliation", input_params={"account_code": "OK", "limit": 22}, run_id="mcp-ok"),
    )
    assert failed["status"] == "error"
    fail_calls = (await service.get_run_trace("mcp-fail"))["mcp_calls"]
    ok_calls = (await service.get_run_trace("mcp-ok"))["mcp_calls"]
    assert [(call["tool"], call["status"]) for call in fail_calls] == [
        ("query_gl_transactions", "success"),
        ("query_bank_transactions", "error"),
    ]
    assert [(call["tool"], call["status"]) for call in ok_calls] == [
        ("query_gl_transactions", "success"),
        ("query_bank_transactions", "success"),
    ]
    assert {call["parameters"]["account_code"] for call in fail_calls} == {"FAIL"}
    assert {call["parameters"]["limit"] for call in fail_calls} == {11}
    assert {call["parameters"]["account_code"] for call in ok_calls} == {"OK"}
    assert {call["parameters"]["limit"] for call in ok_calls} == {22}


@pytest.mark.parametrize(
    ("event_type", "phase"),
    [
        ("RUN_STARTED", "start"),
        ("HITL_PENDING", "start_pending"),
        ("RUN_COMPLETED", "start_complete"),
        ("RUN_ERROR", "start_error"),
        ("HITL_DECISION", "resume"),
        ("RUN_COMPLETED", "resume"),
    ],
)
def test_every_audit_failure_returns_5xx_through_real_api(
    event_type, phase, test_client, test_workflow_service, db_session_factory, monkeypatch
):
    run_id = f"audit-{event_type.lower()}-{phase}"
    if "pending" in phase or phase == "resume":
        with db_session_factory() as db:
            db.add(
                FinancialRecord(
                    id=f"gl-{run_id}", source="GL", account_code=run_id,
                    amount=10.0, is_reconciled=False,
                    transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            db.commit()
    if phase == "resume":
        start = test_client.post(
            "/api/v1/reconciliation/run",
            json={"workflow_type": "reconciliation", "account_code": run_id, "run_id": run_id},
        )
        assert start.status_code == 200 and start.json()["status"] == "hitl_pending"

    seen = []
    if event_type == "RUN_STARTED":
        def fail_reservation(*args, **kwargs):
            raise ObservabilityStorageError("RUN_STARTED storage failed")
        monkeypatch.setattr(test_workflow_service, "_reserve_run_id", fail_reservation)
    else:
        original = test_workflow_service._persist_audit_event

        def fail_selected(record_id, persisted_run_id, persisted_event_type, details):
            seen.append(persisted_event_type)
            if persisted_event_type == event_type:
                raise ObservabilityStorageError(f"{event_type} storage failed")
            return original(record_id, persisted_run_id, persisted_event_type, details)

        monkeypatch.setattr(test_workflow_service, "_persist_audit_event", fail_selected)

    if phase == "start_error":
        async def fail_fetch(*args, **kwargs):
            raise ConnectionError("real execution failed")
        test_workflow_service.deps.fetch_data = fail_fetch

    if phase == "resume":
        response = test_client.post(
            f"/api/v1/approvals/{run_id}/decision",
            json={"decision": "approved", "reviewer": "tester", "comments": "offline"},
        )
    else:
        account = run_id if phase == "start_pending" else f"clean-{run_id}"
        response = test_client.post(
            "/api/v1/reconciliation/run",
            json={"workflow_type": "reconciliation", "account_code": account, "run_id": run_id},
        )
    assert response.status_code == 500
    if event_type != "RUN_STARTED":
        assert event_type in seen
    metrics = test_client.get("/api/v1/observability/metrics").json()
    if event_type == "RUN_ERROR":
        assert metrics["error_count"] == 0
    if event_type == "RUN_COMPLETED":
        assert metrics["hitl_approvals_count"] == 0


@pytest.mark.asyncio
async def test_active_and_restarted_trace_are_exactly_equal(db_session_factory, fake_agents):
    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-parity", source="GL", account_code="PARITY", amount=25.0,
                is_reconciled=False, transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()
    active_service = make_service(db_session_factory, fake_agents)
    pending = await active_service.start_workflow(
        "reconciliation", period="2026-Q1", input_params={"account_code": "PARITY"}, run_id="parity"
    )
    await active_service.resume_decision("parity", "approved", "reviewer", "verified")
    active_trace = await active_service.get_run_trace("parity")
    restarted_trace = await make_service(db_session_factory, fake_agents).get_run_trace("parity")
    assert active_trace == restarted_trace
    assert active_trace["created_at"] == pending["created_at"]


# ---------------------------------------------------------------------------
# Defect 1 Regression Tests: Conflicting audit idempotency
# ---------------------------------------------------------------------------


def test_audit_identical_and_conflicting_retries(test_workflow_service, db_session_factory):
    """Test identical retries succeed idempotently; conflicting payload raises RunConflictError."""
    payload_a = {"status": "hitl_pending", "decision": "pending", "meta": {"attempts": 1}}
    payload_conflict = {"status": "hitl_pending", "decision": "rejected", "meta": {"attempts": 1}}

    test_workflow_service._persist_audit_event(
        record_id="rec_idem_001",
        run_id="run_idem_001",
        event_type="HITL_PENDING",
        details=payload_a,
    )

    # Identical retry must succeed without error
    test_workflow_service._persist_audit_event(
        record_id="rec_idem_001",
        run_id="run_idem_001",
        event_type="HITL_PENDING",
        details=payload_a,
    )

    # Conflicting retry must raise RunConflictError
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event(
            record_id="rec_idem_001",
            run_id="run_idem_001",
            event_type="HITL_PENDING",
            details=payload_conflict,
        )

    # Stored record must remain unchanged
    with db_session_factory() as db:
        rec = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "rec_idem_001").first()
        assert rec is not None
        assert rec.details == payload_a


def test_audit_nested_json_ordering_idempotency(test_workflow_service, db_session_factory):
    """Test nested JSON ordering differences are canonically normalized and treated as identical."""
    details_ordered = {
        "metadata": {"tags": ["finance", "q1"], "priority": 1},
        "config": {"retries": 3, "timeout": 30.0},
        "action": "reconcile",
    }
    details_reordered = {
        "action": "reconcile",
        "config": {"timeout": 30.0, "retries": 3},
        "metadata": {"priority": 1, "tags": ["finance", "q1"]},
    }
    details_different = {
        "action": "reconcile",
        "config": {"timeout": 60.0, "retries": 3},
        "metadata": {"priority": 1, "tags": ["finance", "q1"]},
    }

    test_workflow_service._persist_audit_event(
        record_id="rec_json_order_001",
        run_id="run_order_001",
        event_type="HITL_PENDING",
        details=details_ordered,
    )

    # Reordered payload must be accepted as identical idempotent success
    test_workflow_service._persist_audit_event(
        record_id="rec_json_order_001",
        run_id="run_order_001",
        event_type="HITL_PENDING",
        details=details_reordered,
    )

    # Different nested value must raise RunConflictError
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event(
            record_id="rec_json_order_001",
            run_id="run_order_001",
            event_type="HITL_PENDING",
            details=details_different,
        )


@pytest.mark.asyncio
async def test_concurrent_conflicting_hitl_decisions(test_workflow_service, db_session_factory):
    """Test concurrent conflicting HITL decisions on the same run: exactly one succeeds, one raises RunConflictError."""
    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-hitl-conflict",
                source="GL",
                account_code="CONF-HITL",
                amount=300.0,
                is_reconciled=False,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

    run_id = "run_hitl_conflict_001"
    start_res = await test_workflow_service.start_workflow(
        workflow_type="reconciliation",
        period="2026-Q1",
        input_params={"account_code": "CONF-HITL"},
        run_id=run_id,
    )
    assert start_res["status"] == "hitl_pending"

    # Concurrently attempt approved vs rejected
    results = await asyncio.gather(
        test_workflow_service.resume_decision(run_id, decision="approved", reviewer="Auditor Alpha"),
        test_workflow_service.resume_decision(run_id, decision="rejected", reviewer="Auditor Beta"),
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, dict)]
    conflicts = [r for r in results if isinstance(r, RunConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1

    # Exactly one decision is recorded
    with db_session_factory() as db:
        decisions = (
            db.query(AuditTrailRecord)
            .filter(AuditTrailRecord.run_id == run_id, AuditTrailRecord.event_type == "HITL_DECISION")
            .all()
        )
        assert len(decisions) == 1
        assert decisions[0].details["decision"] in ("approved", "rejected")

    # Metrics count exactly 1 run, not double counted
    assert test_workflow_service.metrics_collector.total_runs == 1
    assert test_workflow_service.metrics_collector.finalized_runs_count == 1


# ---------------------------------------------------------------------------
# Defect 2 Regression Tests: Cancellation-safe start and resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_during_workflow_start(test_workflow_service, db_session_factory):
    """Test cancellation during start: handles CancelledError, persists terminal snapshot, finalizes metrics, re-raises."""
    reached_node = asyncio.Event()
    release_node = asyncio.Event()

    original_val = test_workflow_service.deps.run_validation

    async def hooked_validation(*args, **kwargs):
        reached_node.set()
        await release_node.wait()
        return await original_val(*args, **kwargs)

    test_workflow_service.deps.run_validation = hooked_validation

    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-cancel-start",
                source="GL",
                account_code="CANCEL-START",
                amount=100.0,
                is_reconciled=False,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

    run_id = "run_cancel_start_001"
    task = asyncio.create_task(
        test_workflow_service.start_workflow(
            workflow_type="reconciliation",
            period="2026-Q1",
            input_params={"account_code": "CANCEL-START"},
            run_id=run_id,
        )
    )

    await reached_node.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Assert honest cancelled terminal snapshot persisted to DB
    with db_session_factory() as db:
        records = (
            db.query(AuditTrailRecord)
            .filter(AuditTrailRecord.run_id == run_id)
            .order_by(AuditTrailRecord.created_at.asc())
            .all()
        )
        types = [r.event_type for r in records]
        assert "RUN_STARTED" in types
        assert "RUN_ERROR" in types
        assert types.count("RUN_ERROR") == 1
        terminal = next(r for r in records if r.event_type == "RUN_ERROR")
        assert terminal.details["status"] == "cancelled"
        assert any("cancelled" in str(err).lower() for err in terminal.details.get("errors", []))

    # Assert in-memory state updated
    cached = test_workflow_service._runs.get(run_id)
    assert cached is not None
    assert cached["status"] == "cancelled"

    # Assert metrics finalized exactly once and not stale
    summary = await test_workflow_service.metrics_collector.get_summary()
    assert summary["total_runs"] == 1
    assert summary["error_count"] == 1
    assert test_workflow_service.metrics_collector.finalized_runs_count == 1
    assert run_id not in test_workflow_service.metrics_collector._pending_runs


@pytest.mark.asyncio
async def test_cancellation_during_start_finalization(test_workflow_service, db_session_factory, monkeypatch):
    """Test cancellation during start finalization: clean single terminal snapshot without duplicates."""
    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-cancel-final",
                source="GL",
                account_code="CANCEL-FIN",
                amount=50.0,
                is_reconciled=False,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

    run_id = "run_cancel_start_fin_001"

    orig_persist = test_workflow_service._persist_audit_event

    def hooked_persist(record_id, p_run_id, event_type, details):
        if p_run_id == run_id and event_type in ("RUN_COMPLETED", "HITL_PENDING"):
            raise asyncio.CancelledError("Cancelled during finalization persistence")
        return orig_persist(record_id, p_run_id, event_type, details)

    monkeypatch.setattr(test_workflow_service, "_persist_audit_event", hooked_persist)

    with pytest.raises(asyncio.CancelledError):
        await test_workflow_service.start_workflow(
            workflow_type="reconciliation",
            period="2026-Q1",
            input_params={"account_code": "CANCEL-FIN"},
            run_id=run_id,
        )

    # Check metrics and single terminal record in DB
    summary = await test_workflow_service.metrics_collector.get_summary()
    assert summary["total_runs"] == 1
    assert summary["error_count"] == 1
    assert test_workflow_service.metrics_collector.finalized_runs_count == 1

    with db_session_factory() as db:
        records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == run_id).all()
        terminal_records = [r for r in records if r.event_type in ("RUN_COMPLETED", "RUN_ERROR")]
        assert len(terminal_records) == 1
        assert terminal_records[0].event_type == "RUN_ERROR"


@pytest.mark.asyncio
async def test_cancellation_during_workflow_resume(test_workflow_service, db_session_factory):
    """Test cancellation during resume: handles CancelledError, persists honest cancelled terminal snapshot, cleans pending metrics."""
    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-cancel-resume",
                source="GL",
                account_code="CANCEL-RES",
                amount=150.0,
                is_reconciled=False,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

    run_id = "run_cancel_resume_001"
    start_res = await test_workflow_service.start_workflow(
        workflow_type="reconciliation",
        period="2026-Q1",
        input_params={"account_code": "CANCEL-RES"},
        run_id=run_id,
    )
    assert start_res["status"] == "hitl_pending"
    assert run_id in test_workflow_service.metrics_collector._pending_runs

    async def hooked_ainvoke(cmd, config=None):
        raise asyncio.CancelledError("Cancelled inside resumed graph invoke")

    test_workflow_service.graph.ainvoke = hooked_ainvoke

    with pytest.raises(asyncio.CancelledError):
        await test_workflow_service.resume_decision(run_id, decision="approved", reviewer="Auditor")

    # Assert exactly one terminal RUN_ERROR recorded with cancelled status
    with db_session_factory() as db:
        records = (
            db.query(AuditTrailRecord)
            .filter(AuditTrailRecord.run_id == run_id)
            .order_by(AuditTrailRecord.created_at.asc())
            .all()
        )
        types = [r.event_type for r in records]
        assert types == ["RUN_STARTED", "HITL_PENDING", "HITL_DECISION", "RUN_ERROR"]
        terminal_records = [r for r in records if r.event_type in ("RUN_COMPLETED", "RUN_ERROR")]
        assert len(terminal_records) == 1
        err_rec = next(r for r in records if r.event_type == "RUN_ERROR")
        assert err_rec.details["status"] == "cancelled"

    # Assert metrics finalized, not in pending
    assert run_id not in test_workflow_service.metrics_collector._pending_runs
    summary = await test_workflow_service.metrics_collector.get_summary()
    assert summary["total_runs"] == 1
    assert summary["error_count"] == 1
    assert test_workflow_service.metrics_collector.finalized_runs_count == 1


@pytest.mark.asyncio
async def test_cancellation_during_resumed_finalization(test_workflow_service, db_session_factory, monkeypatch):
    """Test cancellation during resumed finalization completes cleanup once without duplicate events."""
    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-cancel-res-fin",
                source="GL",
                account_code="CANCEL-RES-FIN",
                amount=200.0,
                is_reconciled=False,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

    run_id = "run_cancel_res_fin_001"
    await test_workflow_service.start_workflow(
        workflow_type="reconciliation",
        period="2026-Q1",
        input_params={"account_code": "CANCEL-RES-FIN"},
        run_id=run_id,
    )

    orig_persist = test_workflow_service._persist_audit_event

    def hooked_persist(record_id, p_run_id, event_type, details):
        if p_run_id == run_id and event_type == "RUN_COMPLETED":
            raise asyncio.CancelledError("Cancelled before RUN_COMPLETED persists")
        return orig_persist(record_id, p_run_id, event_type, details)

    monkeypatch.setattr(test_workflow_service, "_persist_audit_event", hooked_persist)

    with pytest.raises(asyncio.CancelledError):
        await test_workflow_service.resume_decision(run_id, decision="approved", reviewer="Auditor")

    summary = await test_workflow_service.metrics_collector.get_summary()
    assert summary["total_runs"] == 1
    assert summary["error_count"] == 1

    with db_session_factory() as db:
        records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == run_id).all()
        terminal_records = [r for r in records if r.event_type in ("RUN_COMPLETED", "RUN_ERROR")]
        assert len(terminal_records) == 1
        assert terminal_records[0].event_type == "RUN_ERROR"


@pytest.mark.asyncio
async def test_cancellation_during_cleanup_shielded(test_workflow_service, db_session_factory):
    """Test that cancellation during cleanup cannot corrupt or interrupt cleanup."""
    with db_session_factory() as db:
        db.add(
            FinancialRecord(
                id="gl-cancel-clean",
                source="GL",
                account_code="CANCEL-CLEAN",
                amount=100.0,
                is_reconciled=False,
                transaction_date=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

    run_id = "run_cancel_clean_001"
    fetch_reached = asyncio.Event()
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def hooked_fetch(*args, **kwargs):
        fetch_reached.set()
        raise asyncio.CancelledError("Initial cancellation")

    test_workflow_service.deps.fetch_data = hooked_fetch

    orig_safe_cleanup = test_workflow_service._safe_record_cancellation

    async def hooked_cleanup(*args, **kwargs):
        cleanup_started.set()
        await cleanup_release.wait()
        return await orig_safe_cleanup(*args, **kwargs)

    test_workflow_service._safe_record_cancellation = hooked_cleanup

    task = asyncio.create_task(
        test_workflow_service.start_workflow(
            workflow_type="reconciliation",
            period="2026-Q1",
            input_params={"account_code": "CANCEL-CLEAN"},
            run_id=run_id,
        )
    )

    await fetch_reached.wait()

    # Wait until cleanup starts, then cancel the task again while cleanup is executing
    await cleanup_started.wait()
    task.cancel()
    task.cancel()
    cleanup_release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Cleanup finished cleanly
    with db_session_factory() as db:
        records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == run_id).all()
        types = [r.event_type for r in records]
        assert "RUN_ERROR" in types
        assert types.count("RUN_ERROR") == 1
        terminal_records = [r for r in records if r.event_type in ("RUN_COMPLETED", "RUN_ERROR")]
        assert len(terminal_records) == 1

    assert test_workflow_service.metrics_collector.finalized_runs_count == 1


# ---------------------------------------------------------------------------
# Defect 3 Regression Tests: Secure storage error responses
# ---------------------------------------------------------------------------


def test_secure_storage_error_sanitizes_direct_and_nested_exceptions(test_client, test_workflow_service, db_session_factory):
    """Test sensitive SQL, credentials, paths, schema names, and nested causes are never exposed."""
    sensitive_tokens = [
        "SELECT secret_key FROM private_credentials WHERE id=1",
        "postgres://superadmin:TopSecretPassword123@10.0.0.5:5432/finance_db",
        "C:\\ClosureIQ\\private\\production_ledger.db",
        "/etc/ssl/certs/private_finance_key.pem",
        "audit_trail_records_confidential_schema",
        "CustomInternalOperationalError",
        "SensitiveDatabaseConnectionTimeout",
    ]

    class SensitiveCustomError(RuntimeError):
        pass

    class HighlySensitiveSession:
        def __init__(self):
            self.closed = False

        def query(self, *args, **kwargs):
            nested_cause = SensitiveCustomError(
                f"Connection failed to {sensitive_tokens[1]} for query: {sensitive_tokens[0]}"
            )
            direct_error = RuntimeError(
                f"Path failure {sensitive_tokens[2]} with schema {sensitive_tokens[4]} "
                f"and cert {sensitive_tokens[3]}: {sensitive_tokens[5]}"
            )
            raise direct_error from nested_cause

        def close(self):
            self.closed = True

    # 1. Test /api/v1/observability/runs
    sess_runs = HighlySensitiveSession()
    test_workflow_service.session_factory = lambda: sess_runs
    resp_runs = test_client.get("/api/v1/observability/runs")
    assert resp_runs.status_code == 500
    assert resp_runs.json() == {"detail": "Observability storage unavailable"}
    assert sess_runs.closed is True
    for token in sensitive_tokens:
        assert token not in resp_runs.text

    # 2. Test /api/v1/observability/runs/{run_id}
    sess_trace = HighlySensitiveSession()
    test_workflow_service.session_factory = lambda: sess_trace
    resp_trace = test_client.get("/api/v1/observability/runs/run_secure_test_999")
    assert resp_trace.status_code == 500
    assert resp_trace.json() == {"detail": "Observability storage unavailable"}
    assert sess_trace.closed is True
    for token in sensitive_tokens:
        assert token not in resp_trace.text

    # 3. Test /api/v1/observability/metrics
    async def failing_metrics():
        nested_cause = SensitiveCustomError(f"Metrics failure for {sensitive_tokens[1]}: {sensitive_tokens[0]}")
        direct_error = ObservabilityStorageError()
        direct_error.__cause__ = nested_cause
        raise direct_error

    test_workflow_service.metrics_collector.get_summary = failing_metrics
    resp_metrics = test_client.get("/api/v1/observability/metrics")
    assert resp_metrics.status_code == 500
    assert resp_metrics.json() == {"detail": "Observability storage unavailable"}
    for token in sensitive_tokens:
        assert token not in resp_metrics.text

    # 4. Test /api/v1/reconciliation/run
    def failing_session_factory():
        nested_cause = SensitiveCustomError(f"Connection failed to {sensitive_tokens[1]} for query: {sensitive_tokens[0]}")
        direct_error = RuntimeError(
            f"Path failure {sensitive_tokens[2]} with schema {sensitive_tokens[4]} "
            f"and cert {sensitive_tokens[3]}: {sensitive_tokens[5]}"
        )
        raise direct_error from nested_cause

    test_workflow_service.session_factory = failing_session_factory
    resp_start = test_client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "period": "2026-Q1"},
    )
    assert resp_start.status_code == 500
    assert resp_start.json() == {"detail": "Workflow execution failed: Observability storage unavailable"}
    for token in sensitive_tokens:
        assert token not in resp_start.text

    # 5. Test /api/v1/approvals/{run_id}/decision
    # First, restore healthy session factory to start a workflow that pauses at HITL
    test_workflow_service.session_factory = db_session_factory
    with db_session_factory() as db:
        db.add(FinancialRecord(id="gl_sec_hitl", source="GL", account_code="SEC-HITL", amount=50.0, is_reconciled=False, transaction_date=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.commit()

    start_hitl = test_client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "SEC-HITL", "period": "2026-Q1", "run_id": "run_sec_hitl_001"},
    )
    assert start_hitl.status_code == 200 and start_hitl.json()["status"] == "hitl_pending"

    # Now inject the sensitive storage failure for approval decision
    test_workflow_service.session_factory = failing_session_factory
    resp_appr = test_client.post(
        "/api/v1/approvals/run_sec_hitl_001/decision",
        json={"decision": "approved", "reviewer": "SecurityAuditor"},
    )
    assert resp_appr.status_code == 500
    assert resp_appr.json() == {"detail": "Approval resume failed: Observability storage unavailable"}
    for token in sensitive_tokens:
        assert token not in resp_appr.text


@pytest.mark.asyncio
async def test_cancellation_immediately_after_terminal_persistence_records_single_terminal_event(
    test_workflow_service, db_session_factory, monkeypatch
):
    """Verify terminal_recorded immediately after terminal audit persistence prevents duplicate RUN_ERROR upon cancellation."""
    run_id = "run_cancel_post_term_001"

    # Hook finalize_run to simulate a cancellation occurring immediately after _persist_audit_event succeeded
    async def cancel_during_finalize(*args, **kwargs):
        raise asyncio.CancelledError("Cancellation delivered right after RUN_COMPLETED persistence")

    monkeypatch.setattr(test_workflow_service.metrics_collector, "finalize_run", cancel_during_finalize)

    with pytest.raises(asyncio.CancelledError):
        await test_workflow_service.start_workflow(
            workflow_type="accrual",
            period="2026-Q1",
            input_params={
                "accrual_entries": [{"vendor": "V1", "amount": 100.0}],
                "historical_baseline": {"V1": {"amount": 100.0}},
            },
            run_id=run_id,
        )

    # In DB, verify exactly one terminal record exists and it is RUN_COMPLETED, not RUN_ERROR
    with db_session_factory() as db:
        records = db.query(AuditTrailRecord).filter(AuditTrailRecord.run_id == run_id).all()
        types = [r.event_type for r in records]
        assert "RUN_COMPLETED" in types
        assert "RUN_ERROR" not in types
        terminal_records = [r for r in records if r.event_type in ("RUN_COMPLETED", "RUN_ERROR")]
        assert len(terminal_records) == 1
        assert terminal_records[0].event_type == "RUN_COMPLETED"


def test_conflicting_payloads_propagate_conflict_and_never_overwrite_or_swallow(
    test_workflow_service, db_session_factory
):
    """Verify existing audit ID is idempotent only for identical payloads, and conflicts are never swallowed or overwritten."""
    # 1. RUN_ERROR idempotency and conflict
    err_payload_1 = {"status": "error", "error_code": "ERR_A", "message": "Failed validation"}
    err_payload_2 = {"status": "error", "error_code": "ERR_B", "message": "Different failure"}

    test_workflow_service._persist_audit_event("rec_err_test", "run_err_test", "RUN_ERROR", err_payload_1)
    # Identical retry succeeds idempotently
    test_workflow_service._persist_audit_event("rec_err_test", "run_err_test", "RUN_ERROR", err_payload_1)
    # Conflicting payload raises RunConflictError
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event("rec_err_test", "run_err_test", "RUN_ERROR", err_payload_2)

    # 2. RUN_COMPLETED idempotency and conflict
    comp_payload_1 = {"status": "completed", "total_latency_ms": 100.0}
    comp_payload_2 = {"status": "completed", "total_latency_ms": 200.0}

    test_workflow_service._persist_audit_event("rec_comp_test", "run_comp_test", "RUN_COMPLETED", comp_payload_1)
    # Identical retry succeeds idempotently
    test_workflow_service._persist_audit_event("rec_comp_test", "run_comp_test", "RUN_COMPLETED", comp_payload_1)
    # Conflicting payload raises RunConflictError
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event("rec_comp_test", "run_comp_test", "RUN_COMPLETED", comp_payload_2)

    # 3. HITL_PENDING conflict
    hitl_p_1 = {"status": "hitl_pending", "exceptions_count": 1}
    hitl_p_2 = {"status": "hitl_pending", "exceptions_count": 2}
    test_workflow_service._persist_audit_event("rec_hitl_p_test", "run_hitl_test", "HITL_PENDING", hitl_p_1)
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event("rec_hitl_p_test", "run_hitl_test", "HITL_PENDING", hitl_p_2)

    # 4. HITL_DECISION conflict
    hitl_d_1 = {"decision": "approved", "reviewer": "Auditor 1"}
    hitl_d_2 = {"decision": "rejected", "reviewer": "Auditor 2"}
    test_workflow_service._persist_audit_event("rec_hitl_d_test", "run_hitl_test", "HITL_DECISION", hitl_d_1)
    with pytest.raises(RunConflictError):
        test_workflow_service._persist_audit_event("rec_hitl_d_test", "run_hitl_test", "HITL_DECISION", hitl_d_2)

    # Verify DB records were NEVER overwritten
    with db_session_factory() as db:
        rec_err = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "rec_err_test").first()
        assert rec_err.details == err_payload_1

        rec_comp = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "rec_comp_test").first()
        assert rec_comp.details == comp_payload_1

        rec_hitl_p = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "rec_hitl_p_test").first()
        assert rec_hitl_p.details == hitl_p_1

        rec_hitl_d = db.query(AuditTrailRecord).filter(AuditTrailRecord.id == "rec_hitl_d_test").first()
        assert rec_hitl_d.details == hitl_d_1

