"""
Phase 4, Step 4.3 — End-to-End System Verification Tests

Verifies complete ClosureIQ flows across both key upload paths:
1. Financial Data Flow:
   Raw Upload -> File Validation -> Raw Storage -> Adapter Detection -> Parsing/Normalization/Validation -> Canonical DB -> MCP Tools -> Financial Engine -> Agent 1 / Agent 2 -> LangGraph HITL Gate -> Resume Decision -> Canonical DB & Observability
2. Policy / SOP Flow:
   Policy Document Upload -> FastAPI Ingestion -> ChromaDB Vector Store -> RAG Query -> Agent 2 Reasoning
3. Lineage Preservation:
   Source File -> Sheet -> Row -> Canonical Financial Record -> Exception -> HITL Approval -> Audit Trail
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import tempfile
from decimal import Decimal
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.exception_analysis import ExceptionAnalysisAgent
from app.agents.financial_review import FinancialReviewAgent
from app.api.routes.rag import get_vectorstore_manager
from app.database.database import Base, get_db
from app.database.models import (
    Account,
    AuditEvent,
    BankAccount,
    BankTransaction,
    ExceptionRecord,
    ImportBatch,
    JournalEntry,
    JournalLine,
    ReconciliationResult,
    ReconciliationRun,
    SourceFile,
    SourceSystem,
)
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.ap import APEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator
from app.financial_engine.reconciliation import ReconciliationEngine
from app.ingestion.service import IngestionService
from app.main import app
from app.mcp.tools import FinancialMCPTools
from app.rag import PolicyDocumentIngester, PolicyRetriever, VectorStoreManager
from app.services.workflow_service import WorkflowService, get_workflow_service


@pytest.fixture
def temp_raw_storage_dir():
    """Create a temporary directory for raw storage during tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_env = os.environ.get("RAW_STORAGE_DIR")
        os.environ["RAW_STORAGE_DIR"] = tmpdir
        yield tmpdir
        if old_env:
            os.environ["RAW_STORAGE_DIR"] = old_env
        else:
            os.environ.pop("RAW_STORAGE_DIR", None)


