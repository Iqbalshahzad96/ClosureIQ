import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ArrowRight } from 'lucide-react';
import DashboardHeader from '../components/dashboard/DashboardHeader';
import OverviewMetrics from '../components/dashboard/OverviewMetrics';
import LatestWorkflowCard from '../components/dashboard/LatestWorkflowCard';
import ExceptionsOverview from '../components/dashboard/ExceptionsOverview';
import ObservabilitySummary from '../components/dashboard/ObservabilitySummary';
import IngestionStatusCard from '../components/dashboard/IngestionStatusCard';
import AgentArchitectureBanner from '../components/dashboard/AgentArchitectureBanner';

import {
  fetchReconciliationSummary,
  fetchExceptions,
  fetchPendingApprovals,
  fetchObservabilityMetrics,
  fetchObservabilityRuns,
} from '../services/dashboardService';

import {
  normalizeSummary,
  normalizeExceptions,
  normalizeApprovals,
  normalizeMetrics,
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

  const [metricsState, setMetricsState] = useState({
    loading: true,
    error: null,
    data: normalizeMetrics(null),
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
    metrics: null,
    runs: null,
  });

  const requestGenerationsRef = useRef({
    summary: 0,
    exceptions: 0,
    approvals: 0,
    metrics: 0,
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
      metrics: setMetricsState,
      runs: setRunsState,
    };

    const fetcherMap = {
      summary: fetchReconciliationSummary,
      exceptions: fetchExceptions,
      approvals: fetchPendingApprovals,
      metrics: fetchObservabilityMetrics,
      runs: fetchObservabilityRuns,
    };

    const normalizerMap = {
      summary: normalizeSummary,
      exceptions: normalizeExceptions,
      approvals: normalizeApprovals,
      metrics: normalizeMetrics,
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
   * Global refresh: fetches all 5 sections concurrently using Promise.allSettled.
   * Updates 'Last updated' timestamp only if at least one endpoint succeeds.
   */
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);

    const results = await Promise.allSettled([
      fetchSection('summary'),
      fetchSection('exceptions'),
      fetchSection('approvals'),
      fetchSection('metrics'),
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
    <main aria-label="ClosureIQ Dashboard">
      {/* Header with Title, Last Updated, and Refresh */}
      <DashboardHeader
        lastUpdated={lastUpdated}
        isRefreshing={isRefreshing}
        onRefresh={handleRefresh}
      />

      {/* KPI Overview Metrics (Status, Active Exceptions, Approvals, Latency) */}
      <OverviewMetrics
        summaryState={summaryState}
        exceptionsState={exceptionsState}
        approvalsState={approvalsState}
        metricsState={metricsState}
        onRetrySummary={() => fetchSection('summary')}
        onRetryExceptions={() => fetchSection('exceptions')}
        onRetryApprovals={() => fetchSection('approvals')}
        onRetryMetrics={() => fetchSection('metrics')}
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

      {/* Financial Exceptions Overview (Category & Severity Breakdown) */}
      <ExceptionsOverview
        exceptionsState={exceptionsState}
        onRetry={() => fetchSection('exceptions')}
      />

      {/* Observability & Runtime Telemetry (Exact backend fields) */}
      <ObservabilitySummary
        metricsState={metricsState}
        onRetry={() => fetchSection('metrics')}
      />

      {/* Honest Ingestion Empty / Readiness State */}
      <IngestionStatusCard />

      {/* Two Specialized AI Agents Banner with Corrected Copy */}
      <AgentArchitectureBanner />

      {/* Quick Action Navigation */}
      <nav
        aria-label="Quick Navigation"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: '1rem',
          marginTop: '1rem',
        }}
      >
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setActiveTab && setActiveTab('reconciliation')}
          style={{ justifyContent: 'space-between', padding: '1rem 1.25rem' }}
          aria-label="Navigate to Reconciliation Engine"
        >
          <span>Open Reconciliation Engine</span>
          <ArrowRight size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setActiveTab && setActiveTab('exceptions')}
          style={{ justifyContent: 'space-between', padding: '1rem 1.25rem' }}
          aria-label="Navigate to Financial Exceptions"
        >
          <span>Inspect Financial Exceptions</span>
          <ArrowRight size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setActiveTab && setActiveTab('approvals')}
          style={{ justifyContent: 'space-between', padding: '1rem 1.25rem' }}
          aria-label="Navigate to HITL Approvals"
        >
          <span>Review HITL Approvals</span>
          <ArrowRight size={16} aria-hidden="true" />
        </button>
      </nav>
    </main>
  );
}
