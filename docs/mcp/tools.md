# MCP tool contracts

[Project entry point](../../README.md) | [Architecture and setup](../architecture/overview.md) | [Ingestion](../ingestion/pipeline.md)

`MCPServer` registers three SQLAlchemy-backed tools. The workflow calls `FinancialMCPTools` in-process; it does not make an MCP transport round trip. No standalone transport launch command is supplied. API exception queries and ingestion also use SQLAlchemy directly, so database access is not exclusively through MCP.

Sources: [registration](../../backend/app/mcp/server.py), [tools](../../backend/app/mcp/tools.py), [workflow service](../../backend/app/services/workflow_service.py).

## Shared query contract

Both transaction queries accept `account_code: str` and `limit: int = 50`. Limits outside 1-100 raise `ValueError("limit must be between 1 and 100")` before opening a session. Sessions are managed internally, dates serialize as ISO-8601 or null, and results are newest-first with ID ordering for ties. The tool instance scopes queries to `organization_id`, default `default_org`.

## Registered tools

| Tool | Canonical query and result |
|---|---|
| `query_gl_transactions(account_code, limit=50)` | Joins `journal_lines`, `journal_entries` and `accounts`; filters account code, account/entry organization and matching currency. Orders by entry date then line ID. Includes DRAFT extracts. |
| `query_bank_transactions(account_code, limit=50)` | Joins `bank_transactions` to `bank_accounts` and its linked GL account. Filters account code, organization and matching transaction/bank/GL currencies. Orders by booking date then transaction ID. |
| `get_exception_details(exception_id)` | Finds an exception by primary key; returns `exception_id`, `period`, `category`, `severity`, `amount_variance`, `description`, `status`, `created_at`, `found`. Missing IDs return `found=false`. |

Transaction output shares `id`, `source` (`GL`/`BANK`), `account_code`, `transaction_date`, `amount`, `description`, `reference`, `is_reconciled` and `currency_code`. GL output also carries original `debit_amount`/`credit_amount` strings and `entry_status`; its float `amount` is debit minus credit. Bank output uses its signed statement amount.

`financial_records` is retained for schema compatibility but is no longer read. Existing legacy-only data needs migration/import. ERP column/layout handling stays in [adapters](../ingestion/pipeline.md), not tools or agents. Queries still cap rows and do not accept a period/date filter; matching does not prove financial coverage or complete vouchers.

## Blocked balance tool

`get_account_balance(account_code, period)` raises `NotImplementedError` and is not registered. It requires an agreed period/date-range and opening-balance contract. The previous guide's explanation based on missing legacy currency columns is obsolete: canonical models now contain currencies, but the balance contract remains unresolved.

Tests: [MCP](../../backend/tests/mcp/test_mcp.py), [canonical ingestion consumption](../../backend/tests/ingestion/test_service_integration.py).