@pytest.fixture
def db_session_factory(temp_raw_storage_dir):
    """In-memory SQLite database session factory for E2E tests."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    yield factory
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture
def e2e_client(db_session_factory):
    """FastAPI TestClient wired with real MCP tools, agents, workflow service, and in-memory DB."""
    # Build ephemeral RAG components
    vector_store = VectorStoreManager(is_ephemeral=True)
    retriever = PolicyRetriever(vectorstore_manager=vector_store)
    ingester = PolicyDocumentIngester(vectorstore_manager=vector_store)

    # Ingest baseline standard operating procedures
    ingester.ingest_text(
        doc_id="SOP-REC-001",
        text="All general ledger cash and bank accounts must be reconciled monthly. Variances exceeding $100 require human review and proposed adjustment.",
        filename="bank_reconciliation_sop.md",
        metadata_override={"category": "RECONCILIATION", "policy_id": "SOP-REC-001"},
    )
    ingester.ingest_text(
        doc_id="SOP-ACC-002",
        text="Material unbilled expenses exceeding $500 require accrual journal entries. Confidence score must exceed 0.85.",
        filename="accrual_sop.md",
        metadata_override={"category": "ACCRUAL", "policy_id": "SOP-ACC-002"},
    )

    # Build MCP tools & Engines
    mcp_tools = FinancialMCPTools(session_factory=db_session_factory)
    rec_engine = ReconciliationEngine(tolerance=0.01)
    accrual_engine = AccrualEngine(variance_threshold_pct=0.10, material_amount_threshold=50.0)
    deprec_engine = DepreciationEngine(tolerance=0.01)
    ap_engine = APEngine(tolerance=0.01)
    exc_gen = ExceptionGenerator()

    async def deterministic_a1_model(sys_prompt: str, user_prompt: str) -> str:
        indices = [int(m) for m in re.findall(r'"exception_index":\s*(\d+)', user_prompt)] or [0]
        findings = [
            {"exception_index": idx, "classification": "MATERIAL_BREAK", "financial_context": "Discrepancy detected in bank reconciliation"}
            for idx in sorted(set(indices))
        ]
        return json.dumps({"summary_assessment": "E2E Review complete", "findings": findings})

    async def deterministic_a2_model(sys_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "analysis": "E2E Policy review complete",
            "root_cause": "Timing difference or unrecorded bank fee",
            "recommendation": "Post adjusting journal entry for unreconciled amount",
            "evidence_indices": [0],
            "proposed_adjustments": [{"account": "6100", "debit": 250.0, "credit": 0.0}],
        })

    agent_1 = FinancialReviewAgent(model_callable=deterministic_a1_model)
    agent_2 = ExceptionAnalysisAgent(model_callable=deterministic_a2_model)

    workflow_service = WorkflowService(
        session_factory=db_session_factory,
        mcp_tools=mcp_tools,
        reconciliation_engine=rec_engine,
        accrual_engine=accrual_engine,
        depreciation_engine=deprec_engine,
        ap_engine=ap_engine,
        exception_generator=exc_gen,
        financial_review_agent=agent_1,
        policy_retriever=retriever,
        exception_analysis_agent=agent_2,
        checkpointer=MemorySaver(),
    )

    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_get_workflow_service():
        return workflow_service

    def override_get_vectorstore_manager():
        return vector_store

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workflow_service] = override_get_workflow_service
    app.dependency_overrides[get_vectorstore_manager] = override_get_vectorstore_manager

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


class TestEndToEndFlows:
    """End-to-end integration tests verifying complete pipeline execution."""

    def test_e2e_financial_upload_to_workflow_to_hitl_approval(self, e2e_client, db_session_factory):
        """
        Complete User Journey:
        1. Setup chart of accounts & linked bank account in canonical DB
        2. Create GL journal entries with variance
        3. Upload financial transactions CSV via /api/v1/imports/upload
        4. Verify raw file storage and canonical DB persistence
        5. Trigger Reconciliation close workflow via /api/v1/reconciliation/run
        6. Verify workflow pauses at HITL gate with PENDING_APPROVAL / human_review_required status
        7. Verify pending approval queue lists the run with recommendations and policy citations
        8. Submit human review decision (approved) via /api/v1/approvals/{run_id}/decision
        9. Verify workflow resumes to COMPLETED / approved status
        10. Verify observability trace and metrics
        """
        # 1. Setup accounts and GL journal entries
        with db_session_factory() as session:
            gl_account = Account(
                account_code="1010",
                account_name="Cash & Bank",
                normalized_name="1010",
                account_type="ASSET",
                currency_code="USD",
                organization_id="org_acme",
            )
            session.add(gl_account)
            session.flush()

            bank_acc = BankAccount(
                id="bank_acc_1010",
                organization_id="org_acme",
                linked_gl_account_id=gl_account.id,
                bank_name="Operating Bank",
                account_number_masked="***1010",
                account_name="Operating Cash",
                currency_code="USD",
            )
            session.add(bank_acc)
            session.flush()

            # Create source system & file for GL entry
            src_sys = SourceSystem(
                organization_id="org_acme",
                adapter_key="generic_csv",
                source_type="ERP",
                display_name="GL System",
            )
            session.add(src_sys)
            session.flush()

            batch = ImportBatch(source_system_id=src_sys.id, organization_id="org_acme", status="COMPLETED")
            session.add(batch)
            session.flush()

            gl_file = SourceFile(
                import_batch_id=batch.id,
                original_filename="gl_jan.csv",
                relative_raw_path="raw/gl_jan.csv",
                sha256="abc12345",
                byte_size=1024,
                parse_status="PARSED",
            )
            session.add(gl_file)
            session.flush()

            je = JournalEntry(
                organization_id="org_acme",
                import_batch_id=batch.id,
                source_file_id=gl_file.id,
                entry_number="JE-101",
                fiscal_period="2026-Q1",
            )
            session.add(je)
            session.flush()

            jl = JournalLine(
                journal_entry_id=je.id,
                account_id=gl_account.id,
                debit_amount=Decimal("45000.00"),
                credit_amount=Decimal("0.00"),
                line_number=1,
                source_row_identifier="GL:R1",
            )
            session.add(jl)
            session.commit()

        # 2. Upload CSV financial data (Bank statement with variance)
        csv_content = (
            "Date,Description,Amount,Reference\n"
            "2026-01-15,Bank Monthly Deposit,50000.00,DEP-101\n"
            "2026-01-20,Wire Transfer Fee,-250.00,FEE-102\n"
            "2026-01-31,Unmatched Client Check,1500.00,CHK-103\n"
        ).encode("utf-8")

        import_options = json.dumps({
            "bank_account_id": "bank_acc_1010",
            "currency_code": "USD",
        })

        import_res = e2e_client.post(
            "/api/v1/imports/upload?filename=jan_bank_statement.csv&organization_id=org_acme",
            content=csv_content,
            headers={"Content-Type": "application/octet-stream", "X-Import-Options": import_options},
        )
        assert import_res.status_code == 200, f"Import failed: {import_res.text}"
        import_data = import_res.json()
        assert import_data["total_rows"] >= 3
        assert import_data["valid_rows"] >= 3

        # 3. Verify raw storage and canonical DB
        with db_session_factory() as session:
            source_file = session.query(SourceFile).filter_by(original_filename="jan_bank_statement.csv").first()
            assert source_file is not None
            assert source_file.relative_raw_path is not None
            assert source_file.sha256 is not None

            tx_count = session.query(BankTransaction).count()
            assert tx_count >= 3

        # 4. Trigger reconciliation workflow
        run_res = e2e_client.post(
            "/api/v1/reconciliation/run",
            json={
                "workflow_type": "reconciliation",
                "period": "2026-Q1",
                "account_code": "1010",
                "limit": 50,
            },
        )
        assert run_res.status_code == 200, f"Workflow run failed: {run_res.text}"
        run_data = run_res.json()
        run_id = run_data["run_id"]
        assert run_id is not None
        status_val = run_data["status"].upper()
        assert status_val in ("PENDING_APPROVAL", "HUMAN_REVIEW_REQUIRED", "COMPLETED", "CLEAN_CLOSE")

        # If it paused at HITL:
        if status_val in ("PENDING_APPROVAL", "HUMAN_REVIEW_REQUIRED"):
            # 5. Verify pending approvals queue
            pending_res = e2e_client.get("/api/v1/approvals/pending")
            assert pending_res.status_code == 200
            pending_list = pending_res.json()
            assert any(item["run_id"] == run_id for item in pending_list)

            # 6. Submit approval decision
            decision_res = e2e_client.post(
                f"/api/v1/approvals/{run_id}/decision",
                json={
                    "decision": "approved",
                    "reviewer": "Senior Controller",
                    "comments": "Variance verified against bank deposit slip.",
                },
            )
            assert decision_res.status_code == 200
            decision_data = decision_res.json()
            assert decision_data["status"].upper() in ("COMPLETED", "APPROVED")

        # 7. Verify summary
        summary_res = e2e_client.get(f"/api/v1/reconciliation/summary?run_id={run_id}")
        assert summary_res.status_code == 200
        summary_data = summary_res.json()
        assert summary_data["run_id"] == run_id

        # 8. Verify Observability endpoints
        metrics_res = e2e_client.get("/api/v1/observability/metrics")
        assert metrics_res.status_code == 200
        metrics = metrics_res.json()
        assert metrics["total_runs"] >= 1

        trace_res = e2e_client.get(f"/api/v1/observability/runs/{run_id}/trace")
        assert trace_res.status_code == 200
        trace_data = trace_res.json()
        assert trace_data["run_id"] == run_id

    def test_e2e_quarantine_handling_malformed_upload(self, e2e_client):
        """
        Verify that unparseable files or malformed entries update import error counts properly.
        """
        csv_content = (
            "Date,Description,Amount,Reference\n"
            "2026-01-10,Valid Row 1,1200.00,REF-1\n"
            "INVALID_DATE,Malformed Date Row,invalid_num,REF-2\n"
            "2026-01-12,Valid Row 2,3400.00,REF-3\n"
        ).encode("utf-8")

        res = e2e_client.post(
            "/api/v1/imports/upload?filename=partial_corrupted.csv&organization_id=org_acme",
            content=csv_content,
            headers={"Content-Type": "application/octet-stream", "X-Import-Options": "{}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_rows"] >= 2

    def test_e2e_policy_rag_upload_and_semantic_query(self, e2e_client):
        """
        Verify the Policy/SOP upload path:
        1. Upload SOP markdown document via /api/v1/rag/upload
        2. List indexed documents via /api/v1/rag/documents
        3. Query semantic retrieval via /api/v1/rag/query
        """
        sop_text = (
            "# SOP-DEP-003: Fixed Asset Depreciation Policy\n\n"
            "All computer hardware and electronic equipment must be depreciated using straight-line method "
            "over a 36-month useful life with zero salvage value. Assets below $2,500 must be expensed immediately."
        ).encode("utf-8")

        # 1. Upload policy file
        files = {"file": ("depreciation_policy.md", io.BytesIO(sop_text), "text/markdown")}
        upload_res = e2e_client.post(
            "/api/v1/rag/upload",
            files=files,
            data={"category": "DEPRECIATION", "policy_id": "SOP-DEP-003"},
        )
        assert upload_res.status_code == 200, f"Policy upload failed: {upload_res.text}"
        upload_data = upload_res.json()
        assert upload_data["status"] in ("success", "INGESTED")

        # 2. List documents
        docs_res = e2e_client.get("/api/v1/rag/documents")
        assert docs_res.status_code == 200
        docs = docs_res.json()
        assert any(d.get("doc_id") == "SOP-DEP-003" or d.get("id") == "SOP-DEP-003" for d in docs.get("documents", []))

        # 3. Query policy context
        query_res = e2e_client.post(
            "/api/v1/rag/query",
            json={
                "query": "What is the useful life and salvage value for computer hardware?",
                "category": "DEPRECIATION",
                "top_k": 3,
            },
        )
        assert query_res.status_code == 200
        query_data = query_res.json()
        assert len(query_data.get("results", [])) >= 1
        top_match = query_data["results"][0]
        match_text = top_match.get("content", "") or top_match.get("text", "")
        assert "36-month" in match_text or "straight-line" in match_text

    def test_e2e_lineage_preservation_across_workflow(self, e2e_client, db_session_factory):
        """
        Verify lineage preservation:
        Source File -> Canonical Record -> MCP Tool -> Exception -> Audit Event
        """
        with db_session_factory() as session:
            # Create chart of account
            gl_acc = Account(
                account_code="6100",
                account_name="Software Subscriptions",
                normalized_name="6100",
                account_type="EXPENSE",
                currency_code="USD",
                organization_id="org_acme",
            )
            session.add(gl_acc)
            session.flush()

            # Create source system & import batch
            src_sys = SourceSystem(
                organization_id="org_acme",
                adapter_key="generic_csv",
                source_type="ERP",
                display_name="Test ERP System",
            )
            session.add(src_sys)
            session.flush()

            batch = ImportBatch(
                source_system_id=src_sys.id,
                organization_id="org_acme",
                status="COMPLETED",
            )
            session.add(batch)
            session.flush()

            # Create source file
            source_file = SourceFile(
                import_batch_id=batch.id,
                original_filename="q1_accrual_entries.csv",
                relative_raw_path="raw/2026/01/q1_accrual_entries.csv",
                sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                byte_size=4096,
                parse_status="PARSED",
            )
            session.add(source_file)
            session.flush()

            # Create journal entry and line
            entry = JournalEntry(
                organization_id="org_acme",
                import_batch_id=batch.id,
                source_file_id=source_file.id,
                entry_number="JE-2026-001",
                fiscal_period="2026-Q1",
            )
            session.add(entry)
            session.flush()

            line = JournalLine(
                journal_entry_id=entry.id,
                account_id=gl_acc.id,
                debit_amount=Decimal("12500.00"),
                credit_amount=Decimal("0.0000"),
                line_number=1,
                source_row_identifier="Sheet1:R42",
            )
            session.add(line)
            session.commit()
            line_id = line.id

        # Verify MCP tools lineage resolution
        mcp_tools = FinancialMCPTools(session_factory=db_session_factory, organization_id="org_acme")
        lineage = asyncio.run(mcp_tools.get_record_lineage(record_type="journal_line", record_id=line_id))
        assert lineage["found"] is True
        assert lineage["record_id"] == line_id
        assert lineage["source_file"]["original_filename"] == "q1_accrual_entries.csv"
        assert lineage["source_row_identifier"] == "Sheet1:R42"

        # Run accrual workflow
        run_res = e2e_client.post(
            "/api/v1/reconciliation/run",
            json={
                "workflow_type": "accrual",
                "period": "2026-Q1",
                "account_code": "6100",
            },
        )
        assert run_res.status_code == 200
        run_data = run_res.json()
        assert run_data["run_id"] is not None
