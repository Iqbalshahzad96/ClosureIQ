# ClosureIQ API Documentation

## Base URL
`/api/v1`

## Endpoints

### Health
- `GET /health` : System health status.

### Reconciliation
- `POST /api/v1/reconciliation/run` : Trigger deterministic reconciliation.
- `GET /api/v1/reconciliation/summary` : Retrieve summary metrics.

### Exceptions
- `GET /api/v1/exceptions/` : List detected financial exceptions.
- `GET /api/v1/exceptions/{exception_id}` : Get detail of specific exception.

### Insights & AI
- `GET /api/v1/insights/` : Get agent insights and recommendations.
- `POST /api/v1/insights/generate` : Trigger agent analysis workflow.

### Human-in-the-Loop Approvals
- `GET /api/v1/approvals/pending` : List items awaiting approval.
- `POST /api/v1/approvals/{item_id}/decision` : Submit approval or rejection.

### Observability
- `GET /api/v1/observability/metrics` : Performance metrics & token usage.
- `GET /api/v1/observability/runs` : List orchestrator runs.
- `GET /api/v1/observability/runs/{run_id}` : Get trace details for a run.
