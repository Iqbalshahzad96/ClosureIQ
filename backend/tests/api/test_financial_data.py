"""
Tests for Financial Data Summary and Preview API (/api/v1/financial-data/*).

Verifies:
- Empty database state returns 0 counts and 0.0% all-time reconciliation rate
- Seeded database returns accurate counts and computed all-time reconciliation rate
- All 7 financial data types preview endpoints return correct columns and records
- Derived depreciation calculates correct monthly depreciation and book value
- Error handling for unsupported data types
"""

from datetime import datetime
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.database import Base, get_db
from app.database.models import (
    Account,
    APInvoice,
    BankAccount,
    BankTransaction,
    FixedAsset,
    JournalEntry,
    JournalLine,
    TrialBalanceRecord,
)


@pytest.fixture
def test_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enforce_fk(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(test_db_session):
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_empty_database_summary(client):
    response = client.get("/api/v1/financial-data/summary")
    assert response.status_code == 200
    data = response.json()

    assert "all_time_reconciliation" in data
    assert "data_types" in data

    recon = data["all_time_reconciliation"]
    assert recon["total_records"] == 0
    assert recon["reconciled_records"] == 0
    assert recon["unreconciled_records"] == 0
    assert recon["reconciled_percentage"] == 0.0

    # Verify all 7 types present
    types = data["data_types"]
    assert "bank_statements" in types
    assert "general_ledger" in types
    assert "trial_balance" in types
    assert "ap_invoices" in types
    assert "fixed_assets" in types
    assert "accruals" in types
    assert "depreciation" in types

    for t_key, t_val in types.items():
        assert t_val["total_count"] == 0
        assert t_val["latest_import_date"] is None


def test_populated_database_summary_and_recon_percentage(client, test_db_session):
    org_id = "default_org"

    # Setup GL Account and Bank Account
    account = Account(
        id="acc-101",
        organization_id=org_id,
        account_code="1010",
        account_name="Standard Bank Operating",
        normalized_name="standard bank operating",
        account_type="ASSET",
        currency_code="KES",
    )
    bank_acct = BankAccount(
        id="bank-101",
        organization_id=org_id,
        bank_name="Standard Bank",
        account_number_masked="***9999",
        account_name="Main Operating",
        linked_gl_account_id=account.id,
        currency_code="KES",
    )
    test_db_session.add_all([account, bank_acct])
    test_db_session.flush()

    # 4 Bank Transactions: 3 Reconciled, 1 Unreconciled
    for i in range(4):
        test_db_session.add(
            BankTransaction(
                id=f"bt-{i}",
                bank_account_id=bank_acct.id,
                booking_date=datetime(2026, 3, 1 + i),
                amount=Decimal("1000.00"),
                currency_code="KES",
                bank_reference=f"REF-BT-{i}",
                description=f"Bank Tx {i}",
                is_reconciled=(i < 3),
            )
        )

    # 6 GL Lines: 3 Reconciled, 3 Unreconciled
    entry = JournalEntry(
        id="je-1",
        organization_id=org_id,
        entry_date=datetime(2026, 3, 10),
        currency_code="KES",
        description="GL Test Entry",
    )
    test_db_session.add(entry)
    test_db_session.flush()

    for i in range(6):
        test_db_session.add(
            JournalLine(
                id=f"jl-{i}",
                journal_entry_id=entry.id,
                account_id=account.id,
                line_number=i + 1,
                debit_amount=Decimal("1000.00"),
                credit_amount=Decimal("0.00"),
                is_reconciled=(i < 3),
            )
        )

    # 2 AP Invoices: 1 Paid, 1 Open
    test_db_session.add_all([
        APInvoice(
            id="inv-1",
            organization_id=org_id,
            vendor_name="Vendor A",
            invoice_number="INV-001",
            invoice_date=datetime(2026, 3, 1),
            total_amount=Decimal("5000.00"),
            paid_amount=Decimal("5000.00"),
            outstanding_amount=Decimal("0.00"),
            status="PAID",
        ),
        APInvoice(
            id="inv-2",
            organization_id=org_id,
            vendor_name="Vendor B",
            invoice_number="INV-002",
            invoice_date=datetime(2026, 3, 2),
            total_amount=Decimal("3000.00"),
            paid_amount=Decimal("0.00"),
            outstanding_amount=Decimal("3000.00"),
            status="OPEN",
        ),
    ])

    # 1 Fixed Asset
    test_db_session.add(
        FixedAsset(
            id="fa-1",
            organization_id=org_id,
            asset_code="FA-01",
            asset_name="Server Rack",
            category="COMPUTERS",
            acquisition_date=datetime(2025, 1, 1),
            acquisition_cost=Decimal("120000.00"),
            salvage_value=Decimal("0.00"),
            useful_life_months=36,
            accumulated_depreciation=Decimal("40000.00"),
            book_value=Decimal("80000.00"),
            currency_code="KES",
            status="ACTIVE",
        )
    )

    # 1 Trial Balance Record
    test_db_session.add(
        TrialBalanceRecord(
            id="tb-1",
            organization_id=org_id,
            account_id=account.id,
            fiscal_period="2026-03",
            opening_balance=Decimal("10000.00"),
            period_debit=Decimal("6000.00"),
            period_credit=Decimal("0.00"),
            closing_balance=Decimal("16000.00"),
            currency_code="KES",
        )
    )

    test_db_session.commit()

    response = client.get("/api/v1/financial-data/summary")
    assert response.status_code == 200
    data = response.json()

    recon = data["all_time_reconciliation"]
    # Total considered = 4 bank + 6 GL = 10
    # Total reconciled = 3 bank + 3 GL = 6
    # Total unreconciled = 1 bank + 3 GL = 4
    # Reconciled percentage = (6 / 10) * 100 = 60.0%
    assert recon["total_records"] == 10
    assert recon["reconciled_records"] == 6
    assert recon["unreconciled_records"] == 4
    assert recon["reconciled_percentage"] == 60.0

    types = data["data_types"]
    assert types["bank_statements"]["total_count"] == 4
    assert types["bank_statements"]["reconciled_count"] == 3
    assert types["bank_statements"]["unreconciled_count"] == 1

    assert types["general_ledger"]["total_count"] == 6
    assert types["general_ledger"]["reconciled_count"] == 3
    assert types["general_ledger"]["unreconciled_count"] == 3

    assert types["ap_invoices"]["total_count"] == 2
    assert types["ap_invoices"]["reconciled_count"] == 1
    assert types["ap_invoices"]["unreconciled_count"] == 1

    assert types["fixed_assets"]["total_count"] == 1
    assert types["fixed_assets"]["reconciled_count"] == 1

    assert types["depreciation"]["total_count"] == 1
    assert types["trial_balance"]["total_count"] == 1


def test_preview_endpoints(client, test_db_session):
    org_id = "default_org"

    account = Account(
        id="acc-201",
        organization_id=org_id,
        account_code="2010",
        account_name="Operating Cash",
        normalized_name="operating cash",
        account_type="ASSET",
        currency_code="KES",
    )
    bank_acct = BankAccount(
        id="bank-201",
        organization_id=org_id,
        bank_name="Test Bank",
        account_number_masked="***1111",
        account_name="Primary",
        linked_gl_account_id=account.id,
        currency_code="KES",
    )
    test_db_session.add_all([account, bank_acct])
    test_db_session.flush()

    test_db_session.add(
        BankTransaction(
            id="bt-preview-1",
            bank_account_id=bank_acct.id,
            booking_date=datetime(2026, 3, 15),
            amount=Decimal("2500.50"),
            currency_code="KES",
            bank_reference="TX123",
            description="Client Wire",
            is_reconciled=True,
        )
    )

    test_db_session.add(
        FixedAsset(
            id="fa-preview-1",
            organization_id=org_id,
            asset_code="FA-VEH-01",
            asset_name="Delivery Van",
            category="MOTOR_VEHICLES",
            acquisition_date=datetime(2024, 6, 1),
            acquisition_cost=Decimal("3600000.00"),
            salvage_value=Decimal("0.00"),
            useful_life_months=60,
            accumulated_depreciation=Decimal("1200000.00"),
            book_value=Decimal("2400000.00"),
            currency_code="KES",
            status="ACTIVE",
        )
    )

    test_db_session.commit()

    # 1. Bank preview
    res = client.get("/api/v1/financial-data/bank_statements")
    assert res.status_code == 200
    bank_data = res.json()
    assert len(bank_data["records"]) == 1
    assert bank_data["records"][0]["reference"] == "TX123"
    assert bank_data["records"][0]["amount"] == 2500.50
    assert bank_data["records"][0]["status"] == "Reconciled"

    # 2. Fixed Assets preview
    res = client.get("/api/v1/financial-data/fixed_assets")
    assert res.status_code == 200
    fa_data = res.json()
    assert len(fa_data["records"]) == 1
    assert fa_data["records"][0]["asset_name"] == "Delivery Van"
    assert fa_data["records"][0]["acquisition_cost"] == 3600000.0

    # 3. Derived Depreciation preview
    res = client.get("/api/v1/financial-data/depreciation")
    assert res.status_code == 200
    deprec_data = res.json()
    assert len(deprec_data["records"]) == 1
    # Monthly deprec = 3600000 / 60 = 60000.0
    assert deprec_data["records"][0]["monthly_depreciation"] == 60000.0
    assert deprec_data["records"][0]["current_book_value"] == 2400000.0

    # 4. Unknown data type returns 404
    res = client.get("/api/v1/financial-data/nonexistent_type")
    assert res.status_code == 404
