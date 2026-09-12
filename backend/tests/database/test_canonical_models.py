"""
Unit Tests for Generic Canonical Financial Database Models.

Covers:
- Table creation and schema reflection
- UUID primary key auto-generation
- Monetary Decimal/Numeric precision (never Float)
- Missing transaction date safety (never defaulting to current date)
- Complete FixedAsset lifecycle (in_service_date, disposal_date, currency, constraints)
- Generalized ReconciliationResult (bank recon, accrual review, depreciation validation)
- Primary linking of ExceptionRecord through reconciliation_result_id
- Entity relationships, foreign keys, cascades, and lineage
- Scoping (organization_id, source_system_id)
- Backward compatibility (FinancialRecord, ExceptionRecord, AuditTrailRecord)
"""

from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.database import Base
from app.database.models import (
    APInvoice,
    Account,
    AuditEvent,
    AuditTrailRecord,
    BankAccount,
    BankTransaction,
    ExceptionRecord,
    FinancialRecord,
    FixedAsset,
    ImportBatch,
    JournalEntry,
    JournalLine,
    ReconciliationResult,
    ReconciliationRun,
    SourceAccountMapping,
    SourceFile,
    SourceSystem,
    TrialBalanceRecord,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database session fixture with fresh schema."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_schema_table_creation(db_session):
    """Verify all 16 canonical tables and legacy tables are registered and created."""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {
        "source_systems",
        "import_batches",
        "source_files",
        "accounts",
        "source_account_mappings",
        "journal_entries",
        "journal_lines",
        "trial_balance_records",
        "bank_accounts",
        "bank_transactions",
        "ap_invoices",
        "fixed_assets",
        "reconciliation_runs",
        "reconciliation_results",
        "exception_records",
        "audit_events",
        "financial_records",
    }
    assert expected_tables.issubset(table_names), f"Missing tables: {expected_tables - table_names}"


def test_uuid_primary_key_generation(db_session):
    """Verify primary keys are automatically generated as unique UUID strings."""
    src1 = SourceSystem(
        adapter_key="enquest_adapter",
        source_type="ERP",
        display_name="Enquest ERP Main",
    )
    src2 = SourceSystem(
        adapter_key="bank_feeder",
        source_type="BANK",
        display_name="Corporate Bank Feeder",
    )
    db_session.add_all([src1, src2])
    db_session.commit()

    assert src1.id is not None
    assert src2.id is not None
    assert len(src1.id) == 36
    assert src1.id != src2.id


def test_monetary_decimal_precision(db_session):
    """Verify monetary amounts use exact Decimal values without float roundoff errors."""
    account = Account(
        account_name="Cash and Equivalents",
        normalized_name="cash_and_equivalents",
        account_type="ASSET",
        normal_balance="DEBIT",
        currency_code="KES",
    )
    db_session.add(account)
    db_session.flush()

    entry = JournalEntry(
        entry_type="JOURNAL",
        fiscal_period="2025-01",
        currency_code="KES",
    )
    db_session.add(entry)
    db_session.flush()

    exact_debit = Decimal("12345678.8765")
    exact_credit = Decimal("0.0000")

    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=account.id,
        line_number=1,
        debit_amount=exact_debit,
        credit_amount=exact_credit,
    )
    db_session.add(line)
    db_session.commit()

    saved_line = db_session.get(JournalLine, line.id)
    assert isinstance(saved_line.debit_amount, Decimal)
    assert saved_line.debit_amount == Decimal("12345678.8765")
    # Verify precision is not lost to binary float approximation
    assert str(saved_line.debit_amount) == "12345678.8765"


def test_missing_transaction_dates_do_not_default_to_current_date(db_session):
    """Verify transaction dates are strictly nullable and NEVER default to datetime.utcnow."""
    entry = JournalEntry(
        entry_type="JOURNAL",
        fiscal_period="2025-01",
    )
    tx = BankTransaction(
        bank_account_id="dummy_bank_acc",
        amount=Decimal("5000.00"),
    )
    invoice = APInvoice(
        vendor_name="Acme Corp",
        invoice_number="INV-001",
        total_amount=Decimal("1500.00"),
    )
    asset = FixedAsset(
        asset_name="Dell Server",
        category="COMPUTERS",
        acquisition_cost=Decimal("250000.00"),
    )

    assert entry.entry_date is None
    assert entry.posting_date is None
    assert tx.booking_date is None
    assert tx.value_date is None
    assert invoice.invoice_date is None
    assert invoice.due_date is None
    assert asset.acquisition_date is None
    assert asset.in_service_date is None
    assert asset.disposal_date is None


