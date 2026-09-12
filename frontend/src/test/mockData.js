/**
 * Deterministic test fixtures for ClosureIQ dashboard tests.
 */

export const mockReconciliationSummary = {
  run_id: 'run-2026-03-001',
  workflow_type: 'reconciliation',
  period: '2026-Q1',
  status: 'clean_close',
  total_latency_ms: 245.8,
  validation_results: { match_rate: 1.0 },
  exceptions_count: 0,
  exceptions: [],
  agent_1_review: { status: 'passed' },
  agent_2_analyses: [],
  policy_contexts: [],
  recommendations_count: 0,
  recommendations: [],
  financial_data: {},
  input_params: {},
  hitl_decision: {},
  errors: [],
  trace_log: [],
  created_at: '2026-03-12T10:30:00Z',
};

export const mockIdleSummary = {
  status: 'idle',
  total_runs: 0,
  message: 'No workflow runs executed yet',
};

export const mockExceptions = [
  {
    id: 'exc-1',
    period: '2026-Q1',
    category: 'RECONCILIATION',
    severity: 'HIGH',
    amount_variance: 4500.0,
    description: 'Unmatched deposit in operating bank account',
    status: 'OPEN',
    created_at: '2026-03-12T11:00:00Z',
  },
  {
    id: 'exc-2',
    period: '2026-Q1',
    category: 'ACCRUAL',
    severity: 'CRITICAL',
    amount_variance: 12000.5,
    description: 'Missing payroll accrual for bonus payout',
    status: 'OPEN',
    created_at: '2026-03-12T11:05:00Z',
  },
  {
    id: 'exc-3',
    period: '2026-Q1',
    category: 'DEPRECIATION',
    severity: 'MEDIUM',
    amount_variance: 340.0,
    description: 'Useful life discrepancy on IT equipment',
    status: 'IN_REVIEW',
    created_at: '2026-03-12T11:10:00Z',
  },
  {
    id: 'exc-4',
    period: '2026-Q1',
    category: 'RECONCILIATION',
    severity: 'LOW',
    amount_variance: 25.0,
    description: 'Minor bank fee timing difference',
    status: 'RESOLVED',
    created_at: '2026-03-12T09:00:00Z',
  },
];

export const mockPendingApprovals = [
  {
    run_id: 'run-2026-03-002',
    workflow_type: 'accrual',
    period: '2026-Q1',
    exceptions_count: 2,
    recommendations: [
      'Post adjusting journal entry for vendor software licenses',
      'Verify recurring contract terms for quarterly billing',
    ],
  },
];

export const mockObservabilityMetrics = {
  total_runs: 14,
  avg_latency_ms: 320.5,
  total_token_usage: 45200,
  error_count: 1,
  hitl_approvals_count: 6,
};

export const mockObservabilityRuns = [
  {
    run_id: 'run-2026-03-002',
    workflow_type: 'accrual',
    period: '2026-Q1',
    status: 'hitl_pending',
    exceptions_count: 2,
    recommendations_count: 2,
    created_at: '2026-03-12T12:00:00Z',
  },
  {
    run_id: 'run-2026-03-001',
    workflow_type: 'reconciliation',
    period: '2026-Q1',
    status: 'clean_close',
    exceptions_count: 0,
    recommendations_count: 0,
    created_at: '2026-03-12T10:30:00Z',
  },
];

export const mockMalformedSummary = {
  run_id: null,
  workflow_type: undefined,
  total_latency_ms: 'invalid_number',
  exceptions_count: NaN,
  recommendations_count: 'none',
  created_at: 'invalid-date',
};

export const mockMalformedExceptions = 'not-an-array';

export const mockMalformedApprovals = null;

export const mockMalformedMetrics = {
  total_runs: 'ten',
  avg_latency_ms: NaN,
  total_token_usage: -5,
  error_count: Infinity,
  hitl_approvals_count: null,
};

export const mockMalformedRuns = [
  {
    run_id: 'run-corrupt',
    created_at: 'not-a-date',
  },
  null,
];

