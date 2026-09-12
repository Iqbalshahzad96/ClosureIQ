/**
 * Pure normalization and safety utilities for ClosureIQ dashboard data.
 * Defensively handles null, undefined, NaN, Infinity, and malformed inputs.
 */

export function isFiniteNumber(val) {
  return typeof val === 'number' && Number.isFinite(val);
}

export function parseFiniteNumber(val, fallback = 0) {
  if (isFiniteNumber(val)) return val;
  if (typeof val === 'string' && val.trim() !== '') {
    const num = Number(val);
    if (Number.isFinite(num)) return num;
  }
  return fallback;
}

export function isValidDate(val) {
  if (!val || typeof val !== 'string') return false;
  const d = new Date(val);
  return !isNaN(d.getTime());
}

export function formatLatency(latencyMs) {
  if (latencyMs === null || latencyMs === undefined || !Number.isFinite(latencyMs)) {
    return 'N/A';
  }
  if (latencyMs < 1000) {
    return `${Math.round(latencyMs)} ms`;
  }
  return `${(latencyMs / 1000).toFixed(2)} s`;
}

export function normalizeSummary(data) {
  if (!data || typeof data !== 'object') {
    return {
      run_id: null,
      workflow_type: null,
      period: null,
      status: 'idle',
      total_latency_ms: null,
      exceptions_count: 0,
      recommendations_count: 0,
      created_at: null,
      isIdle: true,
      message: 'No workflow runs executed yet',
    };
  }

  const rawStatus = typeof data.status === 'string' ? data.status.trim().toLowerCase() : 'idle';
  const runId = typeof data.run_id === 'string' && data.run_id.trim() ? data.run_id.trim() : null;
  const isIdle = !runId && (rawStatus === 'idle' || data.total_runs === 0);

  const exceptionsCount = parseFiniteNumber(
    data.exceptions_count,
    Array.isArray(data.exceptions) ? data.exceptions.length : 0
  );
  const recommendationsCount = parseFiniteNumber(
    data.recommendations_count,
    Array.isArray(data.recommendations) ? data.recommendations.length : 0
  );

  return {
    run_id: runId,
    workflow_type: typeof data.workflow_type === 'string' ? data.workflow_type : null,
    period: typeof data.period === 'string' ? data.period : null,
    status: rawStatus,
    total_latency_ms: parseFiniteNumber(data.total_latency_ms, null),
    exceptions_count: exceptionsCount,
    recommendations_count: recommendationsCount,
    created_at: isValidDate(data.created_at) ? data.created_at : null,
    isIdle,
    message: typeof data.message === 'string' ? data.message : '',
  };
}

export function normalizeExceptions(data) {
  if (!Array.isArray(data)) {
    return {
      items: [],
      activeCount: 0,
      resolvedCount: 0,
      highCriticalCount: 0,
      byCategory: {
        RECONCILIATION: 0,
        ACCRUAL: 0,
        DEPRECIATION: 0,
        OTHER: 0,
      },
      bySeverity: {
        CRITICAL: 0,
        HIGH: 0,
        MEDIUM: 0,
        LOW: 0,
      },
    };
  }

  let activeCount = 0;
  let resolvedCount = 0;
  let highCriticalCount = 0;

  const byCategory = {
    RECONCILIATION: 0,
    ACCRUAL: 0,
    DEPRECIATION: 0,
    OTHER: 0,
  };

  const bySeverity = {
    CRITICAL: 0,
    HIGH: 0,
    MEDIUM: 0,
    LOW: 0,
  };

  const validItems = [];

  for (const item of data) {
    if (!item || typeof item !== 'object') continue;

    const rawStatus = typeof item.status === 'string' ? item.status.trim().toUpperCase() : 'OPEN';
    const isResolved = rawStatus === 'RESOLVED';

    const rawSeverity = typeof item.severity === 'string' ? item.severity.trim().toUpperCase() : 'LOW';
    const severity = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].includes(rawSeverity) ? rawSeverity : 'LOW';

    const rawCategory = typeof item.category === 'string' ? item.category.trim().toUpperCase() : 'OTHER';
    const category = ['RECONCILIATION', 'ACCRUAL', 'DEPRECIATION'].includes(rawCategory)
      ? rawCategory
      : 'OTHER';

    const amountVariance = parseFiniteNumber(item.amount_variance, 0);

    if (isResolved) {
      resolvedCount += 1;
    } else {
      activeCount += 1;
      if (severity === 'CRITICAL' || severity === 'HIGH') {
        highCriticalCount += 1;
      }
      bySeverity[severity] = (bySeverity[severity] || 0) + 1;
      byCategory[category] = (byCategory[category] || 0) + 1;
    }

    validItems.push({
      id: typeof item.id === 'string' ? item.id : `exc-${validItems.length}`,
      period: typeof item.period === 'string' ? item.period : 'N/A',
      category,
      severity,
      amount_variance: amountVariance,
      description: typeof item.description === 'string' ? item.description : 'No description provided',
      status: rawStatus,
      created_at: isValidDate(item.created_at) ? item.created_at : null,
    });
  }

  return {
    items: validItems,
    activeCount,
    resolvedCount,
    highCriticalCount,
    byCategory,
    bySeverity,
  };
}

