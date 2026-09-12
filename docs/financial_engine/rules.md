# Financial engine rules and workflows

[Project entry point](../../README.md) | [Architecture and setup](../architecture/overview.md) | [Ingestion](../ingestion/pipeline.md)

Deterministic Python engines perform financial checks; model output does not determine arithmetic. Current engines use floats even though canonical ingestion uses Decimal.

## Bank reconciliation — Partial end to end; canonical-data backend implemented

`POST /api/v1/reconciliation/run` accepts `workflow_type="reconciliation"`, `account_code`, optional `period`, `limit` and `run_id`. MCP reads canonical `journal_lines`/`journal_entries` joined to `accounts`, and `bank_transactions` joined through `bank_accounts.linked_gl_account_id`. Queries are organization-scoped (default `default_org`) and newest-first. GL signed amounts are derived as debit minus credit for the existing engine response contract, while original debit/credit strings and entry status are retained. Legacy `financial_records` are no longer read; existing legacy-only databases require migration/import before use. Default limit is 50, allowed range 1-100. The supplied period labels the workflow but **still does not filter transaction dates**. Draft ledger extracts can be queried; a matching result does not establish journal completeness.

Matching is greedy one-to-one: first normalized nonempty reference and amount within default 0.01, without checking dates; then amount within tolerance and a three-day window when both dates parse. Missing/unparseable dates permit amount-only fallback. Unmatched rows generate exceptions and enter analysis. The service does not persist canonical run/result rows or update reconciliation flags. Sources: [request schemas](../../backend/app/api/routes/reconciliation.py), [MCP tools](../../backend/app/mcp/tools.py), [engine](../../backend/app/financial_engine/reconciliation.py), [service](../../backend/app/services/workflow_service.py).

## Accrual review — Partial end to end; supplied-input backend implemented

The same run endpoint dispatches `workflow_type="accrual"` with nonempty `accrual_entries` and `historical_baseline`. The engine compares keyed expectations, detects material variance and missing recurring accruals, and creates exceptions. Default material variance requires more than 10% and at least 50 amount units. Baselines are supplied rather than calculated from imported history; no AP query is wired. Prefer vendor/account/name keys: the API accepts ID-only entries, but engine key extraction does not use `id`. Sources: [accrual engine](../../backend/app/financial_engine/accrual.py), [API](../../backend/app/api/routes/reconciliation.py), [dispatch](../../backend/app/services/workflow_service.py).

## Depreciation validation — Partial end to end; supplied-input backend implemented

Use `workflow_type="depreciation"`, nonempty `asset_records` and `period_posted_depreciation`. The engine calculates monthly `(cost - salvage_value) / useful_life_months`, handles invalid parameters/fully depreciated assets and compares expected/posted amounts with default tolerance 0.01. Discrepancies enter analysis. The ingestion service imports asset registers separately, but this workflow does not automatically query them or allocate category GL totals to assets, or implement a full acquisition/disposal/proration schedule. Use stable asset IDs: API-accepted asset-name-only inputs do not supply the engine's posting lookup ID. Sources: [engine](../../backend/app/financial_engine/depreciation.py), [API models](../../backend/app/api/routes/reconciliation.py).

## Exceptions and review

The exception generator uses default amount severity HIGH at 1,000, MEDIUM at 50, otherwise LOW, with supported overrides. See [exception generation](../../backend/app/financial_engine/exceptions.py) and [engine tests](../../backend/tests/financial_engine/test_engine.py). Exceptions enter the [agent and HITL workflow](../agents/specifications.md).

Earlier rules described reference/date/amount matching and calculated historical averages. The implementation ignores dates during reference matching and accepts caller-supplied accrual baselines. Imported AP/assets are not automatically queried by these workflows. See [ingestion](../ingestion/pipeline.md) for source validation, partial journals and quarantine rules.
