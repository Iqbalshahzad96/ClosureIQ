"""
Canonical MCP Controlled Data Access Tests for Fixed Assets, AP Invoices, Trial Balance, and Exceptions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import Base
from app.database.models import ExceptionRecord
from tests.canonical_fixtures import (
    ap_invoice_record,
    fixed_asset_record,
    trial_balance_record,
)
from app.mcp.tools import FinancialMCPTools


@pytest.fixture()
def test_session_factory():
    """In-memory SQLite session factory."""
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
def tools(test_session_factory):
    return FinancialMCPTools(session_factory=test_session_factory)


@pytest.fixture()
def seeded_tools(test_session_factory):
    session = test_session_factory()
    try:
        # Fixed assets
        fixed_asset_record(
            session,
            id="fa_1",
            asset_code="FA-100",
            asset_name="Delivery Truck",
            category="VEHICLES",
            acquisition_cost=50000.0,
            salvage_value=5000.0,
            useful_life_months=60,
            status="ACTIVE",
        )
        fixed_asset_record(
            session,
            id="fa_2",
            asset_code="FA-200",
            asset_name="Office Laptop",
            category="COMPUTERS",
            acquisition_cost=2000.0,
            salvage_value=0.0,
            useful_life_months=24,
            status="DISPOSED",
        )

        # AP Invoices
        ap_invoice_record(
            session,
            id="inv_1",
            vendor_name="Acme Corp",
            invoice_number="INV-001",
            subtotal_amount=1000.0,
            tax_amount=160.0,
            total_amount=1160.0,
            status="OPEN",
        )
        ap_invoice_record(
            session,
            id="inv_2",
            vendor_name="Beta Logistics",
            invoice_number="INV-002",
            subtotal_amount=3000.0,
            tax_amount=0.0,
            total_amount=3000.0,
            status="PAID",
        )

        # Trial Balance
        trial_balance_record(
            session,
            id="tb_1",
            account_code="1010",
            account_name="Cash",
            fiscal_period="2026-01",
            closing_balance=15000.0,
        )
        trial_balance_record(
            session,
            id="tb_2",
            account_code="2010",
            account_name="Accounts Payable",
            fiscal_period="2026-01",
            closing_balance=-4160.0,
        )

        # Exceptions
        session.add(
            ExceptionRecord(
                id="exc_001",
                period="2026-01",
                category="AP_REVIEW",
                severity="HIGH",
                amount_variance=1160.0,
                description="Duplicate invoice detected",
                status="OPEN",
            )
        )
        session.commit()
    finally:
        session.close()

    return FinancialMCPTools(session_factory=test_session_factory)


def test_query_fixed_assets(seeded_tools):
    assets = asyncio.run(seeded_tools.query_fixed_assets(limit=10))
    assert len(assets) == 2
    names = [a["asset_name"] for a in assets]
    assert "Delivery Truck" in names
    assert "Office Laptop" in names

    # Filter by category
    vehicles = asyncio.run(seeded_tools.query_fixed_assets(category="VEHICLES"))
    assert len(vehicles) == 1
    assert vehicles[0]["asset_code"] == "FA-100"

    # Filter by status
    active = asyncio.run(seeded_tools.query_fixed_assets(status="ACTIVE"))
    assert len(active) == 1
    assert active[0]["status"] == "ACTIVE"


def test_query_ap_invoices(seeded_tools):
    invoices = asyncio.run(seeded_tools.query_ap_invoices(limit=10))
    assert len(invoices) == 2

    # Filter by vendor
    acme = asyncio.run(seeded_tools.query_ap_invoices(vendor_name="Acme"))
    assert len(acme) == 1
    assert acme[0]["invoice_number"] == "INV-001"

    # Filter by status
    paid = asyncio.run(seeded_tools.query_ap_invoices(status="PAID"))
    assert len(paid) == 1
    assert paid[0]["vendor_name"] == "Beta Logistics"


def test_query_trial_balance(seeded_tools):
    tb = asyncio.run(seeded_tools.query_trial_balance(fiscal_period="2026-01"))
    assert len(tb) == 2
    codes = [r["account_code"] for r in tb]
    assert "1010" in codes
    assert "2010" in codes

    # Filter by account code
    cash_tb = asyncio.run(seeded_tools.query_trial_balance(account_code="1010"))
    assert len(cash_tb) == 1
    assert cash_tb[0]["closing_balance"] == 15000.0


def test_query_exceptions(seeded_tools):
    exceptions = asyncio.run(seeded_tools.query_exceptions(category="AP_REVIEW"))
    assert len(exceptions) == 1
    assert exceptions[0]["id"] == "exc_001"
    assert exceptions[0]["severity"] == "HIGH"


def test_mcp_limit_validation(seeded_tools):
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_fixed_assets(limit=0))

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_ap_invoices(limit=150))


def test_accounts_and_periods(seeded_tools, test_session_factory):
    from app.database.models import Account, JournalEntry
    with test_session_factory.begin() as session:
        session.add(Account(account_code="hidden", account_name="hidden", normalized_name="hidden", account_type="ASSET",
                            organization_id="other"))
        session.add(JournalEntry(id="journal_only", fiscal_period="2026-02", entry_type="PAYMENT"))
        session.add(JournalEntry(id="foreign", fiscal_period="2099-01", organization_id="other"))
    accounts = asyncio.run(seeded_tools.query_chart_of_accounts(account_type=" asset ", is_active=True))
    assert {account["account_code"] for account in accounts} == {"1010", "2010"}
    assert asyncio.run(seeded_tools.query_chart_of_accounts(is_active=False)) == []
    periods = asyncio.run(seeded_tools.query_accounting_periods())
    assert [period["fiscal_period"] for period in periods] == ["2026-02", "2026-01"]
    assert [period["record_count"] for period in periods] == [0, 2]
    entries = asyncio.run(seeded_tools.query_journal_entries(fiscal_period=" 2026-02 ", entry_type="payment"))
    assert [entry["id"] for entry in entries] == ["journal_only"]
    assert asyncio.run(seeded_tools.query_journal_entries(fiscal_period="2026-01")) == []


def test_balance_fallback_filters_status_period_currency_and_tenant(tools, test_session_factory):
    from app.database.models import Account, JournalEntry, JournalLine
    with test_session_factory.begin() as session:
        account = Account(id="credit", account_code="2000", account_name="Payable", normalized_name="payable",
                          account_type="LIABILITY", normal_balance="CREDIT")
        session.add(account)
        for index, (period, status, currency, org, amount) in enumerate([
            ("2026-01", "POSTED", "KES", "default_org", "0.1001"),
            ("2026-01", "POSTED", "KES", "default_org", "0.2002"),
            ("2026-02", "POSTED", "KES", "default_org", "100"),
            ("2026-01", "DRAFT", "KES", "default_org", "100"),
            ("2026-01", "REVERSED", "KES", "default_org", "100"),
            ("2026-01", "POSTED", "USD", "default_org", "100"),
            ("2026-01", "POSTED", "KES", "other", "100"),
        ]):
            session.add(JournalEntry(id=f"entry{index}", fiscal_period=period, status=status,
                                     currency_code=currency, organization_id=org))
            session.flush()
            session.add(JournalLine(id=f"line{index}", journal_entry_id=f"entry{index}",
                                    account_id=account.id, credit_amount=amount))
    balance = asyncio.run(tools.get_account_balance("2000", " 2026-01 "))
    assert balance["found"] is True
    assert balance["exact_amounts"]["net_movement"] == "0.3003"
    assert balance["opening_balance"] is None and balance["closing_balance"] is None
    assert balance["journal_line_ids"] == ["line0", "line1"]
    assert asyncio.run(tools.get_account_balance("2000", "missing"))["found"] is False
    gl = asyncio.run(tools.query_gl_transactions("2000", fiscal_period="2026-02"))
    assert [line["id"] for line in gl] == ["line2"]


def test_zero_value_posting_is_found(tools, test_session_factory):
    from tests.canonical_fixtures import financial_record
    with test_session_factory.begin() as session:
        line = financial_record(session, id="zero", source="GL", account_code="1000", amount=0)
        line.journal_entry.fiscal_period = "2026-01"
    assert asyncio.run(tools.get_account_balance("1000", "2026-01"))["found"] is True


@pytest.fixture()
def lineage_tools(test_session_factory):
    from app.database.models import SourceSystem, ImportBatch, SourceFile
    from tests.canonical_fixtures import financial_record
    with test_session_factory.begin() as session:
        session.add(SourceSystem(id="source", adapter_key="generic", source_type="ERP", display_name="Fixture"))
        session.flush()
        session.add(ImportBatch(id="batch", source_system_id="source", status="COMPLETED", file_count=1))
        session.flush()
        session.add(SourceFile(id="file", import_batch_id="batch", original_filename="input.csv",
                               relative_raw_path="raw/input.csv", sha256="a" * 64, byte_size=100))
        session.flush()
        line = financial_record(session, id="line", source="GL", account_code="1000", amount=100)
        line.source_row_identifier = "row:2"
        line.dimensions_json = {"Is Bank Reconciliated": True}
        line.journal_entry.import_batch_id = "batch"
        line.journal_entry.source_file_id = "file"
        bank = financial_record(session, id="bank", source="BANK", account_code="1000", amount=100)
        bank.import_batch_id = "batch"
        bank.source_row_identifier = "row:3"
        for record in (ap_invoice_record(session), fixed_asset_record(session), trial_balance_record(session)):
            record.import_batch_id = "batch"
    return FinancialMCPTools(test_session_factory)


@pytest.mark.parametrize("kind,record_id", [("JOURNAL_ENTRY", "entry_line"), ("JOURNAL_LINE", "line"),
    ("BANK_TRANSACTION", "bank"), ("AP_INVOICE", "inv_001"), ("FIXED_ASSET", "fa_001"),
    ("TRIAL_BALANCE", "tb_001")])
def test_lineage_and_tenant_isolation(lineage_tools, test_session_factory, kind, record_id):
    import json
    lineage = asyncio.run(lineage_tools.get_record_lineage(kind, record_id))
    assert lineage["found"] is True
    assert lineage["import_batch"]["id"] == "batch"
    assert lineage["source_system"]["id"] == "source"
    assert lineage["batch_source_files"][0]["sha256"] == "a" * 64
    if kind.startswith("JOURNAL"):
        assert lineage["source_file"]["id"] == "file"
    else:
        assert "source_file" not in lineage  # Batch provenance is not row provenance.
    if kind == "JOURNAL_LINE":
        assert lineage["source_row_identifier"] == "row:2"
        assert asyncio.run(lineage_tools.query_gl_transactions("1000"))[0]["is_reconciled"] is False
    foreign = FinancialMCPTools(test_session_factory, organization_id="other")
    assert asyncio.run(foreign.get_record_lineage(kind, record_id))["found"] is False
    assert asyncio.run(lineage_tools.get_record_lineage(kind, "missing"))["found"] is False
    json.dumps(lineage)


def test_import_batches(lineage_tools, test_session_factory):
    from app.database.models import ImportBatch
    with test_session_factory.begin() as session:
        session.add(ImportBatch(id="foreign", source_system_id="source", organization_id="other", status="COMPLETED"))
    assert [batch["id"] for batch in asyncio.run(lineage_tools.query_import_batches(status=" completed "))] == ["batch"]
    assert asyncio.run(lineage_tools.query_import_batches(status="FAILED")) == []


@pytest.mark.parametrize("method", ["query_chart_of_accounts", "query_journal_entries", "query_import_batches"])
def test_new_query_limits(tools, method):
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(getattr(tools, method)(limit=0))


def test_balance_prefers_latest_snapshot_without_summing_imports(tools, test_session_factory):
    with test_session_factory.begin() as session:
        old = trial_balance_record(session, id="old", closing_balance=100)
        old.created_at = datetime(2026, 1, 1)
        new = trial_balance_record(session, id="new", closing_balance="200.1234")
        new.created_at = datetime(2026, 1, 2)
        foreign_currency = trial_balance_record(session, id="usd", closing_balance=999, currency_code="USD")
        foreign_currency.created_at = datetime(2026, 1, 3)
    result = asyncio.run(tools.get_account_balance("1010", "2026-01"))
    assert result["record_id"] == "new"
    assert result["exact_amounts"]["closing_balance"] == "200.1234"
    assert result["balance_basis"] == "CANONICAL_SNAPSHOT"


@pytest.mark.parametrize("kind,record_id", [("JOURNAL_ENTRY", "entry_line"),
    ("BANK_TRANSACTION", "bank"), ("AP_INVOICE", "inv_001"), ("FIXED_ASSET", "fa_001"),
    ("TRIAL_BALANCE", "tb_001")])
def test_lineage_resolves_existing_ingestion_audit_evidence(lineage_tools, test_session_factory, kind, record_id):
    from app.database.models import AuditEvent
    with test_session_factory.begin() as session:
        session.add(AuditEvent(id="audit", import_batch_id="batch", event_type="INGEST_IMPORTED",
            details={"entity_type": kind, "record_id": record_id, "source_file_id": "file",
                     "source_row_identifier": "Sheet1:R5", "lineage": {"source_flag": True}}))
        session.add(AuditEvent(id="foreign_audit", organization_id="other", import_batch_id="batch",
            event_type="INGEST_IMPORTED", details={"entity_type": kind, "record_id": record_id,
                "source_file_id": "file", "source_row_identifier": "private"}))
    lineage = asyncio.run(lineage_tools.get_record_lineage(kind, record_id))
    assert lineage["source_file"]["id"] == "file"
    assert [item["audit_event_id"] for item in lineage["ingestion_evidence"]] == ["audit"]
    assert lineage["ingestion_evidence"][0]["source_row_identifier"] == "Sheet1:R5"
    assert lineage["ingestion_evidence"][0]["source_metadata"] == {"source_flag": True}
    if kind != "BANK_TRANSACTION":
        assert lineage["source_row_identifier"] == "Sheet1:R5"
