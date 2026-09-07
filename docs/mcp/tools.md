# Model Context Protocol (MCP) Tool Specifications

## Overview
Exposes a controlled tool interface for AI agents to query SQLite database models without giving raw SQL injection or direct unrestricted table access.

All tool parameters are JSON-serializable (`str`, `int`). SQLAlchemy sessions are managed internally by the tool layer and never exposed to callers. All `datetime` values are serialized as ISO-8601 strings.

## Limit Parameter

Both `query_gl_transactions` and `query_bank_transactions` accept an optional `limit` parameter:
- **Default:** `50`
- **Accepted range:** `1` through `100` inclusive
- **Invalid values** (less than 1 or greater than 100) raise a tool error (`ValueError`) with the message: `"limit must be between 1 and 100"`
- Validation occurs before any database session is opened.

## Registered MCP Tools

### 1. `query_gl_transactions(account_code: str, limit: int = 50)`
Returns filtered General Ledger line items for the given account code.
- Filters: `source="GL"`, `account_code` match
- Ordering: `transaction_date` descending
- Limit: default `50`, accepted range `1–100`, invalid values raise a tool error
- Returns: `list[{id, source, account_code, transaction_date, amount, description, reference, is_reconciled}]`

### 2. `query_bank_transactions(account_code: str, limit: int = 50)`
Returns filtered Bank Statement line items for the given account code.
- Filters: `source="BANK"`, `account_code` match
- Ordering: `transaction_date` descending
- Limit: default `50`, accepted range `1–100`, invalid values raise a tool error
- Returns: same schema as `query_gl_transactions`

### 3. `get_exception_details(exception_id: str)`
Returns structured anomaly record by primary key.
- Returns: `{exception_id, period, category, severity, amount_variance, description, status, created_at, found}`
- `found` is `false` if no record exists for the given ID.

## Pending / Blocked Tools

### `get_account_balance(account_code: str, period: str)` — NOT REGISTERED
**Status: Blocked**

This tool is not implemented or registered because:
1. `FinancialRecord` has no `period` column — there is no agreed-upon mapping from a period string (e.g. `"2026-Q1"`) to a `transaction_date` range.
2. `FinancialRecord` has no `currency` column — returning a hardcoded currency would be incorrect.

Returning an all-time sum and pretending it is a period balance is explicitly prohibited.

**Resolution required:** The team must agree on a period-to-date-range contract and decide whether currency is added to the model or sourced externally before this tool can be implemented.