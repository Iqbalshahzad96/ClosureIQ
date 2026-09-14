"""
MCP Server Instance & Tool Registration

Uses the MCP Python SDK v2 (mcp==2.1.1) MCPServer class to register
financial data access tools with proper decorator-based registration.
"""

from __future__ import annotations

from typing import Optional

from mcp.server import MCPServer

from app.database.database import SessionLocal
from app.mcp.tools import FinancialMCPTools


# ---------------------------------------------------------------------------
# Module-level instances
# ---------------------------------------------------------------------------

mcp = MCPServer("closureiq-mcp")

# Default tool collection wired to the application SessionLocal factory.
_tools = FinancialMCPTools(session_factory=SessionLocal)


# ---------------------------------------------------------------------------
# Registered MCP tools — canonical financial data access
# ---------------------------------------------------------------------------


@mcp.tool()
async def query_gl_transactions(account_code: str, limit: int = 50, fiscal_period: Optional[str] = None) -> list[dict]:
    """Query general ledger line items filtered by account code.

    Returns up to ``limit`` GL transactions for the given account,
    ordered by transaction_date descending.
    """
    return await _tools.query_gl_transactions(account_code=account_code, limit=limit, fiscal_period=fiscal_period)


@mcp.tool()
async def query_bank_transactions(account_code: str, limit: int = 50) -> list[dict]:
    """Query bank statement line items filtered by account code.

    Returns up to ``limit`` BANK transactions for the given account,
    ordered by transaction_date descending.
    """
    return await _tools.query_bank_transactions(account_code=account_code, limit=limit)


@mcp.tool()
async def get_exception_details(exception_id: str) -> dict:
    """Fetch details for a specific financial exception by its ID.

    Returns all exception fields plus a ``found`` boolean.
    """
    return await _tools.get_exception_details(exception_id=exception_id)


@mcp.tool()
async def get_account_balance(account_code: str, period: str) -> dict:
    """Retrieve the canonical balance for an account in a fiscal period.

    Looks up TrialBalanceRecord first; falls back to JournalLine aggregation.
    """
    return await _tools.get_account_balance(account_code=account_code, period=period)


@mcp.tool()
async def query_chart_of_accounts(
    account_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
) -> list[dict]:
    """Query canonical chart of accounts with optional type and status filters."""
    return await _tools.query_chart_of_accounts(
        account_type=account_type, is_active=is_active, limit=limit
    )


@mcp.tool()
async def query_trial_balance(
    fiscal_period: Optional[str] = None,
    account_code: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query canonical trial balance records with account details."""
    return await _tools.query_trial_balance(
        fiscal_period=fiscal_period, account_code=account_code, limit=limit
    )


@mcp.tool()
async def query_fixed_assets(
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query canonical fixed assets register records."""
    return await _tools.query_fixed_assets(category=category, status=status, limit=limit)


@mcp.tool()
async def query_ap_invoices(
    vendor_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query canonical accounts payable invoices."""
    return await _tools.query_ap_invoices(vendor_name=vendor_name, status=status, limit=limit)


@mcp.tool()
async def query_exceptions(
    period: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query financial exceptions with optional filters."""
    return await _tools.query_exceptions(
        period=period, category=category, severity=severity, limit=limit
    )


@mcp.tool()
async def query_journal_entries(
    fiscal_period: Optional[str] = None,
    entry_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Query canonical journal entries (headers) with optional filters."""
    return await _tools.query_journal_entries(
        fiscal_period=fiscal_period, entry_type=entry_type, limit=limit
    )


@mcp.tool()
async def query_accounting_periods() -> list[dict]:
    """Return fiscal periods present in canonical trial balances or journals."""
    return await _tools.query_accounting_periods()


@mcp.tool()
async def query_import_batches(
    status: Optional[str] = None, limit: int = 50
) -> list[dict]:
    """Query canonical import batch metadata."""
    return await _tools.query_import_batches(status=status, limit=limit)


@mcp.tool()
async def get_record_lineage(record_type: str, record_id: str) -> dict:
    """Trace a canonical record back to source file, import batch, and source system."""
    return await _tools.get_record_lineage(record_type=record_type, record_id=record_id)
