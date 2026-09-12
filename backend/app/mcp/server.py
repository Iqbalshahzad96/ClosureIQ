"""
MCP Server Instance & Setup
"""

from typing import Any, Dict


class MCPServerManager:
    """Manages the lifecycle of the Python MCP server for financial tools."""

    def __init__(self, server_name: str = "closureiq-mcp") -> None:
        self.server_name = server_name

    def initialize_server(self) -> Dict[str, Any]:
        """Initialize MCP tool registry."""
        return {
            "server": self.server_name,
            "status": "ready",
            "registered_tools": [
                "get_account_balance",
                "query_gl_transactions",
                "get_exception_details"
            ]
        }
