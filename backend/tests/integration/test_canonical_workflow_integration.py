"""
Phase 3B — Canonical Financial Workflow Integration Tests

Tests end-to-end execution of all financial review workflows
(Reconciliation, Accrual Review, Fixed Asset Depreciation, AP Invoices)
operating strictly on canonical DB data with ZERO raw-file dependencies.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.exception_analysis import ExceptionAnalysisAgent
from app.agents.financial_review import FinancialReviewAgent
from app.database.database import Base, get_db
from app.database.models import ExceptionRecord, ReconciliationResult, ReconciliationRun
from tests.canonical_fixtures import (
    ap_invoice_record,
    financial_record,
    fixed_asset_record,
    trial_balance_record,
)
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.ap import APEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator
from app.financial_engine.reconciliation import ReconciliationEngine
from app.main import app
from app.mcp.tools import FinancialMCPTools
from app.services.workflow_service import WorkflowService, get_workflow_service


class FakePolicyRetriever:
    """Deterministic local policy retriever for offline tests."""

    def __init__(self) -> None:
        self._sample_evidence = [
            {
                "chunk_id": "pol_chunk_001",
                "content": "All general ledger cash accounts must be reconciled against official bank statements monthly.",
                "metadata": {"policy_id": "ACC-001", "category": "BANK_RECONCILIATION"},
                "distance": 0.05,
                "citation": "[ACC-001] Corporate Accounting Policies — Bank Reconciliation",
            },
            {
                "chunk_id": "pol_chunk_002",
                "content": "Material variances exceeding 10% against prior baseline require explanatory variance notes.",
                "metadata": {"policy_id": "ACC-002", "category": "ACCRUAL"},
                "distance": 0.08,
                "citation": "[ACC-002] Corporate Accounting Policies — Accruals",
            },
            {
                "chunk_id": "pol_chunk_003",
                "content": "Fixed asset depreciation schedules must use straight line method based on useful life.",
                "metadata": {"policy_id": "ACC-003", "category": "DEPRECIATION"},
                "distance": 0.09,
                "citation": "[ACC-003] Corporate Accounting Policies — Fixed Assets",
            },
        ]

    async def retrieve_policy_context(self, query: str, top_k: int = 3, category: str | None = None):
        if category:
            filtered = [e for e in self._sample_evidence if e.get("metadata", {}).get("category") == category]
            if filtered:
                return filtered[:top_k]
        return self._sample_evidence[:top_k]


@pytest.fixture()
def db_session_factory():
    """Create in-memory SQLite engine and session factory."""
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
def workflow_service(db_session_factory):
    """Construct WorkflowService with in-memory DB and fake policy retriever."""
    mcp_tools = FinancialMCPTools(session_factory=db_session_factory)
    rec_engine = ReconciliationEngine(tolerance=0.01)
    acc_engine = AccrualEngine(variance_threshold_pct=0.10, material_amount_threshold=50.0)
    dep_engine = DepreciationEngine(tolerance=0.01)
    ap_engine = APEngine(tolerance=0.01)
    exc_gen = ExceptionGenerator()

    async def fake_model_a1(sys_prompt: str, user_prompt: str) -> str:
        import re, json
        indices = [int(m) for m in re.findall(r'"exception_index":\s*(\d+)', user_prompt)] or [0]
        findings = [
            {"exception_index": idx, "classification": "MATERIAL_BREAK", "financial_context": "Discrepancy detected"}
            for idx in sorted(set(indices))
        ]
        return json.dumps({"summary_assessment": "Review complete", "findings": findings})

    async def fake_model_a2(sys_prompt: str, user_prompt: str) -> str:
        return '{"analysis": "Policy review complete", "root_cause": "Timing difference or unrecorded transaction", "recommendation": "Review transaction details and post adjusting entry", "evidence_indices": [0]}'

    agent_1 = FinancialReviewAgent(model_callable=fake_model_a1)
    agent_2 = ExceptionAnalysisAgent(model_callable=fake_model_a2)
    policy_retriever = FakePolicyRetriever()

    svc = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=mcp_tools,
        reconciliation_engine=rec_engine,
        accrual_engine=acc_engine,
        depreciation_engine=dep_engine,
        ap_engine=ap_engine,
        exception_generator=exc_gen,
        financial_review_agent=agent_1,
        policy_retriever=policy_retriever,
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
    )
    return svc


@pytest.fixture()
def client(workflow_service, db_session_factory):
    """FastAPI TestClient with overridden dependencies."""
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_workflow_service] = lambda: workflow_service
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        app.state.workflow_service = workflow_service
        yield test_client
    app.dependency_overrides.clear()
    if hasattr(app.state, "workflow_service"):
        delattr(app.state, "workflow_service")


# ===========================================================================
# 1. Reconciliation Workflow via Canonical DB
# ===========================================================================

def test_canonical_reconciliation_workflow_clean_close(client, db_session_factory):
    """Reconciliation matches GL and Bank rows from canonical DB with zero variance."""
    session = db_session_factory()
    try:
        financial_record(
            session,
            id="gl_rec_1",
            source="GL",
            account_code="1010",
            amount=5000.00,
            reference="WIRE-001",
            transaction_date=datetime(2026, 1, 15),
        )
        financial_record(
            session,
            id="bk_rec_1",
            source="BANK",
            account_code="1010",
            amount=5000.00,
            reference="WIRE-001",
            transaction_date=datetime(2026, 1, 15),
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "reconciliation",
            "account_code": "1010",
            "period": "2026-01",
            "limit": 50,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "clean_close"
    assert data["workflow_type"] == "reconciliation"
    assert data["validation_results"]["matched_count"] == 1
    assert data["validation_results"]["net_variance"] == 0.0
    assert len(data["exceptions"]) == 0


def test_canonical_reconciliation_workflow_discrepancies_hitl(client, db_session_factory):
    """Reconciliation with unmatched GL line triggers HITL approval gate and persists results."""
    session = db_session_factory()
    try:
        financial_record(
            session,
            id="gl_unmatched_1",
            source="GL",
            account_code="1010",
            amount=12500.00,
            reference="UNMATCHED-REF",
            transaction_date=datetime(2026, 1, 20),
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "reconciliation",
            "account_code": "1010",
            "period": "2026-01",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "hitl_pending", f"Errors: {data.get('errors')}"
    assert len(data["exceptions"]) == 1
    assert data["exceptions"][0]["severity"] == "HIGH"
    assert data["exceptions"][0]["amount_variance"] == 12500.00

    # Verify exception persisted in DB and linked to reconciliation_result
    db = db_session_factory()
    try:
        exc = db.query(ExceptionRecord).filter_by(category="RECONCILIATION").first()
        assert exc is not None
        assert exc.amount_variance == 12500.00
        assert exc.reconciliation_result_id is not None

        res = db.query(ReconciliationResult).filter_by(id=exc.reconciliation_result_id).first()
        assert res is not None
        assert res.status == "UNMATCHED"
        assert res.journal_line_id == "gl_unmatched_1"
    finally:
        db.close()


# ===========================================================================
# 2. Accrual Review Workflow via Canonical DB
# ===========================================================================

def test_canonical_accrual_workflow_from_gl_entries(client, db_session_factory):
    """Accrual review querying canonical GL postings and comparing to baseline."""
    session = db_session_factory()
    try:
        financial_record(
            session,
            id="gl_accrual_1",
            source="GL",
            account_code="6010",
            amount=8500.00,
            description="Audit Fees",
            reference="AUDIT-2026",
            transaction_date=datetime(2026, 1, 31),
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "accrual",
            "account_code": "6010",
            "period": "2026-01",
            "historical_baseline": {
                "Audit Fees": {"amount": 5000.00}  # $3500 variance > 10% and > $50
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "hitl_pending"
    assert len(data["exceptions"]) == 1
    assert data["exceptions"][0]["category"] == "ACCRUAL"
    assert data["exceptions"][0]["amount_variance"] == 3500.00


# ===========================================================================
# 3. Fixed Asset Depreciation Workflow via Canonical DB
# ===========================================================================

def test_canonical_depreciation_workflow_from_fixed_assets(client, db_session_factory):
    """Depreciation workflow queries canonical FixedAsset table and validates straight-line depreciation."""
    session = db_session_factory()
    try:
        fixed_asset_record(
            session,
            id="fa_test_1",
            asset_code="FA-SRV",
            asset_name="Core Database Server",
            acquisition_cost=36000.00,
            salvage_value=0.0,
            useful_life_months=36,  # Expected monthly = $1000.00
            status="ACTIVE",
        )
        session.commit()
    finally:
        session.close()

    # Case A: Correct posted depreciation ($1000.00)
    resp_clean = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "depreciation",
            "period": "2026-01",
            "period_posted_depreciation": {
                "fa_test_1": {"amount": 1000.00}
            },
        },
    )

    assert resp_clean.status_code == 200
    clean_data = resp_clean.json()
    assert clean_data["status"] == "clean_close"
    assert len(clean_data["exceptions"]) == 0

    # Case B: Discrepant posted depreciation ($500.00 vs $1000.00 expected)
    resp_break = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "depreciation",
            "period": "2026-01",
            "period_posted_depreciation": {
                "fa_test_1": {"amount": 500.00}
            },
        },
    )

    assert resp_break.status_code == 200
    break_data = resp_break.json()
    assert break_data["status"] == "hitl_pending"
    assert len(break_data["exceptions"]) == 1
    assert break_data["exceptions"][0]["category"] == "DEPRECIATION"
    assert abs(break_data["exceptions"][0]["amount_variance"]) == 500.00


# ===========================================================================
# 4. AP Invoice Workflow via Canonical DB
# ===========================================================================

def test_canonical_ap_invoice_workflow(client, db_session_factory):
    """AP workflow queries canonical AP invoices and detects math discrepancies / duplicate invoices."""
    session = db_session_factory()
    try:
        ap_invoice_record(
            session,
            id="inv_dup_1",
            vendor_name="Vendor ABC",
            invoice_number="INV-DUP-100",
            subtotal_amount=2000.00,
            tax_amount=320.00,
            total_amount=2320.00,
        )
        ap_invoice_record(
            session,
            id="inv_dup_2",
            vendor_name="Vendor ABC",
            invoice_number="INV-DUP-100",  # Duplicate number
            subtotal_amount=2000.00,
            tax_amount=320.00,
            total_amount=2320.00,
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "ap_review",
            "period": "2026-01",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "hitl_pending", f"Errors: {data.get('errors')}"
    assert len(data["exceptions"]) == 1
    assert data["exceptions"][0]["category"] == "AP_REVIEW"
    assert data["exceptions"][0]["amount_variance"] == 2320.00
    assert "Duplicate invoice number" in data["exceptions"][0]["description"]


# ===========================================================================
# 5. Lineage Preservation Across Canonical DB -> MCP -> Engine -> Agents
# ===========================================================================

def test_canonical_workflow_lineage_preservation_across_agents(client, db_session_factory):
    """Lineage from canonical SourceFile and ImportBatch is retained in exceptions and agent findings."""
    from app.database.models import ImportBatch, SourceFile, SourceSystem, JournalEntry, JournalLine, Account

    session = db_session_factory()
    try:
        ss = SourceSystem(
            id="ss_lineage_test",
            organization_id="default_org",
            adapter_key="generic_gl",
            source_type="GL",
            display_name="Enterprise GL System",
            is_active=True,
        )
        session.add(ss)
        session.flush()

        batch = ImportBatch(
            id="batch_lineage_test",
            source_system_id=ss.id,
            organization_id="default_org",
            status="COMPLETED",
        )
        session.add(batch)
        session.flush()

        source_file = SourceFile(
            id="sf_lineage_test",
            import_batch_id=batch.id,
            original_filename="GL_Transactions_2026_01.xlsx",
            relative_raw_path="uploads/GL_Transactions_2026_01.xlsx",
            sha256="abc123sha256hash",
            byte_size=1024,
            parse_status="PARSED",
        )
        session.add(source_file)
        session.flush()

        account = Account(
            id="acc_lineage_test",
            account_code="1020",
            account_name="Cash Operating Account",
            normalized_name="cash operating account",
            account_type="ASSET",
            currency_code="KES",
        )
        session.add(account)
        session.flush()

        entry = JournalEntry(
            id="je_lineage_test",
            organization_id="default_org",
            import_batch_id=batch.id,
            source_file_id=source_file.id,
            reference="WIRE-UNMATCHED-99",
            description="Large Vendor Wire",
            currency_code="KES",
            fiscal_period="2026-01",
            status="POSTED",
        )
        session.add(entry)
        session.flush()

        line = JournalLine(
            id="jl_lineage_test",
            journal_entry_id=entry.id,
            account_id=account.id,
            debit_amount=Decimal("45000.00"),
            credit_amount=Decimal("0.00"),
            source_row_identifier="Row 42",
            description="Large Vendor Wire",
        )
        session.add(line)
        session.commit()
    finally:
        session.close()

    resp = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "reconciliation",
            "account_code": "1020",
            "period": "2026-01",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "hitl_pending"
    assert len(data["exceptions"]) == 1

    exc = data["exceptions"][0]
    assert exc["id"].startswith("exc_rec_gl_")
    assert "lineage" in exc
    lineage = exc["lineage"]
    assert lineage["found"] is True
    assert lineage["source_row_identifier"] == "Row 42"
    assert lineage["source_file"]["original_filename"] == "GL_Transactions_2026_01.xlsx"
    assert lineage["source_system"]["display_name"] == "Enterprise GL System"

    # Agent 1 findings retain lineage
    assert len(data["agent_1_review"]["findings"]) == 1
    a1_finding = data["agent_1_review"]["findings"][0]
    assert a1_finding["lineage"] == lineage

    # Agent 2 analyses retain lineage
    assert len(data["agent_2_analyses"]) == 1
    a2_analysis = data["agent_2_analyses"][0]
    assert a2_analysis["lineage"] == lineage


# ===========================================================================
# 6. HITL Approval / Rejection Lifecycle & Resumption
# ===========================================================================

def test_canonical_hitl_approval_and_rejection_lifecycle(client, db_session_factory):
    """Workflow pauses at HITL gate with canonical exceptions, persists state, and resumes on human decision."""
    session = db_session_factory()
    try:
        financial_record(
            session,
            id="gl_hitl_1",
            source="GL",
            account_code="1030",
            amount=9900.00,
            reference="HITL-TEST-REF",
            transaction_date=datetime(2026, 1, 25),
        )
        session.commit()
    finally:
        session.close()

    # 1. Trigger workflow -> pauses at hitl_gate
    resp = client.post(
        "/api/v1/reconciliation/run",
        json={
            "workflow_type": "reconciliation",
            "account_code": "1030",
            "period": "2026-01",
        },
    )
    assert resp.status_code == 200
    run_data = resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "hitl_pending"

    # 2. Check pending approvals list
    pending_resp = client.get("/api/v1/approvals/pending")
    assert pending_resp.status_code == 200
    pending_runs = pending_resp.json()
    assert any(r["run_id"] == run_id for r in pending_runs)

    # 3. Submit human approval decision
    resume_resp = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={
            "decision": "approved",
            "reviewer": "Financial Controller",
            "comments": "Variance confirmed with vendor, posting approved.",
        },
    )
    assert resume_resp.status_code == 200
    resumed = resume_resp.json()
    assert resumed["run_id"] == run_id
    assert resumed["status"] == "approved"
    assert resumed["decision"] == "approved"
    assert resumed["reviewer"] == "Financial Controller"

    # 4. Subsequent resume must be rejected with 409 Conflict
    second_resume = client.post(
        f"/api/v1/approvals/{run_id}/decision",
        json={
            "decision": "rejected",
            "reviewer": "Another Reviewer",
        },
    )
    assert second_resume.status_code == 409