export function normalizeApprovals(data) {
  if (!Array.isArray(data)) {
    return {
      items: [],
      pendingCount: 0,
    };
  }

  const validItems = data.filter((item) => item && typeof item === 'object');
  return {
    items: validItems.map((item, idx) => ({
      run_id: typeof item.run_id === 'string' ? item.run_id : `approval-${idx}`,
      workflow_type: typeof item.workflow_type === 'string' ? item.workflow_type : 'reconciliation',
      period: typeof item.period === 'string' ? item.period : '',
      exceptions_count: parseFiniteNumber(item.exceptions_count, 0),
      recommendations: Array.isArray(item.recommendations) ? item.recommendations : [],
    })),
    pendingCount: validItems.length,
  };
}

export function normalizeMetrics(data) {
  if (!data || typeof data !== 'object') {
    return {
      total_runs: 0,
      avg_latency_ms: 0,
      total_token_usage: 0,
      error_count: 0,
      hitl_approvals_count: 0,
    };
  }

  return {
    total_runs: Math.max(0, Math.floor(parseFiniteNumber(data.total_runs, 0))),
    avg_latency_ms: Math.max(0, parseFiniteNumber(data.avg_latency_ms, 0)),
    total_token_usage: Math.max(0, Math.floor(parseFiniteNumber(data.total_token_usage, 0))),
    error_count: Math.max(0, Math.floor(parseFiniteNumber(data.error_count, 0))),
    hitl_approvals_count: Math.max(0, Math.floor(parseFiniteNumber(data.hitl_approvals_count, 0))),
  };
}

export function normalizeRuns(data) {
  if (!Array.isArray(data)) return [];

  return data
    .filter((item) => item && typeof item === 'object')
    .map((item, index) => {
      const validDate = isValidDate(item.created_at);
      return {
        run_id: typeof item.run_id === 'string' && item.run_id.trim() ? item.run_id.trim() : `run-${index}`,
        workflow_type: typeof item.workflow_type === 'string' ? item.workflow_type : 'reconciliation',
        period: typeof item.period === 'string' ? item.period : '',
        status: typeof item.status === 'string' ? item.status : 'unknown',
        exceptions_count: parseFiniteNumber(item.exceptions_count, 0),
        recommendations_count: parseFiniteNumber(item.recommendations_count, 0),
        created_at: validDate ? item.created_at : null,
        raw_created_at: item.created_at,
        originalIndex: index,
      };
    });
}

/**
 * Select the latest workflow run.
 * Safely handles invalid/missing timestamps:
 * 1. Checks valid created_at timestamps across runs.
 * 2. If valid timestamps exist, sorts by timestamp descending.
 * 3. When timestamps are missing or invalid, preserves the backend's existing order.
 * 4. Merges latency or details from summary if run IDs match.
 */
export function selectLatestRun(summary, runs) {
  const normSummary = summary ? normalizeSummary(summary) : null;
  const normRuns = normalizeRuns(runs);

  // If summary already has a valid run with latency, and no runs array provided
  if (normSummary && !normSummary.isIdle && normSummary.run_id && normRuns.length === 0) {
    return {
      run_id: normSummary.run_id,
      workflow_type: normSummary.workflow_type || 'reconciliation',
      period: normSummary.period || 'CURRENT',
      status: normSummary.status || 'unknown',
      exceptions_count: normSummary.exceptions_count,
      recommendations_count: normSummary.recommendations_count,
      latency_ms: normSummary.total_latency_ms,
      created_at: normSummary.created_at,
    };
  }

  if (normRuns.length === 0) {
    if (normSummary && !normSummary.isIdle && normSummary.run_id) {
      return {
        run_id: normSummary.run_id,
        workflow_type: normSummary.workflow_type || 'reconciliation',
        period: normSummary.period || 'CURRENT',
        status: normSummary.status || 'unknown',
        exceptions_count: normSummary.exceptions_count,
        recommendations_count: normSummary.recommendations_count,
        latency_ms: normSummary.total_latency_ms,
        created_at: normSummary.created_at,
      };
    }
    return null;
  }

  // Check if any run has a valid timestamp
  const runsWithValidDates = normRuns.filter((r) => r.created_at !== null);

  let selectedRun;
  if (runsWithValidDates.length > 0) {
    // Sort stable: newest created_at first; preserve backend order on tie
    const sorted = [...normRuns].sort((a, b) => {
      const timeA = a.created_at ? new Date(a.created_at).getTime() : -1;
      const timeB = b.created_at ? new Date(b.created_at).getTime() : -1;
      if (timeA !== timeB) {
        return timeB - timeA;
      }
      return a.originalIndex - b.originalIndex;
    });
    selectedRun = sorted[0];
  } else {
    // Preserves the backend's existing order when timestamps are unavailable
    selectedRun = normRuns[0];
  }

  // Cross-reference with summary if IDs match for richer details (such as latency)
  let latencyMs = null;
  if (normSummary && normSummary.run_id === selectedRun.run_id) {
    latencyMs = normSummary.total_latency_ms;
  }

  return {
    run_id: selectedRun.run_id,
    workflow_type: selectedRun.workflow_type,
    period: selectedRun.period || 'CURRENT',
    status: selectedRun.status,
    exceptions_count: selectedRun.exceptions_count,
    recommendations_count: selectedRun.recommendations_count,
    latency_ms: latencyMs,
    created_at: selectedRun.created_at,
  };
}

