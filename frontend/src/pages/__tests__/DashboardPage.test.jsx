import React from 'react';
import { render, screen, waitFor, fireEvent, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import DashboardPage from '../DashboardPage';
import {
  mockReconciliationSummary,
  mockIdleSummary,
  mockExceptions,
  mockPendingApprovals,
  mockObservabilityMetrics,
  mockObservabilityRuns,
  mockMalformedSummary,
  mockMalformedExceptions,
  mockMalformedApprovals,
  mockMalformedMetrics,
  mockMalformedRuns,
} from '../../test/mockData';
import { selectLatestRun, normalizeExceptions } from '../../services/dashboardNormalizers';

describe('DashboardPage', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const setupFetchMock = (handlers = {}) => {
    global.fetch = vi.fn().mockImplementation((url, options) => {
      const urlStr = String(url);

      if (handlers.custom) {
        const customRes = handlers.custom(urlStr, options);
        if (customRes) return customRes;
      }

      if (urlStr.includes('/reconciliation/summary')) {
        if (handlers.summaryError) return Promise.reject(new Error('Summary failed'));
        return Promise.resolve({
          ok: !handlers.summaryStatus || handlers.summaryStatus === 200,
          status: handlers.summaryStatus || 200,
          json: async () => (handlers.summaryData !== undefined ? handlers.summaryData : mockReconciliationSummary),
        });
      }

      if (urlStr.includes('/exceptions/')) {
        if (handlers.exceptionsError) return Promise.reject(new Error('Exceptions failed'));
        return Promise.resolve({
          ok: !handlers.exceptionsStatus || handlers.exceptionsStatus === 200,
          status: handlers.exceptionsStatus || 200,
          json: async () => (handlers.exceptionsData !== undefined ? handlers.exceptionsData : mockExceptions),
        });
      }

      if (urlStr.includes('/approvals/pending')) {
        if (handlers.approvalsError) return Promise.reject(new Error('Approvals failed'));
        return Promise.resolve({
          ok: !handlers.approvalsStatus || handlers.approvalsStatus === 200,
          status: handlers.approvalsStatus || 200,
          json: async () => (handlers.approvalsData !== undefined ? handlers.approvalsData : mockPendingApprovals),
        });
      }

      if (urlStr.includes('/observability/metrics')) {
        if (handlers.metricsError) return Promise.reject(new Error('Metrics failed'));
        return Promise.resolve({
          ok: !handlers.metricsStatus || handlers.metricsStatus === 200,
          status: handlers.metricsStatus || 200,
          json: async () => (handlers.metricsData !== undefined ? handlers.metricsData : mockObservabilityMetrics),
        });
      }

      if (urlStr.includes('/observability/runs')) {
        if (handlers.runsError) return Promise.reject(new Error('Runs failed'));
        return Promise.resolve({
          ok: !handlers.runsStatus || handlers.runsStatus === 200,
          status: handlers.runsStatus || 200,
          json: async () => (handlers.runsData !== undefined ? handlers.runsData : mockObservabilityRuns),
        });
      }

      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      });
    });
  };

  // 1. Successful complete response
  it('1. renders all sections with complete successful response data', async () => {
    setupFetchMock();
    render(<DashboardPage setActiveTab={vi.fn()} />);

    // KPI Metrics
    await waitFor(() => {
      expect(screen.getByText('Clean Close')).toBeInTheDocument();
    });

    const activeExceptionsCard = screen.getByTestId('metric-active-exceptions');
    expect(within(activeExceptionsCard).getByText('3')).toBeInTheDocument(); // 3 active exceptions
    expect(screen.getByText(/2 high\/critical requiring review/i)).toBeInTheDocument();

    const approvalsCard = screen.getByTestId('metric-hitl-approvals');
    expect(within(approvalsCard).getByText('1')).toBeInTheDocument(); // 1 pending approval
    expect(screen.getByText('14 Runs')).toBeInTheDocument();

    // Observability Summary exact backend fields
    expect(screen.getByText('45,200')).toBeInTheDocument(); // total_token_usage
    expect(screen.getByText('6')).toBeInTheDocument(); // hitl_approvals_count

    // Corrected Agent copy
    expect(
      screen.getByText(/Agent 1: Exception Review Agent/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Classifies exceptions and explains financial context without recalculation/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Agent 2: Exception Analysis Agent/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Performs RAG-grounded investigation and recommendations; does not directly create journal entries/i)
    ).toBeInTheDocument();

    // Ingestion readiness
    expect(screen.getByText(/No import status available yet/i)).toBeInTheDocument();
  });

  // 2. Loading state
  it('2. displays loading skeletons while requests are in flight', () => {
    global.fetch = vi.fn().mockReturnValue(new Promise(() => {}));
    render(<DashboardPage setActiveTab={vi.fn()} />);

    const skeletons = screen.getAllByRole('status');
    expect(skeletons.length).toBeGreaterThan(0);
    expect(screen.getByText(/Loading status.../i)).toBeInTheDocument();
  });

  // 3. All APIs empty
  it('3. handles all APIs returning empty or idle data cleanly without errors or NaN', async () => {
    setupFetchMock({
      summaryData: mockIdleSummary,
      exceptionsData: [],
      approvalsData: [],
      metricsData: {
        total_runs: 0,
        avg_latency_ms: 0,
        total_token_usage: 0,
        error_count: 0,
        hitl_approvals_count: 0,
      },
      runsData: [],
    });

    render(<DashboardPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Idle')).toBeInTheDocument();
    });

    expect(screen.getByText('0 high/critical priority')).toBeInTheDocument();
    expect(screen.getByText('0 checkpoints awaiting review')).toBeInTheDocument();
    expect(screen.getByText('0 Runs')).toBeInTheDocument();
    expect(screen.getByText(/No workflow runs executed yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No exception records available\. Run a financial close workflow to generate exception results\./i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/completely in balance/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bNaN\b/)).not.toBeInTheDocument();
  });

  // 4. One API failing while remaining sections still render
  it('4. displays error for one failed API while other sections render normally', async () => {
    setupFetchMock({
      exceptionsError: true,
    });

    render(<DashboardPage setActiveTab={vi.fn()} />);

    // Exceptions section and KPI should show error
    await waitFor(() => {
      const retryBtns = screen.getAllByRole('button', { name: /retry exceptions/i });
      expect(retryBtns.length).toBeGreaterThan(0);
    });

    // Other sections render normally
    expect(screen.getByText('Clean Close')).toBeInTheDocument();
    expect(screen.getByText('14 Runs')).toBeInTheDocument();
    expect(screen.getByText(/No import status available yet/i)).toBeInTheDocument();
  });

  // 5. All APIs failing with retry
  it('5. renders error states across sections when all APIs fail and allows retrying', async () => {
    let shouldFail = true;

    global.fetch = vi.fn().mockImplementation((url) => {
      if (shouldFail) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ error: 'Internal Server Error' }),
        });
      }
      // On retry success
      const urlStr = String(url);
      if (urlStr.includes('/exceptions/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockExceptions,
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => mockReconciliationSummary,
      });
    });

    render(<DashboardPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      const retryButtons = screen.getAllByRole('button', { name: /retry/i });
      expect(retryButtons.length).toBeGreaterThan(0);
    });

    // Individual Retry: clicking retry on exceptions only refetches exceptions
    shouldFail = false;
    const retryExceptionsBtns = screen.getAllByRole('button', { name: /retry exceptions/i });
    fireEvent.click(retryExceptionsBtns[0]);

    await waitFor(() => {
      const activeExceptionsCard = screen.getByTestId('metric-active-exceptions');
      expect(within(activeExceptionsCard).getByText('3')).toBeInTheDocument(); // active exceptions recovered
    });
  });

  // 6. Malformed/partial response data
  it('6. safely handles malformed, partial, and non-finite API responses', async () => {
    setupFetchMock({
      summaryData: mockMalformedSummary,
      exceptionsData: mockMalformedExceptions,
      approvalsData: mockMalformedApprovals,
      metricsData: mockMalformedMetrics,
      runsData: mockMalformedRuns,
    });

    render(<DashboardPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('0 Runs')).toBeInTheDocument();
    });

    expect(screen.queryByText(/\bNaN\b/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bInfinity\b/)).not.toBeInTheDocument();
    expect(screen.getByText('0 checkpoints awaiting review')).toBeInTheDocument();
  });

  // 7. Severity/category counting
  it('7. accurately computes active exception counts, severity distribution, and category counts', () => {
    const result = normalizeExceptions(mockExceptions);

    // mockExceptions has 4 items:
    // exc-1: RECONCILIATION, HIGH, OPEN
    // exc-2: ACCRUAL, CRITICAL, OPEN
    // exc-3: DEPRECIATION, MEDIUM, IN_REVIEW
    // exc-4: RECONCILIATION, LOW, RESOLVED
    expect(result.activeCount).toBe(3);
    expect(result.resolvedCount).toBe(1);
    expect(result.highCriticalCount).toBe(2); // HIGH + CRITICAL

    expect(result.byCategory.RECONCILIATION).toBe(1);
    expect(result.byCategory.ACCRUAL).toBe(1);
    expect(result.byCategory.DEPRECIATION).toBe(1);

    expect(result.bySeverity.CRITICAL).toBe(1);
    expect(result.bySeverity.HIGH).toBe(1);
    expect(result.bySeverity.MEDIUM).toBe(1);
    expect(result.bySeverity.LOW).toBe(0); // resolved LOW exception excluded from active
  });

  // 8. Latest-run selection
  it('8. correctly selects latest run, preferring newest valid timestamp and preserving backend order on missing timestamps', () => {
    // Case A: Valid timestamps present
    const runsWithDates = [
      { run_id: 'older-run', created_at: '2026-03-10T10:00:00Z', workflow_type: 'accrual' },
      { run_id: 'newest-run', created_at: '2026-03-12T15:00:00Z', workflow_type: 'reconciliation' },
      { run_id: 'middle-run', created_at: '2026-03-11T12:00:00Z', workflow_type: 'depreciation' },
    ];
    const selectedA = selectLatestRun(null, runsWithDates);
    expect(selectedA.run_id).toBe('newest-run');
    expect(selectedA.workflow_type).toBe('reconciliation');

    // Case B: Timestamps missing or invalid -> preserves backend order
    const runsWithoutDates = [
      { run_id: 'backend-first', created_at: null, workflow_type: 'depreciation' },
      { run_id: 'backend-second', created_at: 'invalid-date', workflow_type: 'accrual' },
    ];
    const selectedB = selectLatestRun(null, runsWithoutDates);
    expect(selectedB.run_id).toBe('backend-first');
  });

  // 9. Refresh behavior and timestamp
  it('9. triggers refresh on button click and updates timestamp only after successful response', async () => {
    setupFetchMock();
    render(<DashboardPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('last-updated-text')).not.toHaveTextContent('Never');
    });

    const refreshBtn = screen.getByRole('button', { name: /refresh dashboard metrics/i });
    expect(refreshBtn).toBeInTheDocument();

    await act(async () => {
      await userEvent.click(refreshBtn);
    });

    await waitFor(() => {
      expect(refreshBtn).not.toBeDisabled();
    });

    // Verify all 5 endpoints were called again (5 on mount + 5 on refresh)
    expect(global.fetch).toHaveBeenCalledTimes(10);
  });

  it('9b. does not update timestamp if every endpoint fails during refresh', async () => {
    let failAll = false;
    global.fetch = vi.fn().mockImplementation(() => {
      if (failAll) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ error: 'Fail' }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => mockIdleSummary,
      });
    });

    render(<DashboardPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('last-updated-text')).not.toHaveTextContent('Never');
    });

    // Now make all endpoints fail
    failAll = true;
    const previousTimestampText = screen.getByTestId('last-updated-text').textContent;

    const refreshBtn = screen.getByRole('button', { name: /refresh dashboard metrics/i });
    await act(async () => {
      await userEvent.click(refreshBtn);
    });

    await waitFor(() => {
      expect(refreshBtn).not.toBeDisabled();
    });

    // The timestamp text should remain unchanged because every endpoint failed
    expect(screen.getByTestId('last-updated-text').textContent).toBe(previousTimestampText);
  });

  // 10. Request cancellation and unmount
  it('10. aborts in-flight requests cleanly on unmount without throwing errors', () => {
    let abortCalled = false;
    global.fetch = vi.fn().mockImplementation((url, options) => {
      if (options?.signal) {
        options.signal.addEventListener('abort', () => {
          abortCalled = true;
        });
      }
      return new Promise(() => {}); // Never resolves
    });

    const { unmount } = render(<DashboardPage setActiveTab={vi.fn()} />);
    unmount();

    expect(abortCalled).toBe(true);
  });

  it('10b. protects against stale overlapping responses overwriting newer data', async () => {
    let resolveFirst;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    let callCount = 0;
    setupFetchMock({
      custom: (url) => {
        if (url.includes('/reconciliation/summary')) {
          callCount++;
          if (callCount === 1) {
            // Initial mount request: slow, resolves to old/stale data
            return firstPromise.then(() => ({
              ok: true,
              status: 200,
              json: async () => ({
                run_id: 'old-stale-run',
                status: 'rejected',
                period: '2025-Q4',
              }),
            }));
          }
          // Subsequent refresh request: fast, resolves immediately to clean_close
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              run_id: 'new-fresh-run',
              status: 'clean_close',
              period: '2026-Q1',
            }),
          });
        }
        return null;
      },
    });

    render(<DashboardPage setActiveTab={vi.fn()} />);

    // Trigger refresh while first request is still pending
    const refreshBtn = screen.getByRole('button', { name: /refresh dashboard metrics/i });
    await act(async () => {
      fireEvent.click(refreshBtn);
    });

    // Fast second request finishes and displays 'Clean Close'
    await waitFor(() => {
      expect(screen.getByText('Clean Close')).toBeInTheDocument();
    });

    // Now resolve the older first request
    await act(async () => {
      resolveFirst();
    });

    // The newer data ('Clean Close') must NOT be overwritten by the older stale data ('Rejected')
    await waitFor(() => {
      expect(screen.getByText('Clean Close')).toBeInTheDocument();
    });
    expect(screen.queryByText('Rejected')).not.toBeInTheDocument();
  });

  // 11. Ingestion status does not show fabricated data
  it('11. displays honest ingestion state without fabricated data or upload controls', async () => {
    setupFetchMock();
    render(<DashboardPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/No import status available yet/i)).toBeInTheDocument();
    });

    // Ensure no file upload controls exist on this branch
    expect(screen.queryByRole('textbox', { type: 'file' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/upload/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/transactions uploaded/i)).not.toBeInTheDocument();
  });

  // 12. No existing navigation regression
  it('12. maintains existing quick action navigation buttons and calls setActiveTab correctly', async () => {
    setupFetchMock();
    const setActiveTabMock = vi.fn();
    render(<DashboardPage setActiveTab={setActiveTabMock} />);

    await waitFor(() => {
      expect(screen.getByText(/Open Reconciliation Engine/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/Open Reconciliation Engine/i));
    expect(setActiveTabMock).toHaveBeenCalledWith('reconciliation');

    fireEvent.click(screen.getByText(/Inspect Financial Exceptions/i));
    expect(setActiveTabMock).toHaveBeenCalledWith('exceptions');

    fireEvent.click(screen.getByText(/Review HITL Approvals/i));
    expect(setActiveTabMock).toHaveBeenCalledWith('approvals');
  });
});
