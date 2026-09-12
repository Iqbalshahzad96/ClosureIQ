"""
MCP Server Instance & Tool Registration

Uses the MCP Python SDK v2 (mcp==2.1.1) MCPServer class to register
financial data access tools with proper decorator-based registration.
"""

from __future__ import annotations

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
# Registered MCP tools (3 implemented, 1 blocked)
# ---------------------------------------------------------------------------
# NOTE: get_account_balance is intentionally NOT registered.
#       It raises NotImplementedError because the period-to-date-range
#       mapping contract has not been agreed upon, and FinancialRecord
#       has no period or currency column.
# ---------------------------------------------------------------------------


@mcp.tool()
async def query_gl_transactions(account_code: str, limit: int = 50) -> list[dict]:
    """Query general ledger line items filtered by account code.

    Returns up to ``limit`` GL transactions for the given account,
    ordered by transaction_date descending.
    """
    return await _tools.query_gl_transactions(account_code=account_code, limit=limit)


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
