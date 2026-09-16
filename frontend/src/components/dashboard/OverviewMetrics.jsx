import React from 'react';
import { Scale, AlertCircle, CheckSquare } from 'lucide-react';
import { LoadingSkeleton, ErrorState } from './SectionState';

export default function OverviewMetrics({
  summaryState,
  exceptionsState,
  approvalsState,
  onRetrySummary,
  onRetryExceptions,
  onRetryApprovals,
}) {
  const getStatusDisplay = (summary) => {
    if (!summary || summary.isIdle) {
      return { text: 'Idle', variant: 'var(--text-muted)', sub: 'No close workflow in progress' };
    }
    switch (summary.status) {
      case 'clean_close':
        return { text: 'Clean Close', variant: 'var(--accent-emerald)', sub: `Period: ${summary.period || 'CURRENT'}` };
      case 'hitl_pending':
        return { text: 'HITL Review Pending', variant: 'var(--accent-amber)', sub: `Period: ${summary.period || 'CURRENT'}` };
      case 'approved':
        return { text: 'Approved', variant: 'var(--accent-emerald)', sub: 'Approved by human reviewer' };
      case 'rejected':
        return { text: 'Rejected', variant: 'var(--accent-rose)', sub: 'Rejected by human reviewer' };
      case 'error':
        return { text: 'Workflow Error', variant: 'var(--accent-rose)', sub: 'Check run trace logs' };
      case 'running':
        return { text: 'Running', variant: 'var(--accent-blue)', sub: 'Workflow currently executing' };
      default:
        return { text: summary.status.toUpperCase(), variant: 'var(--primary)', sub: `Period: ${summary.period || 'CURRENT'}` };
    }
  };

  const statusInfo = getStatusDisplay(summaryState.data);

  return (
    <section className="overview-status-section" aria-label="Close workflow overview">
      <div className="overview-status-grid">
        <div className="metric-card overview-metric-card" data-testid="metric-close-status">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="metric-label">Close Workflow Status</span>
            <div style={{ color: 'var(--primary)', background: 'rgba(255,255,255,0.05)', padding: 6, borderRadius: 6 }}>
              <Scale size={18} aria-hidden="true" />
            </div>
          </div>
          {summaryState.loading ? (
            <LoadingSkeleton label="Loading status..." height={60} />
          ) : summaryState.error ? (
            <ErrorState compact title="Failed to load" onRetry={onRetrySummary} retryLabel="Retry status" />
          ) : (
            <>
              <div
                className="metric-value"
                style={{ fontSize: '1.45rem', color: statusInfo.variant }}
                aria-label={`Current close status: ${statusInfo.text}`}
              >
                {statusInfo.text}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{statusInfo.sub}</div>
            </>
          )}
        </div>

        <div className="metric-card overview-metric-card" data-testid="metric-active-exceptions">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="metric-label">Active Exceptions</span>
            <div style={{ color: 'var(--accent-amber)', background: 'rgba(255,255,255,0.05)', padding: 6, borderRadius: 6 }}>
              <AlertCircle size={18} aria-hidden="true" />
            </div>
          </div>
          {exceptionsState.loading ? (
            <LoadingSkeleton label="Loading exceptions..." height={60} />
          ) : exceptionsState.error ? (
            <ErrorState compact title="Failed to load" onRetry={onRetryExceptions} retryLabel="Retry exceptions" />
          ) : (
            <>
              <div className="metric-value">{exceptionsState.data.activeCount}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {exceptionsState.data.highCriticalCount > 0
                  ? `${exceptionsState.data.highCriticalCount} high/critical requiring review`
                  : '0 high/critical priority'}
              </div>
            </>
          )}
        </div>

        <div className="metric-card overview-metric-card" data-testid="metric-hitl-approvals">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="metric-label">Pending HITL Approvals</span>
            <div style={{ color: 'var(--accent-blue)', background: 'rgba(255,255,255,0.05)', padding: 6, borderRadius: 6 }}>
              <CheckSquare size={18} aria-hidden="true" />
            </div>
          </div>
          {approvalsState.loading ? (
            <LoadingSkeleton label="Loading approvals..." height={60} />
          ) : approvalsState.error ? (
            <ErrorState compact title="Failed to load" onRetry={onRetryApprovals} retryLabel="Retry approvals" />
          ) : (
            <>
              <div className="metric-value">{approvalsState.data.pendingCount}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {approvalsState.data.pendingCount === 1
                  ? '1 workflow checkpoint awaiting review'
                  : `${approvalsState.data.pendingCount} checkpoints awaiting review`}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
