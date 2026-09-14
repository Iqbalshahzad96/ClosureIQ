# HTTP API

[Project entry point](../../README.md) | [Architecture and setup](../architecture/overview.md) | [Ingestion](../ingestion/pipeline.md)

The default prefix is `/api/v1`; FastAPI exposes interactive schemas at `http://localhost:8000/docs`. Health is also registered at `/health`. Request/response schemas in code are authoritative. Browser workflow controls are not yet connected, and reviewer identity is caller-supplied rather than authenticated.

## Endpoints and current status

| Method and path under `/api/v1` | Behavior |
|---|---|
| `GET /health` | Health response; does not establish database/data/provider readiness. |
| `POST /imports/upload` | Implemented financial CSV/Excel upload; raw body, 25 MiB cap. |
| `POST /reconciliation/run` | Runs reconciliation, accrual or depreciation and the shared exception/agent/HITL workflow. |
| `GET /reconciliation/summary` | In-memory workflow summary; optional `run_id`. |
| `GET /exceptions/` | Persisted exception list. |
| `GET /exceptions/{exception_id}` | Persisted exception detail. |
| `GET /approvals/pending` | Lists interrupted runs. |
| `POST /approvals/{run_id}/decision` | Approves/rejects and resumes an interrupted thread. |
| `POST /rag/ingest/text` | JSON policy text ingestion. |
| `POST /rag/ingest/directory` | Ingests a server directory; not browser multipart upload. |
| `POST /rag/query` | Retrieves policy evidence and formatted citations. |
| `GET /rag/documents` | Lists indexed policy documents. |
| `DELETE /rag/documents/{doc_id}` | Removes a document's chunks. |
| `GET /insights/` | Placeholder empty list. |
| `POST /insights/generate` | Placeholder queued response/ID; does not start analysis. Use `/reconciliation/run`. |
| `GET /observability/metrics` | Placeholder metrics. |
| `GET /observability/runs` | Placeholder empty list. |
| `GET /observability/runs/{run_id}` | Placeholder trace. |

Sources: [route modules](../../backend/app/api/routes), [application registration](../../backend/app/main.py).

## Financial uploads

Use `filename` query parameter; `organization_id` defaults to `default_org`. `source_system_id` is optional; when omitted, a dedicated runtime source system isolated by organization and approved adapter is automatically created or reused. When an explicit `source_system_id` is provided, it must belong to the organization and be active. Optional `adapter_key` and `batch_id` select an adapter/bind a batch. `X-Import-Options` accepts a JSON object such as `{"bank_account_id":"demo-bank","currency_code":"KES"}`. Send CSV/Excel bytes directly, not multipart. Configure canonical sources/accounts/mappings first when using explicit source IDs.

The response is an ingestion summary with batch/file IDs, status, row counts and diagnostics. A summary can report FAILED, QUARANTINED or PARTIAL even when HTTP succeeds: inspect the status. Invalid options return 422, oversize input 413, rejected service arguments 400 and unexpected import failures a generic 500. See the [ingestion contract and executable example](../ingestion/pipeline.md) and [route](../../backend/app/api/routes/imports.py).

## Workflow and approval contracts

`workflow_type` selects `reconciliation`, `accrual` or `depreciation`. Reconciliation uses `account_code`, optional `period`, `limit` and `run_id`; accrual requires nonempty `accrual_entries` and `historical_baseline`; depreciation requires nonempty `asset_records` and `period_posted_depreciation`. Supplied period does not currently filter transaction query dates. See [financial rules](../financial_engine/rules.md).

Approval accepts `decision` (`approved`/`rejected`, case-insensitive), `reviewer` and `comments`. Invalid decisions return 400, schema errors 422, absent runs 404 and completed/repeated resumes 409. Duplicate run IDs return 409. Both decisions finalize the run without posting journals or persisting a durable approval audit. See [graph routes and HITL](../agents/specifications.md) and [request schemas](../../backend/app/api/routes/approvals.py).

## Synthetic workflow example

The following is **synthetic supplied input**, not ERP evidence. Submit through Swagger to `POST /api/v1/reconciliation/run`:

```json
{
  "workflow_type": "accrual",
  "period": "DEMO",
  "accrual_entries": [{"vendor": "demo-rent", "amount": 1000}],
  "historical_baseline": {"demo-rent": 1000}
}
```

Equal values exercise the clean branch; change the entry to 2000 for the exception branch, which requires Agent 1 model access. Query `/api/v1/reconciliation/summary?run_id=...`; when `hitl_pending`, submit to `/api/v1/approvals/{run_id}/decision`:

```json
{"decision":"approved","reviewer":"Demo reviewer","comments":"Synthetic scenario reviewed"}
```

Use `rejected` on a separate paused run; completed runs cannot be resumed again. Sources: [run request](../../backend/app/api/routes/reconciliation.py), [approval request](../../backend/app/api/routes/approvals.py).


See [policy pipeline](../rag/pipeline.md) and [telemetry](../observability/telemetry.md) for their endpoint limitations.
