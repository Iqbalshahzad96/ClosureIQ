"""
SQLAlchemy Database Models for Generic Financial Schema, Exceptions, and Traces.

This module provides an ERP-independent canonical SQLite schema with full
lineage, relationships, multi-currency/organization scoping, and Decimal precision.
Backward compatibility models (FinancialRecord, AuditTrailRecord) are maintained.
"""

from decimal import Decimal
import uuid
from datetime import datetime, timezone


def _utc_now():
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _generate_uuid() -> str:
    """Generate a standard UUID4 string."""
    return str(uuid.uuid4())


try:
    from sqlalchemy import (
        Boolean,
        CheckConstraint,
        Column,
        DateTime,
        ForeignKey,
        Integer,
        Numeric,
        String,
        Text,
        JSON,
        Float,
    )
    from sqlalchemy.orm import relationship
    from app.database.database import Base

    # =========================================================================
    # Tenancy, Feeder Systems & Raw Ingestion Lineage
    # =========================================================================

    class SourceSystem(Base):
        """
        ERP-independent source feeder / adapter registration.
        Examples: Enquest ERP, SAP S/4HANA, NetSuite, Bank Statement Feed.
        """
        __tablename__ = "source_systems"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        adapter_key = Column(String(64), nullable=False, index=True)  # e.g., "enquest_adapter", "generic_csv"
        source_type = Column(String(32), nullable=False)  # ERP, BANK, SUB_LEDGER, MANUAL
        display_name = Column(String(128), nullable=False)
        configuration_json = Column(JSON, default=dict)
        is_active = Column(Boolean, default=True, nullable=False)
        created_at = Column(DateTime, default=_utc_now, nullable=False)
        updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

        # Relationships
        import_batches = relationship("ImportBatch", back_populates="source_system", cascade="all, delete-orphan")
        source_account_mappings = relationship("SourceAccountMapping", back_populates="source_system", cascade="all, delete-orphan")


    class ImportBatch(Base):
        """
        Tracking entity for an ingestion batch / execution.
        """
        __tablename__ = "import_batches"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        source_system_id = Column(String(36), ForeignKey("source_systems.id"), nullable=False, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        period_start = Column(DateTime, nullable=True)
        period_end = Column(DateTime, nullable=True)
        status = Column(String(32), default="PENDING", index=True, nullable=False)  # PENDING, PROCESSING, COMPLETED, FAILED, QUARANTINED
        file_count = Column(Integer, default=0, nullable=False)
        total_rows = Column(Integer, default=0, nullable=False)
        valid_rows = Column(Integer, default=0, nullable=False)
        error_rows = Column(Integer, default=0, nullable=False)
        validation_summary_json = Column(JSON, default=dict)
        started_at = Column(DateTime, default=_utc_now, nullable=False)
        completed_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        source_system = relationship("SourceSystem", back_populates="import_batches")
        source_files = relationship("SourceFile", back_populates="import_batch", cascade="all, delete-orphan")
        journal_entries = relationship("JournalEntry", back_populates="import_batch")
        trial_balance_records = relationship("TrialBalanceRecord", back_populates="import_batch")
        bank_transactions = relationship("BankTransaction", back_populates="import_batch")
        ap_invoices = relationship("APInvoice", back_populates="import_batch")
        fixed_assets = relationship("FixedAsset", back_populates="import_batch")


    class SourceFile(Base):
        """
        Immutable metadata and audit lineage for raw source files.
        """
        __tablename__ = "source_files"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=False, index=True)
        original_filename = Column(String(255), nullable=False)
        relative_raw_path = Column(String(512), nullable=False)
        sha256 = Column(String(64), nullable=False, index=True)
        byte_size = Column(Integer, nullable=False)
        media_type = Column(String(64), nullable=True)
        parse_status = Column(String(32), default="PENDING", nullable=False)  # PENDING, PARSED, FAILED, QUARANTINED
        file_metadata_json = Column(JSON, default=dict)
        received_at = Column(DateTime, default=_utc_now, nullable=False)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        import_batch = relationship("ImportBatch", back_populates="source_files")
        journal_entries = relationship("JournalEntry", back_populates="source_file")


    # =========================================================================
    # Chart of Accounts & General Ledger
    # =========================================================================

    class Account(Base):
        """
        Canonical chart of accounts.
        """
        __tablename__ = "accounts"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        account_code = Column(String(64), nullable=True, index=True)
        account_name = Column(String(255), nullable=False)
        normalized_name = Column(String(255), nullable=False, index=True)
        account_type = Column(String(32), nullable=False)  # ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE
        normal_balance = Column(String(8), default="DEBIT", nullable=False)  # DEBIT, CREDIT
        parent_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True)
        currency_code = Column(String(3), default="KES", nullable=False)
        is_active = Column(Boolean, default=True, nullable=False)
        created_at = Column(DateTime, default=_utc_now, nullable=False)
        updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

        # Relationships
        parent_account = relationship("Account", remote_side=[id], backref="child_accounts")
        source_mappings = relationship("SourceAccountMapping", back_populates="account")
        journal_lines = relationship("JournalLine", back_populates="account")
        trial_balance_records = relationship("TrialBalanceRecord", back_populates="account")
        bank_accounts = relationship("BankAccount", back_populates="gl_account")


    class SourceAccountMapping(Base):
        """
        Mapping between source system account keys/names and canonical Account.
        """
        __tablename__ = "source_account_mappings"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        source_system_id = Column(String(36), ForeignKey("source_systems.id"), nullable=False, index=True)
        source_account_key = Column(String(255), nullable=False, index=True)
        account_id = Column(String(36), ForeignKey("accounts.id"), nullable=False, index=True)
        raw_account_name = Column(String(255), nullable=True)
        mapping_status = Column(String(32), default="PENDING_REVIEW", nullable=False)  # AUTO_MAPPED, REVIEWED, PENDING_REVIEW
        reviewed_by = Column(String(128), nullable=True)
        reviewed_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        source_system = relationship("SourceSystem", back_populates="source_account_mappings")
        account = relationship("Account", back_populates="source_mappings")


    class JournalEntry(Base):
        """
        Canonical multi-line journal entry / voucher.
        """
        __tablename__ = "journal_entries"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        source_file_id = Column(String(36), ForeignKey("source_files.id"), nullable=True, index=True)
        external_entry_id = Column(String(128), nullable=True, index=True)  # e.g. source voucher number
        entry_number = Column(String(128), nullable=True)
        entry_type = Column(String(64), default="JOURNAL", index=True, nullable=False)  # JOURNAL, PAYMENT, RECEIPT, CONTRA, etc.
        entry_date = Column(DateTime, nullable=True, default=None)  # Explicit date; never auto-defaults to current time
        posting_date = Column(DateTime, nullable=True, default=None)  # Explicit date; never auto-defaults to current time
        fiscal_period = Column(String(32), nullable=True, index=True)  # e.g. "2025-01"
        reference = Column(String(255), nullable=True, index=True)
        description = Column(Text, nullable=True)
        currency_code = Column(String(3), default="KES", nullable=False)
        exchange_rate = Column(Numeric(18, 6), default=Decimal("1.000000"), nullable=False)
        status = Column(String(32), default="POSTED", nullable=False)  # DRAFT, POSTED, REVERSED
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        import_batch = relationship("ImportBatch", back_populates="journal_entries")
        source_file = relationship("SourceFile", back_populates="journal_entries")
        lines = relationship("JournalLine", back_populates="journal_entry", cascade="all, delete-orphan")


    class JournalLine(Base):
        """
        Canonical debit / credit posting line.
        """
        __tablename__ = "journal_lines"
        __table_args__ = (
            CheckConstraint("debit_amount >= 0", name="chk_journal_lines_debit_amount"),
            CheckConstraint("credit_amount >= 0", name="chk_journal_lines_credit_amount"),
        )

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        journal_entry_id = Column(String(36), ForeignKey("journal_entries.id"), nullable=False, index=True)
        account_id = Column(String(36), ForeignKey("accounts.id"), nullable=False, index=True)
        line_number = Column(Integer, default=1, nullable=False)
        description = Column(Text, nullable=True)
        debit_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        credit_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        base_debit_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        base_credit_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        source_running_balance = Column(Numeric(18, 4), nullable=True)
        source_row_identifier = Column(String(255), nullable=True)
        dimensions_json = Column(JSON, default=dict)
        is_reconciled = Column(Boolean, default=False, nullable=False)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        journal_entry = relationship("JournalEntry", back_populates="lines")
        account = relationship("Account", back_populates="journal_lines")
        reconciliation_results = relationship("ReconciliationResult", back_populates="journal_line")
        exceptions = relationship("ExceptionRecord", foreign_keys="ExceptionRecord.journal_line_id", back_populates="journal_line")


    class TrialBalanceRecord(Base):
        """
        Canonical trial balance period summary and control balances.
        """
        __tablename__ = "trial_balance_records"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        account_id = Column(String(36), ForeignKey("accounts.id"), nullable=False, index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        fiscal_period = Column(String(32), nullable=False, index=True)  # e.g. "2025-12"
        period_start = Column(DateTime, nullable=True, default=None)
        period_end = Column(DateTime, nullable=True, default=None)
        opening_balance = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        period_debit = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        period_credit = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        closing_balance = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        currency_code = Column(String(3), default="KES", nullable=False)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        account = relationship("Account", back_populates="trial_balance_records")
        import_batch = relationship("ImportBatch", back_populates="trial_balance_records")


    # =========================================================================
    # Banking & Sub-Ledgers
    # =========================================================================

    class BankAccount(Base):
        """
        Bank and cash account master entity.
        """
        __tablename__ = "bank_accounts"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        bank_name = Column(String(128), nullable=False)
        account_number_masked = Column(String(64), nullable=False)
        account_name = Column(String(255), nullable=False)
        currency_code = Column(String(3), default="KES", nullable=False)
        linked_gl_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True, index=True)
        is_active = Column(Boolean, default=True, nullable=False)
        created_at = Column(DateTime, default=_utc_now, nullable=False)
        updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

        # Relationships
        gl_account = relationship("Account", back_populates="bank_accounts")
        transactions = relationship("BankTransaction", back_populates="bank_account", cascade="all, delete-orphan")


    class BankTransaction(Base):
        """
        Bank statement transaction record (bank-originated side of reconciliation).
        """
        __tablename__ = "bank_transactions"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        bank_account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False, index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        external_transaction_id = Column(String(128), nullable=True, index=True)
        booking_date = Column(DateTime, nullable=True, default=None)  # NOT defaulted to now
        value_date = Column(DateTime, nullable=True, default=None)  # NOT defaulted to now
        amount = Column(Numeric(18, 4), nullable=False)  # Signed: + deposit, - withdrawal
        currency_code = Column(String(3), default="KES", nullable=False)
        bank_reference = Column(String(255), nullable=True, index=True)
        description = Column(Text, nullable=True)
        running_balance = Column(Numeric(18, 4), nullable=True)
        is_reconciled = Column(Boolean, default=False, nullable=False)
        source_row_identifier = Column(String(255), nullable=True)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        bank_account = relationship("BankAccount", back_populates="transactions")
        import_batch = relationship("ImportBatch", back_populates="bank_transactions")
        reconciliation_results = relationship("ReconciliationResult", back_populates="bank_transaction")
        exceptions = relationship("ExceptionRecord", foreign_keys="ExceptionRecord.bank_transaction_id", back_populates="bank_transaction")


    class APInvoice(Base):
        """
        Accounts Payable invoice entity.
        """
        __tablename__ = "ap_invoices"
        __table_args__ = (
            CheckConstraint("subtotal_amount >= 0", name="chk_ap_invoices_subtotal_amount"),
            CheckConstraint("tax_amount >= 0", name="chk_ap_invoices_tax_amount"),
            CheckConstraint("total_amount >= 0", name="chk_ap_invoices_total_amount"),
            CheckConstraint("paid_amount >= 0", name="chk_ap_invoices_paid_amount"),
        )

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        vendor_name = Column(String(255), nullable=False)
        vendor_code = Column(String(64), nullable=True, index=True)
        invoice_number = Column(String(128), nullable=False, index=True)
        invoice_date = Column(DateTime, nullable=True, default=None)  # NOT defaulted to now
        due_date = Column(DateTime, nullable=True, default=None)  # NOT defaulted to now
        currency_code = Column(String(3), default="KES", nullable=False)
        subtotal_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        tax_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        total_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        paid_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        outstanding_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        status = Column(String(32), default="OPEN", index=True, nullable=False)  # OPEN, PAID, PARTIALLY_PAID, VOID
        description = Column(Text, nullable=True)
        gl_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True, index=True)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        import_batch = relationship("ImportBatch", back_populates="ap_invoices")
        gl_account = relationship("Account")
        reconciliation_results = relationship("ReconciliationResult", back_populates="ap_invoice")


    class FixedAsset(Base):
        """
        Fixed asset register entity with complete lifecycle tracking and constraints.
        """
        __tablename__ = "fixed_assets"
        __table_args__ = (
            CheckConstraint("acquisition_cost >= 0", name="chk_fixed_assets_acquisition_cost"),
            CheckConstraint("salvage_value >= 0", name="chk_fixed_assets_salvage_value"),
            CheckConstraint("accumulated_depreciation >= 0", name="chk_fixed_assets_accumulated_depreciation"),
        )

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        asset_code = Column(String(64), nullable=True, index=True)
        asset_name = Column(String(255), nullable=False)
        category = Column(String(64), nullable=False)  # MOTOR_VEHICLES, COMPUTERS, FURNITURE, PLANT_MACHINERY, etc.
        acquisition_date = Column(DateTime, nullable=True, default=None)  # NOT defaulted to now
        in_service_date = Column(DateTime, nullable=True, default=None)  # Date asset entered service
        acquisition_cost = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        salvage_value = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        useful_life_months = Column(Integer, nullable=True)
        depreciation_method = Column(String(32), default="STRAIGHT_LINE", nullable=False)
        accumulated_depreciation = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        book_value = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        currency_code = Column(String(3), default="KES", nullable=False)
        status = Column(String(32), default="ACTIVE", index=True, nullable=False)  # ACTIVE, DISPOSED, FULLY_DEPRECIATED
        disposal_date = Column(DateTime, nullable=True, default=None)  # Date of disposal if applicable
        asset_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True, index=True)
        accum_deprec_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True, index=True)
        deprec_expense_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True, index=True)
        created_at = Column(DateTime, default=_utc_now, nullable=False)
        updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

        # Property alias for currency
        @property
        def currency(self) -> str:
            return self.currency_code

        @currency.setter
        def currency(self, value: str) -> None:
            self.currency_code = value

        # Relationships
        import_batch = relationship("ImportBatch", back_populates="fixed_assets")
        asset_account = relationship("Account", foreign_keys=[asset_account_id], backref="fixed_assets_cost")
        accum_deprec_account = relationship("Account", foreign_keys=[accum_deprec_account_id])
        deprec_expense_account = relationship("Account", foreign_keys=[deprec_expense_account_id])
        reconciliation_results = relationship("ReconciliationResult", back_populates="fixed_asset")


    # =========================================================================
    # Reconciliation, Exceptions & Observability
    # =========================================================================

    class ReconciliationRun(Base):
        """
        Reconciliation execution run (supports bank recon, accruals, depreciation, etc.).
        """
        __tablename__ = "reconciliation_runs"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        run_type = Column(String(64), default="GL_BANK_RECONCILIATION", nullable=False)  # GL_BANK_RECONCILIATION, ACCRUAL_REVIEW, DEPRECIATION_VALIDATION
        fiscal_period = Column(String(32), nullable=True, index=True)
        period_start = Column(DateTime, nullable=True, default=None)
        period_end = Column(DateTime, nullable=True, default=None)
        gl_import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        bank_import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        tolerance_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        date_window_days = Column(Integer, default=7, nullable=False)
        status = Column(String(32), default="PENDING", index=True, nullable=False)  # PENDING, IN_PROGRESS, COMPLETED, FAILED
        requested_by = Column(String(128), nullable=True)
        started_at = Column(DateTime, nullable=True)
        completed_at = Column(DateTime, nullable=True)
        summary_json = Column(JSON, default=dict)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        results = relationship("ReconciliationResult", back_populates="run", cascade="all, delete-orphan")
        exceptions = relationship("ExceptionRecord", back_populates="run")
        audit_events = relationship("AuditEvent", back_populates="run")


    class ReconciliationResult(Base):
        """
        Generalized result of reconciliation, accrual review, or depreciation validation.
        Links JournalLine, BankTransaction, APInvoice, or FixedAsset entities.
        """
        __tablename__ = "reconciliation_results"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        run_id = Column(String(36), ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
        result_type = Column(String(64), default="BANK_RECONCILIATION", nullable=False, index=True)  # BANK_RECONCILIATION, ACCRUAL_REVIEW, DEPRECIATION_VALIDATION
        match_group_id = Column(String(36), nullable=True, index=True)

        # Nullable polymorphic/domain entity references
        journal_line_id = Column(String(36), ForeignKey("journal_lines.id"), nullable=True, index=True)
        bank_transaction_id = Column(String(36), ForeignKey("bank_transactions.id"), nullable=True, index=True)
        ap_invoice_id = Column(String(36), ForeignKey("ap_invoices.id"), nullable=True, index=True)
        fixed_asset_id = Column(String(36), ForeignKey("fixed_assets.id"), nullable=True, index=True)

        # Financial comparison & variance
        expected_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        actual_amount = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        variance = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        amount_difference = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)  # Alias/compat
        date_difference_days = Column(Integer, nullable=True)

        # Status & matching telemetry
        status = Column(String(32), default="MATCHED", nullable=False, index=True)  # MATCHED, UNMATCHED, VARIANCE_DETECTED, RESOLVED, EXCEPTION
        result_status = Column(String(32), default="MATCHED", nullable=False, index=True)  # Alias/compat
        match_method = Column(String(64), nullable=True)  # EXACT_REFERENCE, FUZZY_AMOUNT_DATE, DEPRECIATION_SCHEDULE, ACCRUAL_3WAY, MANUAL
        confidence = Column(Numeric(5, 4), nullable=True)  # 0.0000 to 1.0000
        rule_version = Column(String(32), nullable=True)
        details_json = Column(JSON, default=dict)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        run = relationship("ReconciliationRun", back_populates="results")
        journal_line = relationship("JournalLine", back_populates="reconciliation_results")
        bank_transaction = relationship("BankTransaction", back_populates="reconciliation_results")
        ap_invoice = relationship("APInvoice", back_populates="reconciliation_results")
        fixed_asset = relationship("FixedAsset", back_populates="reconciliation_results")
        exceptions = relationship("ExceptionRecord", back_populates="reconciliation_result")


    class ExceptionRecord(Base):
        """
        Detected financial anomalies, breaks, and reconciliation exceptions.
        Linked primarily through reconciliation_result_id while retaining legacy compatibility.
        """
        __tablename__ = "exception_records"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)

        # Primary link to reconciliation result
        reconciliation_result_id = Column(String(36), ForeignKey("reconciliation_results.id"), nullable=True, index=True)

        # Direct domain references (optional / legacy)
        run_id = Column(String(36), ForeignKey("reconciliation_runs.id"), nullable=True, index=True)
        journal_line_id = Column(String(36), ForeignKey("journal_lines.id"), nullable=True, index=True)
        bank_transaction_id = Column(String(36), ForeignKey("bank_transactions.id"), nullable=True, index=True)

        # Legacy & canonical exception fields
        period = Column(String(32), nullable=False, index=True)
        category = Column(String(64), nullable=False)  # RECONCILIATION, ACCRUAL, DEPRECIATION, TAX, etc.
        severity = Column(String(32), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
        amount_variance = Column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
        currency_code = Column(String(3), default="KES", nullable=False)
        description = Column(Text, default="", nullable=False)
        status = Column(String(32), default="OPEN", index=True, nullable=False)  # OPEN, IN_REVIEW, RESOLVED
        assigned_to = Column(String(128), nullable=True)
        policy_evidence_json = Column(JSON, default=dict)
        resolved_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, default=_utc_now, nullable=False)
        updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)

        # Relationships
        reconciliation_result = relationship("ReconciliationResult", back_populates="exceptions")
        run = relationship("ReconciliationRun", back_populates="exceptions")
        journal_line = relationship("JournalLine", foreign_keys=[journal_line_id], back_populates="exceptions")
        bank_transaction = relationship("BankTransaction", foreign_keys=[bank_transaction_id], back_populates="exceptions")


    class AuditEvent(Base):
        """
        Observability trace, agent decisions, and audit trail records.
        """
        __tablename__ = "audit_events"

        id = Column(String(36), primary_key=True, default=_generate_uuid, index=True)
        organization_id = Column(String(64), nullable=False, default="default_org", index=True)
        run_id = Column(String(36), ForeignKey("reconciliation_runs.id"), nullable=True, index=True)
        import_batch_id = Column(String(36), ForeignKey("import_batches.id"), nullable=True, index=True)
        exception_id = Column(String(36), ForeignKey("exception_records.id"), nullable=True, index=True)
        event_type = Column(String(64), nullable=False, index=True)  # AGENT_DECISION, HITL_APPROVAL, ERROR, etc.
        actor = Column(String(128), nullable=True)
        details = Column(JSON, default=dict)
        created_at = Column(DateTime, default=_utc_now, nullable=False)

        # Relationships
        run = relationship("ReconciliationRun", back_populates="audit_events")


    # Alias for backward compatibility
    AuditTrailRecord = AuditEvent


    # =========================================================================
    # Legacy Working Models (Preserved for Backward Compatibility)
    # =========================================================================

    class FinancialRecord(Base):
        """
        General Ledger and Bank Statement transactions (Legacy Model).
        Preserved to prevent regressions in legacy MCP tools and endpoints.
        """
        __tablename__ = "financial_records"

        id = Column(String, primary_key=True, index=True)
        source = Column(String, nullable=False)  # "GL" | "BANK"
        account_code = Column(String, nullable=False, index=True)
        transaction_date = Column(DateTime, default=_utc_now)
        amount = Column(Float, nullable=False)
        description = Column(String, default="")
        reference = Column(String, default="")
        is_reconciled = Column(Boolean, default=False)


except ImportError:
    # Stubs when SQLAlchemy is not available
    class SourceSystem: pass
    class ImportBatch: pass
    class SourceFile: pass
    class Account: pass
    class SourceAccountMapping: pass
    class JournalEntry: pass
    class JournalLine: pass
    class TrialBalanceRecord: pass
    class BankAccount: pass
    class BankTransaction: pass
    class APInvoice: pass
    class FixedAsset: pass
    class ReconciliationRun: pass
    class ReconciliationResult: pass
    class ExceptionRecord: pass
    class AuditEvent: pass
    AuditTrailRecord = AuditEvent
    class FinancialRecord: pass
