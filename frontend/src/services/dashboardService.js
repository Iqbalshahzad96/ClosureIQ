/**
 * Dashboard API Service for ClosureIQ.
 * Fetches dashboard endpoints with AbortSignal support, safe error masking,
 * and no sensitive payload or full URL logging.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

async function fetchEndpoint(endpoint, { signal } = {}) {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = `${BASE_URL}${cleanEndpoint}`;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
      signal,
    });

    if (!response.ok) {
      const error = new Error(`Request failed with status ${response.status}`);
      error.status = response.status;
      throw error;
    }

    return await response.json();
  } catch (err) {
    if (err.name === 'AbortError') {
      throw err;
    }
    // Sanitized user-facing error message; prevents leaking raw backend details
    const sanitizedError = new Error('Service unavailable. Please retry.');
    if (err.status) sanitizedError.status = err.status;
    throw sanitizedError;
  }
}

export async function fetchReconciliationSummary({ signal } = {}) {
  return fetchEndpoint('/reconciliation/summary', { signal });
}

export async function fetchExceptions({ signal } = {}) {
  return fetchEndpoint('/exceptions/', { signal });
}

export async function fetchPendingApprovals({ signal } = {}) {
  return fetchEndpoint('/approvals/pending', { signal });
}

export async function fetchObservabilityMetrics({ signal } = {}) {
  return fetchEndpoint('/observability/metrics', { signal });
}

export async function fetchObservabilityRuns({ signal } = {}) {
  return fetchEndpoint('/observability/runs', { signal });
}

