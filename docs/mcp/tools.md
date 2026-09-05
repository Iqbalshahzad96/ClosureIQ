# Model Context Protocol (MCP) Tool Specifications

## Overview
Exposes a controlled tool interface for AI agents to query SQLite database models without giving raw SQL injection or direct unrestricted table access.

## Registered MCP Tools
1. `get_account_balance(account_code: str, period: str)`: Returns GL balance and currency.
2. `query_gl_transactions(account_code: str, limit: int = 50)`: Returns filtered GL line items.
3. `get_exception_details(exception_id: str)`: Returns structured anomaly record.