def test_source_system_and_lineage_relationships(db_session):
    """Verify hierarchy: SourceSystem -> ImportBatch -> SourceFile."""
    src = SourceSystem(
        organization_id="org_kenya_ops",
        adapter_key="enquest_adapter",
        source_type="ERP",
        display_name="Enquest ERP",
    )
    db_session.add(src)
    db_session.flush()

    batch = ImportBatch(
        source_system_id=src.id,
        organization_id="org_kenya_ops",
        status="PROCESSING",
        file_count=1,
    )
    db_session.add(batch)
    db_session.flush()

    src_file = SourceFile(
        import_batch_id=batch.id,
        original_filename="DIAMOND TRUST BANK KSHS.xls",
        relative_raw_path="data/raw/enquest/bank_gl/DIAMOND TRUST BANK KSHS.xls",
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        byte_size=5954,
        media_type="application/vnd.ms-excel",
        parse_status="PARSED",
    )
    db_session.add(src_file)
    db_session.commit()

    queried_src = db_session.get(SourceSystem, src.id)
    assert len(queried_src.import_batches) == 1
    assert queried_src.import_batches[0].id == batch.id
    assert len(queried_src.import_batches[0].source_files) == 1
    assert queried_src.import_batches[0].source_files[0].original_filename == "DIAMOND TRUST BANK KSHS.xls"


def test_chart_of_accounts_and_journal_entries(db_session):
    """Verify Account, SourceAccountMapping, JournalEntry, and multi-line JournalLine integrity."""
    src = SourceSystem(
        adapter_key="enquest_adapter",
        source_type="ERP",
        display_name="Enquest ERP",
    )
    db_session.add(src)
    db_session.flush()

    acc_bank = Account(
        account_code="1010",
        account_name="Diamond Trust Bank KSHS",
        normalized_name="diamond_trust_bank_kshs",
        account_type="ASSET",
        normal_balance="DEBIT",
    )
    acc_sales = Account(
        account_code="4010",
        account_name="Sales Revenue",
        normalized_name="sales_revenue",
        account_type="REVENUE",
        normal_balance="CREDIT",
    )
    db_session.add_all([acc_bank, acc_sales])
    db_session.flush()

    mapping = SourceAccountMapping(
        source_system_id=src.id,
        source_account_key="LEDGERS/CURRENT ASSETS/BANK ACCOUNTS/DIAMOND TRUST BANK KSHS.xls",
        account_id=acc_bank.id,
        raw_account_name="DIAMOND TRUST BANK KSHS",
        mapping_status="REVIEWED",
    )
    db_session.add(mapping)

    entry = JournalEntry(
        external_entry_id="VOUCHER-2025-001",
        entry_type="RECEIPT",
        entry_date=datetime(2025, 1, 4, 10, 0, 0),
        posting_date=datetime(2025, 1, 4, 10, 0, 0),
        fiscal_period="2025-01",
        description="Customer cash receipt",
        currency_code="KES",
    )
    db_session.add(entry)
    db_session.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=acc_bank.id,
        line_number=1,
        debit_amount=Decimal("50000.00"),
        credit_amount=Decimal("0.00"),
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=acc_sales.id,
        line_number=2,
        debit_amount=Decimal("0.00"),
        credit_amount=Decimal("50000.00"),
    )
    db_session.add_all([line1, line2])
    db_session.commit()

    saved_entry = db_session.get(JournalEntry, entry.id)
    assert len(saved_entry.lines) == 2
    total_debits = sum(line.debit_amount for line in saved_entry.lines)
    total_credits = sum(line.credit_amount for line in saved_entry.lines)
    assert total_debits == total_credits == Decimal("50000.00")
    assert saved_entry.entry_date == datetime(2025, 1, 4, 10, 0, 0)


