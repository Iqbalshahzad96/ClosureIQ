"""
Focused Offline Integration Test Suite for ClosureIQ Workflow Integration

Tests end-to-end execution of:
- Reconciliation, Accrual, and Depreciation workflows
- LangGraph HITL gate (pause, checkpointing, and resumption)
- Case-insensitive approval decisions ("APPROVED", "rejected", invalid decisions)
- Exception persistence and querying
- Discriminated model input validation (422 responses)
- Atomic run ID reservation (409 Conflict)
- Per-run resumption lock and rejection of second resume (409 Conflict)
- Period propagation and persistence
- Database persistence failure rollback, session close, and skipping of downstream agents
- Shared checkpointer state across separate HTTP requests

Zero live network, Gemini API, or external service calls.
"""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.exception_analysis import ExceptionAnalysisAgent
from app.agents.financial_review import FinancialReviewAgent
from app.database.database import Base, get_db
from app.database.models import ExceptionRecord, FinancialRecord
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator
from app.financial_engine.reconciliation import ReconciliationEngine
from app.main import app
from app.mcp.tools import FinancialMCPTools
from app.services.workflow_service import WorkflowService, get_workflow_service


# ---------------------------------------------------------------------------
# Offline Socket Guard (Ensures Zero External Network Activity)
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
# Deterministic Fake Policy Retriever (Zero ChromaDB Downloads)
# ---------------------------------------------------------------------------

class FakePolicyRetriever:
    """Deterministic local policy retriever for fast, zero-download offline testing."""

    def __init__(self, sample_evidence: Optional[List[Dict[str, Any]]] = None) -> None:
        self._sample_evidence = sample_evidence or [
            {
                "chunk_id": "pol_chunk_001",
                "content": (
                    "All general ledger cash accounts must be reconciled against official bank statements monthly. "
                    "Unmatched items exceeding $50.00 must be flagged for manual investigation. "
                    "Timing differences must be evaluated."
                ),
                "metadata": {"policy_id": "ACC-001", "category": "BANK_RECONCILIATION"},
                "distance": 0.05,
                "citation": "[ACC-001] Corporate Accounting Policies — Section: Bank Reconciliation Standard",
            },
            {
                "chunk_id": "pol_chunk_002",
                "content": "Material variances exceeding 10% against prior baseline require explanatory variance notes.",
                "metadata": {"policy_id": "ACC-002", "category": "ACCRUAL"},
                "distance": 0.08,
                "citation": "[ACC-002] Corporate Accounting Policies — Section: Accrual & Expense Matching",
            },
            {
                "chunk_id": "pol_chunk_003",
                "content": "Fixed asset depreciation schedules must use straight line method based on useful life.",
                "metadata": {"policy_id": "ACC-003", "category": "DEPRECIATION"},
                "distance": 0.09,
                "citation": "[ACC-003] Corporate Accounting Policies — Section: Fixed Assets",
            },
        ]

    async def retrieve_policy_context(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if category:
            matched = [e for e in self._sample_evidence if e["metadata"].get("category") == category]
            if matched:
                return matched[:top_k]
        return self._sample_evidence[:top_k]


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


@pytest.fixture()
def fake_policy_retriever():
    """Deterministic offline policy retriever."""
    return FakePolicyRetriever()


@pytest.fixture()
def fake_agents():
    """Deterministic offline async fakes for Agent 1 and Agent 2."""
    agent_1_calls = []
    agent_2_calls = []

    async def fake_model_1(system_instruction: str, user_content: str) -> str:
        agent_1_calls.append((system_instruction, user_content))
        data = json.loads(user_content.split("\n", 1)[1].rsplit("\n", 1)[0])
        exceptions = data.get("exceptions", [])
        findings = []
        for exc in exceptions:
            findings.append({
                "exception_index": exc["exception_index"],
                "classification": "TIMING_DIFFERENCE",
                "financial_context": f"Timing variance for {exc.get('id', 'exception')}",
            })
        return json.dumps({
            "summary_assessment": f"Reviewed {len(exceptions)} exception(s). Timing variances noted.",
            "findings": findings,
        })

    async def fake_model_2(system_instruction: str, user_content: str) -> str:
        agent_2_calls.append((system_instruction, user_content))
        data = json.loads(user_content.split("\n", 1)[1].rsplit("\n", 1)[0])
        evidence = data.get("rag_evidence", [])
        evidence_indices = [0] if evidence else []
        return json.dumps({
            "analysis": "Unmatched ledger transaction due to end-of-month bank transit delay.",
            "root_cause": "Timing difference in bank clearing cycle.",
            "recommendation": "Post temporary transit accrual pending bank deposit settlement.",
            "evidence_indices": evidence_indices,
        })

    a1 = FinancialReviewAgent(model_callable=fake_model_1)
    a2 = ExceptionAnalysisAgent(model_callable=fake_model_2)
    return a1, a2, agent_1_calls, agent_2_calls


@pytest.fixture()
def workflow_test_env(db_session_factory, fake_policy_retriever, fake_agents):
    """Configured WorkflowService and FastAPI TestClient with shared MemorySaver."""
    a1, a2, a1_calls, a2_calls = fake_agents
    shared_checkpointer = MemorySaver()

    service = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=FinancialMCPTools(session_factory=db_session_factory),
        reconciliation_engine=ReconciliationEngine(tolerance=0.01),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=a1,
        policy_retriever=fake_policy_retriever,
        exception_analysis_agent=a2,
        checkpointer=shared_checkpointer,
    )

    app.state.workflow_service = service

    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workflow_service] = lambda: service

    client = TestClient(app)

    yield {
        "client": client,
        "service": service,
        "session_factory": db_session_factory,
        "a1_calls": a1_calls,
        "a2_calls": a2_calls,
    }

    app.dependency_overrides.clear()
    if hasattr(app.state, "workflow_service"):
        delattr(app.state, "workflow_service")


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

