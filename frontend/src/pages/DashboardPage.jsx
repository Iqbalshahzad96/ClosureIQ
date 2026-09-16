import React, { useState, useEffect, useRef, useCallback } from 'react';
import DashboardHeader from '../components/dashboard/DashboardHeader';
import OverviewMetrics from '../components/dashboard/OverviewMetrics';
import LatestWorkflowCard from '../components/dashboard/LatestWorkflowCard';

import {
  fetchReconciliationSummary,
  fetchExceptions,
  fetchPendingApprovals,
  fetchObservabilityRuns,
} from '../services/dashboardService';

import {
  normalizeSummary,
  normalizeExceptions,
  normalizeApprovals,
  normalizeRuns,
} from '../services/dashboardNormalizers';

export default function DashboardPage({ setActiveTab }) {
  const [summaryState, setSummaryState] = useState({
    loading: true,
    error: null,
    data: normalizeSummary(null),
  });

  const [exceptionsState, setExceptionsState] = useState({
    loading: true,
    error: null,
    data: normalizeExceptions([]),
  });

  const [approvalsState, setApprovalsState] = useState({
    loading: true,
    error: null,
    data: normalizeApprovals([]),
  });

  const [runsState, setRunsState] = useState({
    loading: true,
    error: null,
    data: normalizeRuns([]),
  });

  const [lastUpdated, setLastUpdated] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const isMountedRef = useRef(true);
  const abortControllersRef = useRef({
    summary: null,
    exceptions: null,
    approvals: null,
    runs: null,
  });

  const requestGenerationsRef = useRef({
    summary: 0,
    exceptions: 0,
    approvals: 0,
    runs: 0,
  });

  /**
   * Refetch an individual endpoint safely with generation ID and abort protection.
   * Returns true on success, false on error or abort.
   */
  const fetchSection = useCallback(async (section) => {
    // Abort previous in-flight request for this section
    if (abortControllersRef.current[section]) {
      abortControllersRef.current[section].abort();
    }

    const controller = new AbortController();
    abortControllersRef.current[section] = controller;
    const generation = ++requestGenerationsRef.current[section];

    const setStateMap = {
      summary: setSummaryState,
      exceptions: setExceptionsState,
      approvals: setApprovalsState,
      runs: setRunsState,
    };

    const fetcherMap = {
      summary: fetchReconciliationSummary,
      exceptions: fetchExceptions,
      approvals: fetchPendingApprovals,
      runs: fetchObservabilityRuns,
    };

    const normalizerMap = {
      summary: normalizeSummary,
      exceptions: normalizeExceptions,
      approvals: normalizeApprovals,
      runs: normalizeRuns,
    };

    const setSectionState = setStateMap[section];
    const fetcher = fetcherMap[section];
    const normalizer = normalizerMap[section];

    if (!setSectionState || !fetcher || !normalizer) return false;

    setSectionState((prev) => ({ ...prev, loading: true, error: null }));

    try {
      const rawData = await fetcher({ signal: controller.signal });

      if (
        isMountedRef.current &&
        requestGenerationsRef.current[section] === generation
      ) {
        const normalized = normalizer(rawData);
        setSectionState({
          loading: false,
          error: null,
          data: normalized,
        });
        return true;
      }
      return false;
    } catch (err) {
      if (err.name === 'AbortError') {
        return false;
      }

      if (
        isMountedRef.current &&
        requestGenerationsRef.current[section] === generation
      ) {
        setSectionState((prev) => ({
          ...prev,
          loading: false,
          error: err.message || 'Service unavailable',
        }));
      }
      return false;
    }
  }, []);

  /**
   * Global refresh: fetches all retained sections concurrently using Promise.allSettled.
   * Updates 'Last updated' timestamp only if at least one endpoint succeeds.
   */
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);

    const results = await Promise.allSettled([
      fetchSection('summary'),
      fetchSection('exceptions'),
      fetchSection('approvals'),
      fetchSection('runs'),
    ]);

    if (isMountedRef.current) {
      const hasAnySuccess = results.some(
        (res) => res.status === 'fulfilled' && res.value === true
      );

      if (hasAnySuccess) {
        setLastUpdated(new Date());
      }
      setIsRefreshing(false);
    }
  }, [fetchSection]);

  useEffect(() => {
    isMountedRef.current = true;
    handleRefresh();

    return () => {
      isMountedRef.current = false;
      Object.values(abortControllersRef.current).forEach((ctrl) => {
        if (ctrl) ctrl.abort();
      });
    };
  }, [handleRefresh]);

  return (
    <main className="overview-page" aria-label="ClosureIQ Dashboard">
      {/* Header with Title, Last Updated, and Refresh */}
      <DashboardHeader
        lastUpdated={lastUpdated}
        isRefreshing={isRefreshing}
        onRefresh={handleRefresh}
      />

      {/* Retained close status, exceptions, and approval summaries */}
      <OverviewMetrics
        summaryState={summaryState}
        exceptionsState={exceptionsState}
        approvalsState={approvalsState}
        onRetrySummary={() => fetchSection('summary')}
        onRetryExceptions={() => fetchSection('exceptions')}
        onRetryApprovals={() => fetchSection('approvals')}
      />

      {/* Latest Workflow Execution Details */}
      <LatestWorkflowCard
        summaryState={summaryState}
        runsState={runsState}
        onRetry={() => {
          fetchSection('summary');
          fetchSection('runs');
        }}
      />

    </main>
  );
}
