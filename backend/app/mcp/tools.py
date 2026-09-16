"""
MCP Tool Definitions for Controlled Financial Data Access

Agents call these tools to inspect GL entries, bank lines, and exception records.
All public tool parameters are JSON-serializable (str, int). SQLAlchemy sessions
are managed internally and guaranteed to close via try/finally.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.financial_engine.periods import period_bounds, ledger_period_filter


class FinancialMCPTools:
    """Collection of MCP tools exposed to AI agents.

    Parameters
    ----------
    session_factory : callable
        A zero-argument callable that returns a new ``sqlalchemy.orm.Session``.
        Defaults to ``None``; must be set before any tool is invoked.
    """

    def __init__(self, session_factory: Optional[Callable[[], Session]] = None, organization_id: str = "default_org") -> None:
        self._session_factory = session_factory
        self.organization_id = organization_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self) -> Session:
        """Create a new session from the factory.

        Raises ``RuntimeError`` if no session factory has been configured.
        """
        if self._session_factory is None:
            raise RuntimeError(
                "FinancialMCPTools: session_factory has not been configured. "
                "Provide a session factory via the constructor."
            )
        return self._session_factory()

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Validate that limit is within the accepted range.

        Raises ``ValueError`` if limit is not between 1 and 100 inclusive.
        Called before opening a database session.
        """
        if not (1 <= limit <= 100):
            raise ValueError("limit must be between 1 and 100")

    @staticmethod
    def _serialize_datetime(dt: Any) -> Optional[str]:
        """Convert a datetime to ISO-8601 string, or return None."""
        if dt is None:
            return None
        return dt.isoformat()

    # ------------------------------------------------------------------
    # Account Balance — queries canonical TrialBalanceRecord or
    # falls back to JournalLine aggregation for the requested period.
    # ------------------------------------------------------------------

    async def get_account_balance(self, account_code: str, period: str) -> Dict[str, Any]:
        """Retrieve the canonical balance for an account in a fiscal period.

        Uses the latest canonical snapshot (created_at, then id) in the account
        currency. Otherwise reports posted journal movement for the exact fiscal
        period; opening and closing remain unknown. Numeric compatibility fields
        have lossless decimal-string counterparts in exact_amounts.

        Parameters
        ----------
        account_code : str
            The chart-of-accounts code.
        period : str
            Fiscal period identifier (e.g. ``"2026-01"``).

        Returns
        -------
        dict
            Balance breakdown with ``found`` boolean.
        """
        from app.database.models import Account, JournalEntry, JournalLine, TrialBalanceRecord

        period = period.strip()
        account_code = account_code.strip()
        if not period or not account_code:
            raise ValueError("account_code and period must be non-empty")
        session = self._get_session()
        try:
            # 1. Try canonical TrialBalanceRecord
            result = (
                session.query(TrialBalanceRecord, Account)
                .join(Account, TrialBalanceRecord.account_id == Account.id)
                .filter(
                    Account.account_code == account_code,
                    Account.organization_id == self.organization_id,
                    TrialBalanceRecord.organization_id == self.organization_id,
                    TrialBalanceRecord.fiscal_period == period.strip(),
                    TrialBalanceRecord.currency_code == Account.currency_code,
                )
                .order_by(TrialBalanceRecord.created_at.desc(), TrialBalanceRecord.id.desc())
                .first()
            )

            if result is not None:
                tb, acc = result
                return {
                    "account_code": acc.account_code,
                    "account_name": acc.account_name,
                    "normal_balance": acc.normal_balance,
                    "import_batch_id": tb.import_batch_id,
                    "exact_amounts": {key: str(getattr(tb, key)) for key in
                                     ("opening_balance", "period_debit", "period_credit", "closing_balance")},
                    "fiscal_period": tb.fiscal_period,
                    "opening_balance": float(tb.opening_balance) if tb.opening_balance is not None else 0.0,
                    "period_debit": float(tb.period_debit) if tb.period_debit is not None else 0.0,
                    "period_credit": float(tb.period_credit) if tb.period_credit is not None else 0.0,
                    "closing_balance": float(tb.closing_balance) if tb.closing_balance is not None else 0.0,
                    "currency_code": tb.currency_code,
                    "record_id": tb.id,
                    "balance_basis": "CANONICAL_SNAPSHOT",
                    "source": "TRIAL_BALANCE_RECORD",
                    "found": True,
                }

            # 2. Fallback: aggregate from JournalLines for the given period
            account = (
                session.query(Account)
                .filter(
                    Account.account_code == account_code,
                    Account.organization_id == self.organization_id,
                )
                .first()
            )
            if account is None:
                return {"account_code": account_code, "fiscal_period": period, "found": False}

            # Sum retrieved Numeric values with Decimal (SQLite SUM uses floating point).
            lines = (session.query(JournalLine)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .filter(JournalLine.account_id == account.id,
                        JournalEntry.organization_id == self.organization_id,
                        JournalEntry.fiscal_period == period,
                        JournalEntry.status == "POSTED",
                        JournalEntry.currency_code == account.currency_code)
                .order_by(JournalLine.id).all())
            total_debit = sum((line.debit_amount for line in lines), Decimal("0"))
            total_credit = sum((line.credit_amount for line in lines), Decimal("0"))
            movement = total_credit - total_debit if account.normal_balance == "CREDIT" else total_debit - total_credit
            return {
                "account_code": account.account_code,
                "account_name": account.account_name,
                "normal_balance": account.normal_balance,
                "fiscal_period": period,
                # A period's postings do not establish an opening or closing balance.
                "opening_balance": None,
                "closing_balance": None,
                "period_debit": float(total_debit),
                "period_credit": float(total_credit),
                "net_movement": float(movement),
                "exact_amounts": {"period_debit": str(total_debit),
                                  "period_credit": str(total_credit), "net_movement": str(movement)},
                "currency_code": account.currency_code,
                "source": "JOURNAL_LINE_AGGREGATION",
                "balance_basis": "PERIOD_MOVEMENT_ONLY",
                "journal_line_ids": [line.id for line in lines],
                "found": bool(lines),
            }

        finally:
            session.close()

    async def query_gl_transactions(
        self,
        account_code: Optional[str] = None,
        limit: int = 50,
        fiscal_period: Optional[str] = None,
        offset: int = 0,
        account_id: Optional[str] = None,
        currency_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Canonical postings only; signed amount is debit minus credit.

        Original debit/credit columns and draft status remain visible. No source
        filenames, headers or ERP transformations are used by this query.
        """
        from app.database.models import Account, JournalEntry, JournalLine
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = (session.query(JournalLine, JournalEntry, Account)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .join(Account, JournalLine.account_id == Account.id)
                .filter(Account.organization_id == self.organization_id,
                        JournalEntry.organization_id == self.organization_id))
            if account_id:
                query = query.filter(Account.id == account_id)
            else:
                query = query.filter(Account.account_code == account_code)
            if currency_code:
                query = query.filter(JournalEntry.currency_code == currency_code)
            if fiscal_period:
                query = query.filter(ledger_period_filter(JournalEntry.fiscal_period, JournalEntry.entry_date, fiscal_period))
            rows = (query.order_by(JournalEntry.entry_date.desc(), JournalLine.id)
                .offset(offset).limit(limit).all())
            return [{'id':line.id,'source':'GL','account_code':account.account_code,
                     'transaction_date':self._serialize_datetime(entry.entry_date),
                     'amount':float(line.debit_amount-line.credit_amount),
                     'debit_amount':str(line.debit_amount),'credit_amount':str(line.credit_amount),
                     'currency_code':entry.currency_code,'entry_status':entry.status,
                     'fiscal_period':entry.fiscal_period,'import_batch_id':entry.import_batch_id,
                     'source_file_id':entry.source_file_id,'source_row_identifier':line.source_row_identifier,
                     'description':line.description or entry.description,'reference':entry.reference,
                     'is_reconciled':line.is_reconciled} for line,entry,account in rows]
        finally:
            session.close()

    async def query_bank_transactions(
        self,
        account_code: Optional[str] = None,
        limit: int = 50,
        fiscal_period: Optional[str] = None,
        offset: int = 0,
        bank_account_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Independent canonical bank statements linked to the requested GL account."""
        from app.database.models import Account, BankAccount, BankTransaction
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = (session.query(BankTransaction, Account)
                .join(BankAccount, BankTransaction.bank_account_id == BankAccount.id)
                .join(Account, BankAccount.linked_gl_account_id == Account.id)
                .filter(Account.organization_id == self.organization_id,
                        BankAccount.organization_id == self.organization_id,
                        BankTransaction.currency_code == BankAccount.currency_code))
            if bank_account_id:
                query = query.filter(BankAccount.id == bank_account_id)
            elif account_id:
                query = query.filter(Account.id == account_id)
            else:
                query = query.filter(Account.account_code == account_code)
            
            if fiscal_period:
                start, end = period_bounds(fiscal_period)
                query = query.filter(BankTransaction.booking_date >= start, BankTransaction.booking_date < end)

            rows = (query.order_by(BankTransaction.booking_date.desc(), BankTransaction.id)
                .offset(offset).limit(limit).all())
            return [{'id':row.id,'source':'BANK','account_code':account.account_code,
                     'transaction_date':self._serialize_datetime(row.booking_date),
                     'amount':float(row.amount),'currency_code':row.currency_code,
                     'description':row.description,'reference':row.bank_reference,
                     'is_reconciled':row.is_reconciled} for row,account in rows]
        finally:
            session.close()

    async def get_exception_details(
        self, exception_id: str
    ) -> Dict[str, Any]:
        """Fetch details for a specific financial exception.

        Parameters
        ----------
        exception_id : str
            Primary key of the ``ExceptionRecord``.

        Returns
        -------
        dict
            All exception columns plus ``found`` (bool). Dates are ISO-8601.
        """
        from app.database.models import ExceptionRecord

        session = self._get_session()
        try:
            record = session.get(ExceptionRecord, exception_id)
            if record is None:
                return {"exception_id": exception_id, "found": False}
            return {
                "exception_id": record.id,
                "period": record.period,
                "category": record.category,
                "severity": record.severity,
                "amount_variance": float(record.amount_variance) if record.amount_variance is not None else 0.0,
                "description": record.description,
                "status": record.status,
                "created_at": self._serialize_datetime(record.created_at),
                "found": True,
            }
        finally:
            session.close()

    async def query_fixed_assets(
        self, category: Optional[str] = None, status: Optional[str] = None, limit: int = 50, fiscal_period: Optional[str] = None, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query canonical fixed assets register records with lifecycle parameters."""
        from app.database.models import FixedAsset
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = session.query(FixedAsset).filter(FixedAsset.organization_id == self.organization_id)
            if category:
                query = query.filter(FixedAsset.category.ilike(f"%{category.strip()}%"))
            if status:
                query = query.filter(FixedAsset.status == status.strip().upper())
            if fiscal_period:
                start, end = period_bounds(fiscal_period)
                service_date = func.coalesce(FixedAsset.in_service_date, FixedAsset.acquisition_date)
                query = query.filter(service_date < end,
                    or_(FixedAsset.disposal_date.is_(None), FixedAsset.disposal_date >= start))
            rows = query.order_by(FixedAsset.asset_name.asc(), FixedAsset.id).offset(offset).limit(limit).all()
            return [
                {
                    "id": asset.id,
                    "asset_code": asset.asset_code,
                    "asset_name": asset.asset_name,
                    "category": asset.category,
                    "acquisition_date": self._serialize_datetime(asset.acquisition_date),
                    "in_service_date": self._serialize_datetime(asset.in_service_date),
                    "acquisition_cost": float(asset.acquisition_cost) if asset.acquisition_cost is not None else 0.0,
                    "cost": float(asset.acquisition_cost) if asset.acquisition_cost is not None else 0.0,
                    "salvage_value": float(asset.salvage_value) if asset.salvage_value is not None else 0.0,
                    "useful_life_months": asset.useful_life_months or 0,
                    "depreciation_method": asset.depreciation_method,
                    "accumulated_depreciation": float(asset.accumulated_depreciation) if asset.accumulated_depreciation is not None else 0.0,
                    "accumulated_depreciation_prior": float(asset.accumulated_depreciation) if asset.accumulated_depreciation is not None else 0.0,
                    "book_value": float(asset.book_value) if asset.book_value is not None else 0.0,
                    "currency_code": asset.currency_code,
                    "status": asset.status,
                    "disposal_date": self._serialize_datetime(asset.disposal_date),
                    "asset_account_id": asset.asset_account_id,
                    "accum_deprec_account_id": asset.accum_deprec_account_id,
                    "deprec_expense_account_id": asset.deprec_expense_account_id,
                }
                for asset in rows
            ]
        finally:
            session.close()

    async def query_ap_invoices(
        self, vendor_name: Optional[str] = None, status: Optional[str] = None, limit: int = 50, fiscal_period: Optional[str] = None, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query canonical accounts payable invoices."""
        from app.database.models import APInvoice
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = session.query(APInvoice).filter(APInvoice.organization_id == self.organization_id)
            if vendor_name:
                query = query.filter(APInvoice.vendor_name.ilike(f"%{vendor_name.strip()}%"))
            if status:
                query = query.filter(APInvoice.status == status.strip().upper())
            if fiscal_period:
                start, end = period_bounds(fiscal_period)
                query = query.filter(APInvoice.invoice_date >= start, APInvoice.invoice_date < end)
            rows = query.order_by(APInvoice.invoice_date.desc(), APInvoice.id).offset(offset).limit(limit).all()
            return [
                {
                    "id": inv.id,
                    "vendor_name": inv.vendor_name,
                    "vendor_code": inv.vendor_code,
                    "invoice_number": inv.invoice_number,
                    "invoice_date": self._serialize_datetime(inv.invoice_date),
                    "due_date": self._serialize_datetime(inv.due_date),
                    "currency_code": inv.currency_code,
                    "subtotal_amount": float(inv.subtotal_amount) if inv.subtotal_amount is not None else 0.0,
                    "tax_amount": float(inv.tax_amount) if inv.tax_amount is not None else 0.0,
                    "total_amount": float(inv.total_amount) if inv.total_amount is not None else 0.0,
                    "paid_amount": float(inv.paid_amount) if inv.paid_amount is not None else 0.0,
                    "outstanding_amount": float(inv.outstanding_amount) if inv.outstanding_amount is not None else 0.0,
                    "status": inv.status,
                    "description": inv.description,
                }
                for inv in rows
            ]
        finally:
            session.close()

    async def query_trial_balance(
        self, fiscal_period: Optional[str] = None, account_code: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Query canonical trial balance records with account details."""
        from app.database.models import Account, TrialBalanceRecord
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = (
                session.query(TrialBalanceRecord, Account)
                .join(Account, TrialBalanceRecord.account_id == Account.id)
                .filter(
                    TrialBalanceRecord.organization_id == self.organization_id,
                    Account.organization_id == self.organization_id,
                )
            )
            if fiscal_period:
                query = query.filter(TrialBalanceRecord.fiscal_period == fiscal_period.strip())
            if account_code:
                query = query.filter(Account.account_code == account_code.strip())
            rows = query.order_by(TrialBalanceRecord.fiscal_period.desc(), Account.account_code.asc()).limit(limit).all()
            return [
                {
                    "id": tb.id,
                    "account_id": tb.account_id,
                    "account_code": acc.account_code,
                    "account_name": acc.account_name,
                    "account_type": acc.account_type,
                    "normal_balance": acc.normal_balance,
                    "import_batch_id": tb.import_batch_id,
                    "exact_amounts": {key: str(getattr(tb, key)) for key in
                                     ("opening_balance", "period_debit", "period_credit", "closing_balance")},
                    "fiscal_period": tb.fiscal_period,
                    "period_start": self._serialize_datetime(tb.period_start),
                    "period_end": self._serialize_datetime(tb.period_end),
                    "opening_balance": float(tb.opening_balance) if tb.opening_balance is not None else 0.0,
                    "period_debit": float(tb.period_debit) if tb.period_debit is not None else 0.0,
                    "period_credit": float(tb.period_credit) if tb.period_credit is not None else 0.0,
                    "closing_balance": float(tb.closing_balance) if tb.closing_balance is not None else 0.0,
                    "currency_code": tb.currency_code,
                }
                for tb, acc in rows
            ]
        finally:
            session.close()

    async def query_exceptions(
        self,
        period: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query financial exceptions with optional filters."""
        from app.database.models import ExceptionRecord
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = session.query(ExceptionRecord).filter(ExceptionRecord.organization_id == self.organization_id)
            if period:
                query = query.filter(ExceptionRecord.period == period.strip())
            if category:
                query = query.filter(ExceptionRecord.category == category.strip().upper())
            if severity:
                query = query.filter(ExceptionRecord.severity == severity.strip().upper())
            rows = query.order_by(ExceptionRecord.created_at.desc(), ExceptionRecord.id).limit(limit).all()
            return [
                {
                    "id": rec.id,
                    "exception_id": rec.id,
                    "period": rec.period,
                    "category": rec.category,
                    "severity": rec.severity,
                    "amount_variance": float(rec.amount_variance) if rec.amount_variance is not None else 0.0,
                    "description": rec.description,
                    "status": rec.status,
                    "created_at": self._serialize_datetime(rec.created_at),
                }
                for rec in rows
            ]
        finally:
            session.close()

    async def query_chart_of_accounts(
        self,
        account_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query canonical chart of accounts with optional filters."""
        from app.database.models import Account
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = session.query(Account).filter(Account.organization_id == self.organization_id)
            if account_type:
                query = query.filter(Account.account_type == account_type.strip().upper())
            if is_active is not None:
                query = query.filter(Account.is_active == is_active)
            rows = query.order_by(Account.account_code.asc(), Account.id).limit(limit).all()
            return [
                {
                    "id": acc.id,
                    "account_code": acc.account_code,
                    "account_name": acc.account_name,
                    "account_type": acc.account_type,
                    "normal_balance": acc.normal_balance,
                    "parent_account_id": acc.parent_account_id,
                    "currency_code": acc.currency_code,
                    "is_active": acc.is_active,
                }
                for acc in rows
            ]
        finally:
            session.close()

    async def query_journal_entries(
        self,
        fiscal_period: Optional[str] = None,
        entry_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query canonical journal entries (headers) with optional filters."""
        from app.database.models import JournalEntry
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = session.query(JournalEntry).filter(JournalEntry.organization_id == self.organization_id)
            if fiscal_period:
                query = query.filter(JournalEntry.fiscal_period == fiscal_period.strip())
            if entry_type:
                query = query.filter(JournalEntry.entry_type == entry_type.strip().upper())
            rows = query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id).limit(limit).all()
            return [
                {
                    "id": entry.id,
                    "entry_number": entry.entry_number,
                    "entry_type": entry.entry_type,
                    "entry_date": self._serialize_datetime(entry.entry_date),
                    "posting_date": self._serialize_datetime(entry.posting_date),
                    "fiscal_period": entry.fiscal_period,
                    "reference": entry.reference,
                    "description": entry.description,
                    "currency_code": entry.currency_code,
                    "status": entry.status,
                    "import_batch_id": entry.import_batch_id,
                    "source_file_id": entry.source_file_id,
                }
                for entry in rows
            ]
        finally:
            session.close()

    async def query_accounting_periods(self) -> List[Dict[str, Any]]:
        """Return periods known through canonical trial balances or journal headers."""
        from app.database.models import TrialBalanceRecord, JournalEntry
        from sqlalchemy import func
        session = self._get_session()
        try:
            rows = (
                session.query(
                    TrialBalanceRecord.fiscal_period,
                    func.min(TrialBalanceRecord.period_start).label("period_start"),
                    func.max(TrialBalanceRecord.period_end).label("period_end"),
                    func.count(TrialBalanceRecord.id).label("record_count"),
                )
                .filter(TrialBalanceRecord.organization_id == self.organization_id)
                .group_by(TrialBalanceRecord.fiscal_period)
                .order_by(TrialBalanceRecord.fiscal_period.desc())
                .all()
            )
            periods = [
                {
                    "fiscal_period": row.fiscal_period,
                    "period_start": self._serialize_datetime(row.period_start),
                    "period_end": self._serialize_datetime(row.period_end),
                    "record_count": row.record_count,
                }
                for row in rows
            ]
            known = {row["fiscal_period"] for row in periods}
            journal_periods = session.query(JournalEntry.fiscal_period).filter(
                JournalEntry.organization_id == self.organization_id,
                JournalEntry.fiscal_period.isnot(None)).distinct().all()
            periods.extend({"fiscal_period": period, "period_start": None,
                            "period_end": None, "record_count": 0}
                           for (period,) in journal_periods if period and period not in known)
            return sorted(periods, key=lambda row: row["fiscal_period"], reverse=True)
        finally:
            session.close()

    async def query_import_batches(
        self, status: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Query canonical import batch metadata."""
        from app.database.models import ImportBatch
        self._validate_limit(limit)
        session = self._get_session()
        try:
            query = session.query(ImportBatch).filter(ImportBatch.organization_id == self.organization_id)
            if status:
                query = query.filter(ImportBatch.status == status.strip().upper())
            rows = query.order_by(ImportBatch.created_at.desc(), ImportBatch.id).limit(limit).all()
            return [
                {
                    "id": batch.id,
                    "source_system_id": batch.source_system_id,
                    "status": batch.status,
                    "file_count": batch.file_count,
                    "total_rows": batch.total_rows,
                    "valid_rows": batch.valid_rows,
                    "error_rows": batch.error_rows,
                    "period_start": self._serialize_datetime(batch.period_start),
                    "period_end": self._serialize_datetime(batch.period_end),
                    "started_at": self._serialize_datetime(batch.started_at),
                    "completed_at": self._serialize_datetime(batch.completed_at),
                    "created_at": self._serialize_datetime(batch.created_at),
                }
                for batch in rows
            ]
        finally:
            session.close()

    async def get_record_lineage(
        self, record_type: str, record_id: str
    ) -> Dict[str, Any]:
        """Trace a canonical record back to its source file, import batch, and source system.

        Parameters
        ----------
        record_type : str
            One of: ``JOURNAL_ENTRY``, ``JOURNAL_LINE``, ``BANK_TRANSACTION``,
            ``AP_INVOICE``, ``FIXED_ASSET``, ``TRIAL_BALANCE``.
        record_id : str
            Primary key of the record.

        Returns
        -------
        dict
            Lineage chain with ``found`` boolean.
        """
        from app.database.models import (
            APInvoice, AuditEvent, BankAccount, BankTransaction, FixedAsset,
            ImportBatch, JournalEntry, JournalLine,
            SourceFile, SourceSystem, TrialBalanceRecord,
        )

        session = self._get_session()
        try:
            record_type_upper = record_type.strip().upper()
            import_batch_id = None
            source_file_id = None
            source_row_identifier = None
            record_found = False

            if record_type_upper == "JOURNAL_ENTRY":
                rec = session.get(JournalEntry, record_id)
                if rec and rec.organization_id == self.organization_id:
                    record_found = True
                    import_batch_id = rec.import_batch_id
                    source_file_id = rec.source_file_id

            elif record_type_upper == "JOURNAL_LINE":
                rec = session.query(JournalLine).join(JournalEntry).filter(
                    JournalLine.id == record_id, JournalEntry.organization_id == self.organization_id).first()
                if rec:
                    record_found = True
                    source_row_identifier = rec.source_row_identifier
                    # Walk up to journal entry for batch/file
                    entry = session.get(JournalEntry, rec.journal_entry_id)
                    if entry:
                        import_batch_id = entry.import_batch_id
                        source_file_id = entry.source_file_id

            elif record_type_upper == "BANK_TRANSACTION":
                rec = session.query(BankTransaction).join(BankAccount).filter(
                    BankTransaction.id == record_id, BankAccount.organization_id == self.organization_id).first()
                if rec:
                    record_found = True
                    import_batch_id = rec.import_batch_id
                    source_row_identifier = rec.source_row_identifier

            elif record_type_upper == "AP_INVOICE":
                rec = session.get(APInvoice, record_id)
                if rec and rec.organization_id == self.organization_id:
                    record_found = True
                    import_batch_id = rec.import_batch_id

            elif record_type_upper == "FIXED_ASSET":
                rec = session.get(FixedAsset, record_id)
                if rec and rec.organization_id == self.organization_id:
                    record_found = True
                    import_batch_id = rec.import_batch_id

            elif record_type_upper == "TRIAL_BALANCE":
                rec = session.get(TrialBalanceRecord, record_id)
                if rec and rec.organization_id == self.organization_id:
                    record_found = True
                    import_batch_id = rec.import_batch_id

            if not record_found:
                return {"record_type": record_type, "record_id": record_id, "found": False}

            lineage: Dict[str, Any] = {
                "record_type": record_type,
                "record_id": record_id,
                "found": True,
                "source_row_identifier": source_row_identifier,
            }

            # Ingestion already persists exact provenance for entities without
            # source-file columns. Read that canonical evidence; never infer a
            # particular source row merely from batch membership.
            audit_record_id = rec.journal_entry_id if record_type_upper == "JOURNAL_LINE" else record_id
            audit_type = "JOURNAL_ENTRY" if record_type_upper == "JOURNAL_LINE" else record_type_upper
            audits = session.query(AuditEvent).filter(
                AuditEvent.organization_id == self.organization_id,
                AuditEvent.import_batch_id == import_batch_id,
                AuditEvent.event_type == "INGEST_IMPORTED",
                AuditEvent.details["record_id"].as_string() == audit_record_id,
                AuditEvent.details["entity_type"].as_string() == audit_type,
            ).order_by(AuditEvent.created_at, AuditEvent.id).all() if import_batch_id else []
            evidence = []
            for audit in audits:
                detail = audit.details
                file = session.get(SourceFile, detail.get("source_file_id")) if detail.get("source_file_id") else None
                if not file or file.import_batch_id != import_batch_id or file.import_batch.organization_id != self.organization_id:
                    continue
                evidence.append({"audit_event_id": audit.id, "source_file_id": file.id,
                                 "source_row_identifier": detail.get("source_row_identifier"),
                                 "source_metadata": detail.get("lineage", {})})
            lineage["ingestion_evidence"] = evidence
            if evidence:
                file_ids = {item["source_file_id"] for item in evidence}
                row_ids = {item["source_row_identifier"] for item in evidence}
                if not source_file_id and len(file_ids) == 1:
                    source_file_id = next(iter(file_ids))
                if not source_row_identifier and len(row_ids) == 1:
                    lineage["source_row_identifier"] = next(iter(row_ids))

            # Resolve source file
            if source_file_id:
                sf = session.get(SourceFile, source_file_id)
                if sf and sf.import_batch.organization_id == self.organization_id:
                    lineage["source_file"] = {
                        "id": sf.id,
                        "original_filename": sf.original_filename,
                        "relative_raw_path": sf.relative_raw_path,
                        "sha256": sf.sha256,
                        "byte_size": sf.byte_size,
                        "media_type": sf.media_type,
                        "parse_status": sf.parse_status,
                    }
                    # Use source file's import_batch_id if not already set
                    if not import_batch_id:
                        import_batch_id = sf.import_batch_id

            # Resolve import batch and source system
            if import_batch_id:
                batch = session.get(ImportBatch, import_batch_id)
                if batch and batch.organization_id == self.organization_id:
                    lineage["import_batch"] = {
                        "id": batch.id,
                        "status": batch.status,
                        "file_count": batch.file_count,
                        "total_rows": batch.total_rows,
                        "valid_rows": batch.valid_rows,
                        "error_rows": batch.error_rows,
                        "started_at": self._serialize_datetime(batch.started_at),
                        "completed_at": self._serialize_datetime(batch.completed_at),
                    }
                    # Batch-level provenance only: these are not asserted to be row-level sources.
                    lineage["batch_source_files"] = [
                        {"id": file.id, "original_filename": file.original_filename,
                         "sha256": file.sha256, "relative_raw_path": file.relative_raw_path}
                        for file in sorted(batch.source_files, key=lambda file: file.id)]
                    ss = session.get(SourceSystem, batch.source_system_id)
                    if ss and ss.organization_id == self.organization_id:
                        lineage["source_system"] = {
                            "id": ss.id,
                            "adapter_key": ss.adapter_key,
                            "source_type": ss.source_type,
                            "display_name": ss.display_name,
                            "is_active": ss.is_active,
                        }

            return lineage
        finally:
            session.close()

    async def query_accrual_accounts(self, fiscal_period: str) -> List[Dict[str, Any]]:
        """Detect active accrual accounts with posted activity in the selected period."""
        from app.database.models import Account, JournalEntry, JournalLine
        start, end = period_bounds(fiscal_period)
        session = self._get_session()
        try:
            rows = (session.query(Account)
                .join(JournalLine, JournalLine.account_id == Account.id)
                .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
                .filter(Account.organization_id == self.organization_id,
                    JournalEntry.organization_id == self.organization_id,
                    Account.is_active.is_(True), JournalEntry.status == "POSTED",
                    JournalEntry.currency_code == Account.currency_code,
                    or_(Account.account_name.ilike("%accru%"), JournalEntry.entry_type == "ACCRUAL"),
                    ledger_period_filter(JournalEntry.fiscal_period, JournalEntry.entry_date, fiscal_period))
                .distinct().order_by(Account.account_code).all())
            return [{"account_code": row.account_code, "account_name": row.account_name} for row in rows]
        finally:
            session.close()