def test_clean_reconciliation_skips_agents_and_hitl(workflow_test_env):
    """Clean close without exceptions completes immediately with status='clean_close'."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]
    a1_calls = workflow_test_env["a1_calls"]
    a2_calls = workflow_test_env["a2_calls"]

    # Seed matching GL and Bank transactions for account 1010
    session = factory()
    session.add_all([
        FinancialRecord(
            id="gl_001", source="GL", account_code="1010",
            transaction_date=datetime(2026, 1, 15, 10, 0, 0),
            amount=1000.00, reference="INV-1001", is_reconciled=False,
        ),
        FinancialRecord(
            id="bank_001", source="BANK", account_code="1010",
            transaction_date=datetime(2026, 1, 15, 12, 0, 0),
            amount=1000.00, reference="INV-1001", is_reconciled=False,
        ),
    ])
    session.commit()
    session.close()

    # Trigger reconciliation
    resp = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "period": "2026-Q1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "clean_close"
    assert data["exceptions_count"] == 0
    assert data["validation_results"]["reconciliation_rate"] == 100.0

    # Verify AI agents were NOT invoked
    assert len(a1_calls) == 0
    assert len(a2_calls) == 0

    # Verify no pending approvals exist
    pending_resp = client.get("/api/v1/approvals/pending")
    assert pending_resp.status_code == 200
    assert pending_resp.json() == []


def test_exception_flow_pauses_at_hitl_with_grounded_recommendations(workflow_test_env):
    """Exception flow invokes Agent 1 and Agent 2 and pauses at HITL gate with recommendations."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]
    a1_calls = workflow_test_env["a1_calls"]
    a2_calls = workflow_test_env["a2_calls"]

    # Seed unmatched transactions (1 matched, 1 unmatched GL, 1 unmatched BANK)
    session = factory()
    session.add_all([
        FinancialRecord(
            id="gl_match", source="GL", account_code="1010",
            amount=500.00, reference="MATCH-01", is_reconciled=False,
        ),
        FinancialRecord(
            id="bank_match", source="BANK", account_code="1010",
            amount=500.00, reference="MATCH-01", is_reconciled=False,
        ),
        FinancialRecord(
            id="gl_unmatched", source="GL", account_code="1010",
            amount=2500.00, reference="UNMATCH-GL", description="Unreconciled invoice",
            is_reconciled=False,
        ),
        FinancialRecord(
            id="bank_unmatched", source="BANK", account_code="1010",
            amount=750.00, reference="UNMATCH-BK", description="Unrecognized fee deposit",
            is_reconciled=False,
        ),
    ])
    session.commit()
    session.close()

    # Trigger reconciliation
    resp = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "period": "2026-Q1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "hitl_pending"
    assert data["exceptions_count"] == 2
    assert data["recommendations_count"] == 2
    assert len(data["recommendations"]) == 2

    # Verify Agent 1 and Agent 2 were invoked
    assert len(a1_calls) == 1
    assert len(a2_calls) == 2

    run_id = data["run_id"]

    # Verify pending approvals endpoint lists this paused run
    pending_resp = client.get("/api/v1/approvals/pending")
    assert pending_resp.status_code == 200
    pending_list = pending_resp.json()
    assert len(pending_list) == 1
    assert pending_list[0]["run_id"] == run_id
    assert len(pending_list[0]["recommendations"]) == 2


