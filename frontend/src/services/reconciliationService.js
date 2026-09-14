/**
 * Reconciliation & Financial Close Workflow Service.
 *
 * Communicates with FastAPI backend for:
 * - Running financial close workflows (reconciliation, accrual, depreciation, ap_review)
 * - Fetching workflow results & summaries
 * - Fetching pending approvals (HITL)
 * - Submitting human review decisions (Approve / Reject)
 * - Fetching detected financial exceptions
 * - Fetching detailed run traces & audit logs
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export async function runWorkflow({
  workflowType = 'reconciliation',
  period = '2026-Q1',
  accountCode,
  limit = 50,
  extraParams = {},
  signal,
}) {
  const url = `${BASE_URL}/reconciliation/run`;
  const payload = {
    workflow_type: workflowType,
    period: period || '2026-Q1',
    limit: Number(limit) || 50,
    ...extraParams,
  };

  if (accountCode && !payload.account_code) {
    payload.account_code = accountCode;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    let errorDetail = '';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || '';
    } catch {
      errorDetail = await response.text().catch(() => '');
    }
    throw new Error(errorDetail || `Workflow failed with status ${response.status}`);
  }

  return await response.json();
}

export async function fetchWorkflowSummary(runId, { signal } = {}) {
  const query = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
  const url = `${BASE_URL}/reconciliation/summary${query}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch workflow summary (${response.status})`);
  }

  return await response.json();
}

export async function fetchPendingApprovals({ signal } = {}) {
  const url = `${BASE_URL}/approvals/pending`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch pending approvals (${response.status})`);
  }

  return await response.json();
}

export async function submitApprovalDecision({
  runId,
  decision,
  reviewer = 'Accountant',
  comments = '',
  signal,
}) {
  if (!runId) {
    throw new Error('runId is required to submit approval decision');
  }

  const url = `${BASE_URL}/approvals/${encodeURIComponent(runId)}/decision`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      decision,
      reviewer: reviewer || 'Accountant',
      comments: comments || '',
    }),
    signal,
  });

  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = data.detail || '';
    } catch {
      detail = await response.text().catch(() => '');
    }
    throw new Error(detail || `Decision submission failed (${response.status})`);
  }

  return await response.json();
}

export async function fetchExceptions({ period, status, category, limit = 100, signal } = {}) {
  const params = new URLSearchParams();
  if (period) params.set('period', period);
  if (status) params.set('status', status);
  if (category) params.set('category', category);
  if (limit) params.set('limit', String(limit));

  const qs = params.toString();
  const url = `${BASE_URL}/exceptions/${qs ? `?${qs}` : ''}`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch exceptions (${response.status})`);
  }

  return await response.json();
}

export async function fetchObservabilityMetrics({ signal } = {}) {
  const url = `${BASE_URL}/observability/metrics`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch observability metrics (${response.status})`);
  }

  return await response.json();
}

export async function fetchObservabilityRuns({ signal } = {}) {
  const url = `${BASE_URL}/observability/runs`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch observability runs (${response.status})`);
  }

  return await response.json();
}

export async function fetchRunTrace(runId, { signal } = {}) {
  if (!runId) {
    throw new Error('runId is required');
  }

  const url = `${BASE_URL}/observability/runs/${encodeURIComponent(runId)}/trace`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch run trace (${response.status})`);
  }

  return await response.json();
}