def test_bank_and_reconciliation_flow(db_session):
    """Verify BankAccount, BankTransaction, ReconciliationRun, ReconciliationResult, and ExceptionRecord."""
    bank_acc = BankAccount(
        bank_name="Diamond Trust Bank",
        account_number_masked="****1234",
        account_name="DTB Operations KES",
        currency_code="KES",
    )
    db_session.add(bank_acc)
    db_session.flush()

    bank_tx = BankTransaction(
        bank_account_id=bank_acc.id,
        booking_date=datetime(2025, 1, 5, 0, 0, 0),
        amount=Decimal("150000.00"),
        bank_reference="FT25005001",
        description="Wire Deposit from Client",
    )
    db_session.add(bank_tx)
    db_session.flush()

    run = ReconciliationRun(
        run_type="GL_BANK_RECONCILIATION",
        fiscal_period="2025-01",
        tolerance_amount=Decimal("0.00"),
        date_window_days=5,
        status="IN_PROGRESS",
    )
    db_session.add(run)
    db_session.flush()

    result = ReconciliationResult(
        run_id=run.id,
        result_type="BANK_RECONCILIATION",
        bank_transaction_id=bank_tx.id,
        expected_amount=Decimal("150000.00"),
        actual_amount=Decimal("0.00"),
        variance=Decimal("150000.00"),
        status="UNMATCHED",
        result_status="UNMATCHED_BANK",
        amount_difference=Decimal("150000.00"),
        confidence=Decimal("0.0000"),
    )
    db_session.add(result)
    db_session.flush()

    # Link ExceptionRecord primarily through reconciliation_result_id
    exc = ExceptionRecord(
        reconciliation_result_id=result.id,
        run_id=run.id,
        bank_transaction_id=bank_tx.id,
        period="2025-01",
        category="RECONCILIATION",
        severity="HIGH",
        amount_variance=Decimal("150000.00"),
        description="Unmatched deposit on bank statement",
        status="OPEN",
    )
    db_session.add(exc)

    audit = AuditEvent(
        run_id=run.id,
        exception_id=exc.id,
        event_type="EXCEPTION_RAISED",
        actor="reconciliation_agent",
        details={"reason": "No matching GL posting found within date window"},
    )
    db_session.add(audit)
    db_session.commit()

    saved_run = db_session.get(ReconciliationRun, run.id)
    assert len(saved_run.results) == 1
    assert len(saved_run.exceptions) == 1
    assert len(saved_run.audit_events) == 1

    saved_result = db_session.get(ReconciliationResult, result.id)
    assert len(saved_result.exceptions) == 1
    assert saved_result.exceptions[0].id == exc.id
    assert saved_result.exceptions[0].amount_variance == Decimal("150000.00")


def test_generalized_reconciliation_results(db_session):
    """
    Verify generalized ReconciliationResult for:
    1. Accrual Review (linking APInvoice + GL line)
    2. Depreciation Validation (linking FixedAsset + GL line)
    """
    # 1. Accounts & setup
    expense_acc = Account(
        account_code="5010",
        account_name="Rent Expense",
        normalized_name="rent_expense",
        account_type="EXPENSE",
        normal_balance="DEBIT",
    )
    deprec_acc = Account(
        account_code="6010",
        account_name="Depreciation Expense",
        normalized_name="depreciation_expense",
        account_type="EXPENSE",
        normal_balance="DEBIT",
    )
    db_session.add_all([expense_acc, deprec_acc])
    db_session.flush()

    # 2. Invoices & Assets
    invoice = APInvoice(
        vendor_name="Office Park Landlord",
        invoice_number="INV-RENT-01",
        invoice_date=datetime(2025, 1, 1, 0, 0, 0),
        subtotal_amount=Decimal("100000.00"),
        tax_amount=Decimal("16000.00"),
        total_amount=Decimal("116000.00"),
        outstanding_amount=Decimal("116000.00"),
        status="OPEN",
    )
    asset = FixedAsset(
        asset_code="COMP-001",
        asset_name="MacBook Pro M3",
        category="COMPUTERS",
        acquisition_date=datetime(2025, 1, 10, 0, 0, 0),
        in_service_date=datetime(2025, 1, 15, 0, 0, 0),
        acquisition_cost=Decimal("350000.00"),
        salvage_value=Decimal("35000.00"),
        useful_life_months=36,
        depreciation_method="STRAIGHT_LINE",
        accumulated_depreciation=Decimal("8750.00"),
        book_value=Decimal("341250.00"),
        status="ACTIVE",
    )
    db_session.add_all([invoice, asset])
    db_session.flush()

    run = ReconciliationRun(
        run_type="MULTI_DOMAIN_AUDIT",
        fiscal_period="2025-01",
        status="COMPLETED",
    )
    db_session.add(run)
    db_session.flush()

    # Accrual Review Result
    accrual_result = ReconciliationResult(
        run_id=run.id,
        result_type="ACCRUAL_REVIEW",
        ap_invoice_id=invoice.id,
        expected_amount=Decimal("116000.00"),
        actual_amount=Decimal("110000.00"),
        variance=Decimal("6000.00"),
        status="VARIANCE_DETECTED",
        match_method="ACCRUAL_3WAY",
        details_json={"invoice_no": "INV-RENT-01", "accrual_discrepancy": "6000.00"},
    )
    # Depreciation Validation Result
    deprec_result = ReconciliationResult(
        run_id=run.id,
        result_type="DEPRECIATION_VALIDATION",
        fixed_asset_id=asset.id,
        expected_amount=Decimal("8750.00"),
        actual_amount=Decimal("8750.00"),
        variance=Decimal("0.00"),
        status="MATCHED",
        match_method="DEPRECIATION_SCHEDULE",
        confidence=Decimal("1.0000"),
        details_json={"asset_code": "COMP-001", "method": "STRAIGHT_LINE"},
    )
    db_session.add_all([accrual_result, deprec_result])
    db_session.commit()

    saved_accrual = db_session.get(ReconciliationResult, accrual_result.id)
    assert saved_accrual.result_type == "ACCRUAL_REVIEW"
    assert saved_accrual.ap_invoice.invoice_number == "INV-RENT-01"
    assert saved_accrual.variance == Decimal("6000.00")

    saved_deprec = db_session.get(ReconciliationResult, deprec_result.id)
    assert saved_deprec.result_type == "DEPRECIATION_VALIDATION"
    assert saved_deprec.fixed_asset.asset_code == "COMP-001"
    assert saved_deprec.expected_amount == Decimal("8750.00")
    assert saved_deprec.status == "MATCHED"