def test_hitl_approval_and_rejection_resumes_same_run(workflow_test_env):
    """Test that submitting approval or rejection resumes the paused checkpoint to completion."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    # 1. Seed unmatched transaction
    session = factory()
    session.add(
        FinancialRecord(
            id="gl_disc_1", source="GL", account_code="1010",
            amount=1500.00, reference="DISC-01", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    # Run workflow -> pauses at HITL
    run_resp = client.post("/api/v1/reconciliation/run", json={"account_code": "1010"})
    run_id = run_resp.json()["run_id"]
    assert run_resp.json()["status"] == "hitl_pending"

    # Submit APPROVAL (case-insensitive "APPROVED")
    decision_resp = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={"decision": "APPROVED", "reviewer": "Jane Doe", "comments": "Signed off"},
    )
    assert decision_resp.status_code == 200
    dec_data = decision_resp.json()
    assert dec_data["status"] == "approved"
    assert dec_data["decision"] == "approved"

    # Verify summary reflects "approved"
    summary_resp = client.get(f"/api/v1/reconciliation/summary?run_id={run_id}")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["status"] == "approved"

    # Verify pending list is now empty
    pending_resp = client.get("/api/v1/approvals/pending")
    assert pending_resp.json() == []

    # 2. Test REJECTION on a second run
    run_resp_2 = client.post("/api/v1/reconciliation/run", json={"account_code": "1010"})
    run_id_2 = run_resp_2.json()["run_id"]

    reject_resp = client.post(
        f"/api/v1/approvals/{run_id_2}/decision",
        json={"decision": "rejected", "reviewer": "Audit Lead"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    summary_2 = client.get(f"/api/v1/reconciliation/summary?run_id={run_id_2}")
    assert summary_2.json()["status"] == "rejected"


def test_decision_case_insensitivity_and_invalid_decision_handling(workflow_test_env):
    """Case normalization handles mixed case; invalid decision returns 400 Bad Request."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add(
        FinancialRecord(
            id="gl_case_test", source="GL", account_code="1010",
            amount=800.00, reference="CASE-01", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    run_resp = client.post("/api/v1/reconciliation/run", json={"account_code": "1010"})
    run_id = run_resp.json()["run_id"]

    # Invalid decision returns 400
    bad_resp = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={"decision": "maybe", "reviewer": "Test"},
    )
    assert bad_resp.status_code == 400
    assert "approved" in bad_resp.json()["detail"].lower()

    # Unknown run_id returns 404
    missing_resp = client.post(
        "/api/v1/approvals/non_existent_run_999/decision",
        json={"decision": "approved"},
    )
    assert missing_resp.status_code == 404

    # Mixed-case "ApPrOvEd" succeeds
    good_resp = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={"decision": "ApPrOvEd", "reviewer": "Senior Accountant"},
    )
    assert good_resp.status_code == 200
    assert good_resp.json()["status"] == "approved"


