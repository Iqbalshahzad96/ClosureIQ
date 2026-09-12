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

    def __init__(self, session_factory: Optional[Callable[[], Session]] = None) -> None:
        self._session_factory = session_factory

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
        """Fetch balance for a given account code and period.

        .. warning::

            **Not implemented.** ``FinancialRecord`` has no ``period`` or
            ``currency`` column. Returning an all-time sum as a period
            balance would be silently incorrect. This tool is blocked
            until the team agrees on a period-string → date-range mapping
            and a currency source.

        Raises
        ------
        NotImplementedError
            Always. This tool must not be registered until the contract is resolved.
        """
        raise NotImplementedError(
            "get_account_balance is blocked: FinancialRecord has no 'period' or "
            "'currency' column. A period-to-date-range mapping contract must be "
            "agreed upon before this tool can be implemented."
        )

    # ------------------------------------------------------------------
    # Implemented tools
    # ------------------------------------------------------------------

    async def query_gl_transactions(
        self, account_code: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Query general ledger line items filtered by account code.

        Parameters
        ----------
        account_code : str
            The account code to filter on.
        limit : int
            Maximum number of rows to return (default 50).

        Returns
        -------
        list[dict]
            Each dict contains: id, source, account_code, transaction_date
            (ISO-8601), amount, description, reference, is_reconciled.
        """
        from app.database.models import FinancialRecord

        self._validate_limit(limit)
        session = self._get_session()
        try:
            rows = (
                session.query(FinancialRecord)
                .filter(
                    FinancialRecord.source == "GL",
                    FinancialRecord.account_code == account_code,
                )
                .order_by(FinancialRecord.transaction_date.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "source": r.source,
                    "account_code": r.account_code,
                    "transaction_date": self._serialize_datetime(r.transaction_date),
                    "amount": r.amount,
                    "description": r.description,
                    "reference": r.reference,
                    "is_reconciled": r.is_reconciled,
                }
                for r in rows
            ]
        finally:
            session.close()

    async def query_bank_transactions(
        self, account_code: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Query bank statement line items filtered by account code.

        Parameters
        ----------
        account_code : str
            The account code to filter on.
        limit : int
            Maximum number of rows to return (default 50).

        Returns
        -------
        list[dict]
            Same schema as ``query_gl_transactions``.
        """
        from app.database.models import FinancialRecord

        self._validate_limit(limit)
        session = self._get_session()
        try:
            rows = (
                session.query(FinancialRecord)
                .filter(
                    FinancialRecord.source == "BANK",
                    FinancialRecord.account_code == account_code,
                )
                .order_by(FinancialRecord.transaction_date.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "source": r.source,
                    "account_code": r.account_code,
                    "transaction_date": self._serialize_datetime(r.transaction_date),
                    "amount": r.amount,
                    "description": r.description,
                    "reference": r.reference,
                    "is_reconciled": r.is_reconciled,
                }
                for r in rows
            ]
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
                "amount_variance": record.amount_variance,
                "description": record.description,
                "status": record.status,
                "created_at": self._serialize_datetime(record.created_at),
                "found": True,
            }
        finally:
            session.close()
