"""
MCP Tool Definitions for Controlled Financial Data Access

Agents call these tools to inspect GL entries, bank lines, accruals, and ledger balances.
"""

from typing import Dict, Any, List


class FinancialMCPTools:
    """Collection of MCP tools exposed to AI agents."""

    @staticmethod
    async def get_account_balance(account_code: str, period: str) -> Dict[str, Any]:
        """Fetch balance for a given account code and period."""
        return {
            "account_code": account_code,
            "period": period,
            "balance": 0.0,
            "currency": "USD"
        }

    @staticmethod
    async def query_gl_transactions(account_code: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Query general ledger line items with limit."""
        return []

    @staticmethod
    async def get_exception_details(exception_id: str) -> Dict[str, Any]:
        """Fetch details for a specific financial exception."""
        return {"exception_id": exception_id, "found": False}