def test_duplicate_run_id_returns_409(workflow_test_env):
    """Starting a workflow with a duplicate run ID returns HTTP 409 Conflict."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add(
        FinancialRecord(
            id="gl_dup_1", source="GL", account_code="1010",
            amount=500.00, reference="DUP-01", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    fixed_run_id = "test_run_dup_123"
    payload = {"account_code": "1010", "run_id": fixed_run_id}

    # First start: succeeds
    resp1 = client.post("/api/v1/reconciliation/run", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["run_id"] == fixed_run_id

    # Second start with identical run_id: must return HTTP 409 Conflict
    resp2 = client.post("/api/v1/reconciliation/run", json=payload)
    assert resp2.status_code == 409
    assert "already exists" in resp2.json()["detail"].lower()


def test_concurrent_and_second_resume_on_terminal_run_returns_409(workflow_test_env):
    """Submitting two decisions simultaneously returns 200 for one and 409 for the other,
    and a subsequent decision on the terminal run returns 409."""
    import httpx

    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add(
        FinancialRecord(
            id="gl_conflict_test", source="GL", account_code="1010",
            amount=900.00, reference="CONF-01", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    # Start run -> pauses at HITL
    resp = client.post("/api/v1/reconciliation/run", json={"account_code": "1010"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "hitl_pending"

    # Genuinely concurrent submission: submit two decisions simultaneously for the same pending run
    async def submit_concurrent_decisions():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            return await asyncio.gather(
                ac.post(
                    f"/api/v1/approvals/{run_id}/decision",
                    json={"decision": "approved", "reviewer": "Reviewer 1"},
                ),
                ac.post(
                    f"/api/v1/approvals/{run_id}/decision",
                    json={"decision": "rejected", "reviewer": "Reviewer 2"},
                ),
            )

    resp1, resp2 = asyncio.run(submit_concurrent_decisions())

    # Assert exactly one succeeds (200) and the other returns 409 Conflict
    status_codes = [resp1.status_code, resp2.status_code]
    assert sorted(status_codes) == [200, 409], f"Expected [200, 409], got {status_codes}"

    success_resp = resp1 if resp1.status_code == 200 else resp2
    conflict_resp = resp2 if resp1.status_code == 200 else resp1
    assert success_resp.json()["status"] in ("approved", "rejected")
    assert "already completed" in conflict_resp.json()["detail"].lower()

    # Retain the separate second-resume-after-terminal assertion:
    # Submitting another decision now that the run is terminal must return 409 Conflict
    terminal_resp = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={"decision": "approved", "reviewer": "Reviewer 3"},
    )
    assert terminal_resp.status_code == 409
    assert "already completed" in terminal_resp.json()["detail"].lower()



def test_period_preservation(workflow_test_env):
    """Ensure requested period is cleanly propagated into exception objects and database records."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add(
        FinancialRecord(
            id="gl_period_test", source="GL", account_code="1010",
            amount=1250.00, reference="PER-01", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    target_period = "2026-Q3-TEST"
    resp = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "period": target_period},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == target_period
    assert data["exceptions_count"] == 1
    assert data["exceptions"][0]["period"] == target_period

    # Verify database ExceptionRecord has target_period
    db = factory()
    try:
        exc_rec = db.query(ExceptionRecord).filter(ExceptionRecord.id == data["exceptions"][0]["id"]).first()
        assert exc_rec is not None
        assert exc_rec.period == target_period
    finally:
        db.close()