def test_fixed_asset_complete_lifecycle_and_constraints(db_session):
    """Verify FixedAsset attributes, in_service_date, disposal_date, and currency property."""
    asset = FixedAsset(
        asset_code="FA-TRUCK-01",
        asset_name="Scania Prime Mover",
        category="MOTOR_VEHICLES",
        acquisition_date=datetime(2023, 6, 1, 0, 0, 0),
        in_service_date=datetime(2023, 6, 15, 0, 0, 0),
        acquisition_cost=Decimal("12000000.00"),
        salvage_value=Decimal("1200000.00"),
        useful_life_months=96,
        depreciation_method="STRAIGHT_LINE",
        accumulated_depreciation=Decimal("2250000.00"),
        book_value=Decimal("9750000.00"),
        currency_code="KES",
        status="ACTIVE",
    )
    db_session.add(asset)
    db_session.commit()

    saved_asset = db_session.get(FixedAsset, asset.id)
    assert saved_asset.in_service_date == datetime(2023, 6, 15, 0, 0, 0)
    assert saved_asset.disposal_date is None
    assert saved_asset.currency == "KES"

    # Test updating disposal date and status
    saved_asset.disposal_date = datetime(2025, 12, 31, 0, 0, 0)
    saved_asset.status = "DISPOSED"
    saved_asset.currency = "USD"
    db_session.commit()

    updated_asset = db_session.get(FixedAsset, asset.id)
    assert updated_asset.disposal_date == datetime(2025, 12, 31, 0, 0, 0)
    assert updated_asset.status == "DISPOSED"
    assert updated_asset.currency_code == "USD"
    assert updated_asset.currency == "USD"


def test_trial_balance_controls(db_session):
    """Verify TrialBalanceRecord storage and balance fields."""
    acc = Account(
        account_code="2010",
        account_name="Accounts Payable",
        normalized_name="accounts_payable",
        account_type="LIABILITY",
        normal_balance="CREDIT",
    )
    db_session.add(acc)
    db_session.flush()

    tb = TrialBalanceRecord(
        account_id=acc.id,
        fiscal_period="2025-12",
        opening_balance=Decimal("1000000.00"),
        period_debit=Decimal("500000.00"),
        period_credit=Decimal("300000.00"),
        closing_balance=Decimal("800000.00"),
        currency_code="KES",
    )
    db_session.add(tb)
    db_session.commit()

    saved_tb = db_session.get(TrialBalanceRecord, tb.id)
    assert saved_tb.fiscal_period == "2025-12"
    assert saved_tb.closing_balance == Decimal("800000.00")
    assert saved_tb.account.account_name == "Accounts Payable"


def test_backward_compatibility_models(db_session):
    """Verify FinancialRecord, ExceptionRecord, and AuditTrailRecord legacy workflows operate smoothly."""
    rec = FinancialRecord(
        id="legacy-gl-001",
        source="GL",
        account_code="1010",
        amount=15000.50,
        description="Legacy GL test line",
        reference="REF-001",
        is_reconciled=False,
    )
    db_session.add(rec)

    exc = ExceptionRecord(
        id="legacy-exc-001",
        period="2025-Q1",
        category="UNRECONCILED",
        severity="HIGH",
        amount_variance=Decimal("1500.00"),
        description="Legacy exception format",
        status="OPEN",
    )
    db_session.add(exc)

    audit = AuditTrailRecord(
        id="legacy-audit-001",
        run_id="run-test-01",
        event_type="AGENT_DECISION",
        details={"step": "legacy_check"},
    )
    db_session.add(audit)
    db_session.commit()

    saved_rec = db_session.get(FinancialRecord, "legacy-gl-001")
    assert saved_rec.source == "GL"
    assert saved_rec.amount == 15000.50

    saved_exc = db_session.get(ExceptionRecord, "legacy-exc-001")
    assert saved_exc.period == "2025-Q1"
    assert saved_exc.amount_variance == Decimal("1500.00")

    saved_audit = db_session.get(AuditEvent, "legacy-audit-001")
    assert saved_audit.event_type == "AGENT_DECISION"
