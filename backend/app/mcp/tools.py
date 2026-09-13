"""
MCP Tool Definitions for Controlled Financial Data Access

Agents call these tools to inspect GL entries, bank lines, and exception records.
All public tool parameters are JSON-serializable (str, int). SQLAlchemy sessions
are managed internally and guaranteed to close via try/finally.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session


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
    # BLOCKED — period-to-date-range contract not yet defined
    # ------------------------------------------------------------------

    async def get_account_balance(self, account_code: str, period: str) -> Dict[str, Any]:
        """Blocked until an agreed period/date-range and opening-balance contract exists."""
        raise NotImplementedError("get_account_balance requires an agreed period/date-range contract")

    async def query_gl_transactions(self, account_code: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Canonical postings only; signed amount is debit minus credit.

        Original debit/credit columns and draft status remain visible. No source
        filenames, headers or ERP transformations are used by this query.
        """
        from app.database.models import Account, JournalEntry, JournalLine
        self._validate_limit(limit)
        session = self._get_session()
        try:
            rows = (session.query(JournalLine, JournalEntry, Account)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .join(Account, JournalLine.account_id == Account.id)
                .filter(Account.account_code == account_code,
                        Account.organization_id == self.organization_id,
                        JournalEntry.organization_id == self.organization_id,
                        JournalEntry.currency_code == Account.currency_code)
                .order_by(JournalEntry.entry_date.desc(), JournalLine.id)
                .limit(limit).all())
            return [{'id':line.id,'source':'GL','account_code':account.account_code,
                     'transaction_date':self._serialize_datetime(entry.entry_date),
                     'amount':float(line.debit_amount-line.credit_amount),
                     'debit_amount':str(line.debit_amount),'credit_amount':str(line.credit_amount),
                     'currency_code':entry.currency_code,'entry_status':entry.status,
                     'description':line.description or entry.description,'reference':entry.reference,
                     'is_reconciled':line.is_reconciled} for line,entry,account in rows]
        finally:
            session.close()

    async def query_bank_transactions(self, account_code: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Independent canonical bank statements linked to the requested GL account."""
        from app.database.models import Account, BankAccount, BankTransaction
        self._validate_limit(limit)
        session = self._get_session()
        try:
            rows = (session.query(BankTransaction, Account)
                .join(BankAccount, BankTransaction.bank_account_id == BankAccount.id)
                .join(Account, BankAccount.linked_gl_account_id == Account.id)
                .filter(Account.account_code == account_code,
                        Account.organization_id == self.organization_id,
                        BankAccount.organization_id == self.organization_id,
                        BankTransaction.currency_code == BankAccount.currency_code,
                        BankAccount.currency_code == Account.currency_code)
                .order_by(BankTransaction.booking_date.desc(), BankTransaction.id)
                .limit(limit).all())
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
        self, category: Optional[str] = None, status: Optional[str] = None, limit: int = 50
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
            rows = query.order_by(FixedAsset.asset_name.asc(), FixedAsset.id).limit(limit).all()
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
        self, vendor_name: Optional[str] = None, status: Optional[str] = None, limit: int = 50
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
            rows = query.order_by(APInvoice.invoice_date.desc(), APInvoice.id).limit(limit).all()
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