def test_exact_persistence_count_and_no_duplicates(workflow_test_env):
    """Workflow persists exact number of generated exceptions without duplicating on re-checks."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add_all([
        FinancialRecord(
            id="gl_cnt_1", source="GL", account_code="1010",
            amount=111.00, reference="CNT-01", is_reconciled=False,
        ),
        FinancialRecord(
            id="bank_cnt_2", source="BANK", account_code="1010",
            amount=222.00, reference="CNT-02", is_reconciled=False,
        ),
    ])
    session.commit()
    session.close()

    resp = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "period": "2026-Q1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["exceptions_count"] == 2

    # Query DB directly to verify exact count
    db = factory()
    try:
        records = db.query(ExceptionRecord).all()
        assert len(records) == 2
        ids = {r.id for r in records}
        expected_ids = {e["id"] for e in data["exceptions"]}
        assert ids == expected_ids
    finally:
        db.close()


def test_persistence_failure_rollback_rethrow_session_closed_and_agents_skipped(fake_agents):
    """When DB persistence fails: session rolls back, closes, rethrows, workflow ends in error, and agents are skipped."""
    a1, a2, a1_calls, a2_calls = fake_agents
    rollback_called = False
    close_called = False

    class FailingSession:
        def __init__(self):
            self.fail_commit = False

        def get(self, *args, **kwargs):
            return None

        def add(self, record):
            # Reservation/audit writes are healthy; this legacy integration
            # scenario targets only exception-record persistence.
            self.fail_commit = isinstance(record, ExceptionRecord)

        def commit(self):
            if self.fail_commit:
                raise RuntimeError("Simulated DB commit disk failure")

        def rollback(self):
            nonlocal rollback_called
            rollback_called = True

        def close(self):
            nonlocal close_called
            close_called = True

    def failing_session_factory():
        return FailingSession()

    failing_service = WorkflowService(
        session_factory=failing_session_factory,
        reconciliation_engine=ReconciliationEngine(),
        accrual_engine=AccrualEngine(),
        depreciation_engine=DepreciationEngine(),
        exception_generator=ExceptionGenerator(),
        financial_review_agent=a1,
        policy_retriever=FakePolicyRetriever(),
        exception_analysis_agent=a2,
        checkpointer=MemorySaver(),
    )

    input_params = {
        "accrual_entries": [{"vendor": "BadVendor", "amount": 99999.0}],
        "historical_baseline": {"BadVendor": 10.0},
    }

    result = asyncio.run(
        failing_service.start_workflow(
            workflow_type="accrual",
            period="2026-Q1",
            input_params=input_params,
        )
    )

    # 1. Rollback and close must have been invoked
    assert rollback_called is True
    assert close_called is True

    # 2. Workflow must terminate as error
    assert result["status"] == "error"
    assert len(result["errors"]) > 0
    assert "Database persistence failed" in result["errors"][0]

    # 3. Agents and HITL must NOT have executed
    assert len(a1_calls) == 0
    assert len(a2_calls) == 0
    assert result["recommendations_count"] == 0


def test_exceptions_persist_once_and_are_queryable(workflow_test_env):
    """Exceptions generated by the workflow persist to exception_records and are queryable."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add(
        FinancialRecord(
            id="gl_persist_1", source="GL", account_code="1010",
            amount=4200.00, reference="PERSIST-01", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    run_resp = client.post("/api/v1/reconciliation/run", json={"account_code": "1010"})
    assert run_resp.status_code == 200
    exc_list = run_resp.json()["exceptions"]
    assert len(exc_list) == 1
    target_exc_id = exc_list[0]["id"]

    # Query all exceptions from API
    get_all_resp = client.get("/api/v1/exceptions/")
    assert get_all_resp.status_code == 200
    all_excs = get_all_resp.json()
    assert len(all_excs) >= 1
    assert any(e["id"] == target_exc_id for e in all_excs)

    # Query single exception by ID
    get_one_resp = client.get(f"/api/v1/exceptions/{target_exc_id}")
    assert get_one_resp.status_code == 200
    exc_detail = get_one_resp.json()
    assert exc_detail["id"] == target_exc_id
    assert exc_detail["amount_variance"] == 4200.00
    assert exc_detail["category"] == "RECONCILIATION"

    # Query unknown exception returns 404
    assert client.get("/api/v1/exceptions/non_existent_id").status_code == 404


def test_accrual_workflow_dispatches_to_accrual_engine(workflow_test_env):
    """Accrual workflow runs deterministically via AccrualEngine."""
    client = workflow_test_env["client"]

    # Clean accrual within threshold
    accrual_clean_payload = {
        "workflow_type": "accrual",
        "period": "2026-Q1",
        "input_params": {
            "accrual_entries": [{"vendor": "AWS Cloud", "account_code": "6100", "amount": 5050.00}],
            "historical_baseline": {"AWS Cloud": 5000.00},
        },
    }
    resp = client.post("/api/v1/reconciliation/run", json=accrual_clean_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "clean_close"
    assert data["validation_results"]["valid_accruals_count"] == 1
    assert data["validation_results"]["anomalies_count"] == 0

    # Accrual anomaly (material variance > 10%)
    accrual_anomaly_payload = {
        "workflow_type": "accrual",
        "period": "2026-Q1",
        "input_params": {
            "accrual_entries": [{"vendor": "Audit Firm", "account_code": "6200", "amount": 15000.00}],
            "historical_baseline": {"Audit Firm": 8000.00},
        },
    }
    resp2 = client.post("/api/v1/reconciliation/run", json=accrual_anomaly_payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "hitl_pending"
    assert data2["exceptions_count"] == 1


def test_depreciation_workflow_dispatches_to_depreciation_engine(workflow_test_env):
    """Depreciation workflow runs deterministically via DepreciationEngine."""
    client = workflow_test_env["client"]

    dep_clean_payload = {
        "workflow_type": "depreciation",
        "period": "2026-Q1",
        "input_params": {
            "asset_records": [
                {
                    "asset_id": "AST-100",
                    "asset_name": "Server",
                    "cost": 36000.00,
                    "salvage_value": 0.0,
                    "useful_life_months": 36,
                }
            ],
            "period_posted_depreciation": {"AST-100": 1000.00},
        },
    }
    resp = client.post("/api/v1/reconciliation/run", json=dep_clean_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "clean_close"
    assert data["validation_results"]["total_calculated_depreciation"] == 1000.00
    assert len(data["validation_results"]["discrepancies"]) == 0


def test_invalid_payloads_return_422(workflow_test_env):
    """Missing and invalid inputs fail Pydantic model validation with HTTP 422."""
    client = workflow_test_env["client"]

    # 1. Reconciliation missing account_code
    resp_rec = client.post("/api/v1/reconciliation/run", json={"workflow_type": "reconciliation"})
    assert resp_rec.status_code == 422

    # 2. Reconciliation invalid limit (0 - below ge=1)
    resp_limit_low = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "limit": 0},
    )
    assert resp_limit_low.status_code == 422

    # 3. Reconciliation invalid limit (101 - above le=100)
    resp_limit_high = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "limit": 101},
    )
    assert resp_limit_high.status_code == 422

    # 4. Accrual empty accrual_entries container
    resp_acc_empty = client.post(
        "/api/v1/reconciliation/run",
        json={"workflow_type": "accrual", "input_params": {"accrual_entries": [], "historical_baseline": {"Vendor": 100.0}}},
    )
    assert resp_acc_empty.status_code == 422

    # 5. Accrual missing historical_baseline
    resp_acc_no_base = client.post(
        "/api/v1/reconciliation/run",
        json={"workflow_type": "accrual", "input_params": {"accrual_entries": [{"vendor": "V", "amount": 50.0}]}},
    )
    assert resp_acc_no_base.status_code == 422

    # 6. Depreciation missing asset_records
    resp_dep_no_assets = client.post(
        "/api/v1/reconciliation/run",
        json={"workflow_type": "depreciation", "input_params": {"period_posted_depreciation": {"AST-1": 100.0}}},
    )
    assert resp_dep_no_assets.status_code == 422

    # 7. Depreciation useful_life_months <= 0
    resp_dep_bad_life = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "depreciation",
            "input_params": {
                "asset_records": [
                    {
                        "asset_id": "AST-100",
                        "cost": 1000.0,
                        "useful_life_months": 0,
                    }
                ],
                "period_posted_depreciation": {"AST-100": 100.0},
            },
        },
    )
    assert resp_dep_bad_life.status_code == 422

    # 8. Invalid workflow_type discriminator tag
    resp_bad_type = client.post(
        "/api/v1/reconciliation/run",
        json={"workflow_type": "unknown_workflow", "account_code": "1010"},
    )
    assert resp_bad_type.status_code == 422

    # 9. Blank/whitespace account_code
    resp_blank_acct = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "   "},
    )
    assert resp_blank_acct.status_code == 422

    # 10. Blank/whitespace period
    resp_blank_period = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "period": "   "},
    )
    assert resp_blank_period.status_code == 422

    # 11. Blank/whitespace run_id
    resp_blank_run_id = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "run_id": "   "},
    )
    assert resp_blank_run_id.status_code == 422

    # 12. Extra forbidden field at root (extra="forbid")
    resp_extra_root = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "forbidden_field": 123},
    )
    assert resp_extra_root.status_code == 422

    # 13. Blank/whitespace baseline key
    resp_blank_base_key = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "accrual",
            "input_params": {
                "accrual_entries": [{"vendor": "V1", "amount": 100.0}],
                "historical_baseline": {"  ": 100.0},
            },
        },
    )
    assert resp_blank_base_key.status_code == 422

    # 14. Non-finite (NaN / Infinity) numeric values rejected
    resp_inf_val = client.post(
        "/api/v1/reconciliation/run",
        content='{"workflow_type": "accrual", "input_params": {"accrual_entries": [{"vendor": "V1", "amount": 1e999}], "historical_baseline": {"V1": 100.0}}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp_inf_val.status_code == 422

    resp_str_nan = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "accrual",
            "input_params": {
                "accrual_entries": [{"vendor": "V1", "amount": "NaN"}],
                "historical_baseline": {"V1": 100.0},
            },
        },
    )
    assert resp_str_nan.status_code == 422

    # Direct Pydantic models reject float('nan') and float('inf')
    from app.api.routes.reconciliation import AccrualEntryItem
    with pytest.raises(Exception):
        AccrualEntryItem(vendor="V1", amount=float("nan"))
    with pytest.raises(Exception):
        AccrualEntryItem(vendor="V1", amount=float("inf"))

    # 15. Negative cost in asset record
    resp_neg_cost = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "depreciation",
            "input_params": {
                "asset_records": [{"asset_id": "AST-1", "cost": -100.0, "useful_life_months": 12}],
                "period_posted_depreciation": {"AST-1": 10.0},
            },
        },
    )
    assert resp_neg_cost.status_code == 422

    # 16. Non-dict input_params container
    resp_bad_container = client.post(
        "/api/v1/reconciliation/run",
        json={"account_code": "1010", "input_params": "not-a-dict"},
    )
    assert resp_bad_container.status_code == 422


