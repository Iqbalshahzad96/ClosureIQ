"""
MCP Controlled Data Access Layer Tests
"""

import asyncio
from app.mcp.server import MCPServerManager
from app.mcp.tools import FinancialMCPTools


def test_mcp_server_initialization():
    manager = MCPServerManager()
    server_info = manager.initialize_server()
    assert server_info["server"] == "closureiq-mcp"
    assert "get_account_balance" in server_info["registered_tools"]


def test_mcp_tools():
    balance_info = asyncio.run(FinancialMCPTools.get_account_balance("1010", "2026-Q1"))
    assert balance_info["account_code"] == "1010"
    assert balance_info["balance"] == 0.0

    txns = asyncio.run(FinancialMCPTools.query_gl_transactions("1010"))
    assert isinstance(txns, list)

    exc = asyncio.run(FinancialMCPTools.get_exception_details("exc_123"))
    assert exc["exception_id"] == "exc_123"
