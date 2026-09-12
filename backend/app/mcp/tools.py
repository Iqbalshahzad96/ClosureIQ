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