def test_get_workflow_service_requires_app_state():
    """get_workflow_service(request) must strictly require request.app.state.workflow_service."""
    from unittest.mock import MagicMock
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.app.state = type("EmptyState", (), {})()

    with pytest.raises(RuntimeError, match="WorkflowService is not initialized on app.state"):
        get_workflow_service(mock_request)



def test_shared_checkpointer_across_separate_http_requests(workflow_test_env):
    """Demonstrate state persistence across separate HTTP requests via shared MemorySaver."""
    client = workflow_test_env["client"]
    factory = workflow_test_env["session_factory"]

    session = factory()
    session.add(
        FinancialRecord(
            id="gl_state_test", source="GL", account_code="1010",
            amount=990.00, reference="STATE-REF", is_reconciled=False,
        )
    )
    session.commit()
    session.close()

    # Request 1: Start workflow
    r1 = client.post("/api/v1/reconciliation/run", json={"account_code": "1010"})
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]
    assert r1.json()["status"] == "hitl_pending"

    # Request 2: Inspect summary
    r2 = client.get(f"/api/v1/reconciliation/summary?run_id={run_id}")
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id
    assert r2.json()["status"] == "hitl_pending"

    # Request 3: Check pending list
    r3 = client.get("/api/v1/approvals/pending")
    assert r3.status_code == 200
    assert any(p["run_id"] == run_id for p in r3.json())

    # Request 4: Submit approval
    r4 = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={"decision": "APPROVED", "reviewer": "Controller"},
    )
    assert r4.status_code == 200
    assert r4.json()["status"] == "approved"

    # Request 5: Verify final state
    r5 = client.get(f"/api/v1/reconciliation/summary?run_id={run_id}")
    assert r5.status_code == 200
    assert r5.json()["status"] == "approved"
