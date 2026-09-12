# Observability and audit

[Project entry point](../../README.md) | [Architecture and setup](../architecture/overview.md) | [Ingestion](../ingestion/pipeline.md)

## Implemented behavior

Console logging and graph-state node traces record timing and errors. Logger, metrics and tracer helpers exist, but they are not a complete persisted operational telemetry pipeline. Workflow checkpoints, summaries and locks use process memory; restarting loses pending approvals.

Financial ingestion separately persists `INGEST_CONTROL`, `INGEST_IMPORTED`, `INGEST_QUARANTINED` and `INGEST_FILE_FAILED` audit events. Details preserve batch/file/sheet/row context, record IDs and diagnostics. Import logs contain status/counts, not raw financial row contents. Returned diagnostics are capped at 100 warnings and 100 errors; full row events persist. Raw copies use exclusive creation and path validation; neither files nor audit metadata have database/OS-enforced immutability.

Sources: [observability helpers](../../backend/app/observability), [nodes](../../backend/app/orchestrator/nodes.py), [workflow service](../../backend/app/services/workflow_service.py), [ingestion service](../../backend/app/ingestion/service.py), [models](../../backend/app/database/models.py).

## Placeholder endpoints

| Endpoint under `/api/v1` | Current response |
|---|---|
| `GET /observability/metrics` | Static zero totals for runs, latency, tokens, errors and approvals. |
| `GET /observability/runs` | Empty list. |
| `GET /observability/runs/{run_id}` | Supplied ID with static completed status, empty execution/tool/retrieval arrays and no human decision. |

These responses are not actual run evidence. See [routes](../../backend/app/api/routes/observability.py). Real in-memory workflow summaries use `/reconciliation/summary`; see [API](../api/endpoints.md).

## Remaining work

Durable run recovery, token/cost collection, MCP/RAG span correlation, authenticated reviewer identity and persisted HITL decisions are unfinished. Approval changes graph state; it does not currently create an `AuditEvent`. The previous guide's complete run-to-agent-to-tool-to-policy-to-human audit trail described intended coverage, not implemented behavior. See [HITL paths](../agents/specifications.md) and [ingestion lineage](../ingestion/pipeline.md).
