import React from 'react';
import { Activity, Clock, FileWarning, Lightbulb, Calendar, Terminal } from 'lucide-react';
import { formatLatency, selectLatestRun } from '../../services/dashboardNormalizers';
import { LoadingSkeleton, ErrorState, EmptyState } from './SectionState';
import StatusBadge from '../StatusBadge';

export default function LatestWorkflowCard({
  summaryState,
  runsState,
  onRetry,
}) {
  const isLoading = summaryState.loading && runsState.loading;
  const hasError = summaryState.error && runsState.error;

  const latestRun = selectLatestRun(summaryState.data, runsState.data);

  const getStatusBadgeProps = (status) => {
    switch (status) {
      case 'clean_close':
      case 'approved':
        return { variant: 'emerald', label: status === 'clean_close' ? 'Clean Close' : 'Approved' };
      case 'hitl_pending':
        return { variant: 'amber', label: 'HITL Review Pending' };
      case 'rejected':
      case 'error':
        return { variant: 'rose', label: status === 'rejected' ? 'Rejected' : 'Workflow Error' };
      case 'running':
        return { variant: 'indigo', label: 'Running' };
      default:
        return { variant: 'indigo', label: status ? status.toUpperCase() : 'Idle' };
    }
  };

  return (
    <section className="card" style={{ marginBottom: '2rem' }} aria-labelledby="latest-workflow-title">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.25rem',
        }}
      >
        <h2
          id="latest-workflow-title"
          style={{ fontSize: '1.15rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <Activity size={20} color="var(--primary)" aria-hidden="true" />
          Latest Workflow Execution
        </h2>
        {latestRun && (
          <StatusBadge
            status={getStatusBadgeProps(latestRun.status).label}
            variant={getStatusBadgeProps(latestRun.status).variant}
          />
        )}
      </div>

      {isLoading ? (
        <LoadingSkeleton label="Loading latest workflow details..." height={100} />
      ) : hasError ? (
        <ErrorState
          title="Unable to load workflow details"
          message="Both reconciliation summary and run telemetry could not be retrieved."
          onRetry={onRetry}
          retryLabel="Retry workflow details"
        />
      ) : !latestRun ? (
        <EmptyState
          message="No workflow runs executed yet. Trigger a reconciliation, accrual, or depreciation run to inspect execution telemetry."
          icon={Activity}
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.25rem' }}>
          {/* Run ID & Type */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '0.9rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.35rem' }}>
              <Terminal size={14} aria-hidden="true" />
              <span>Run ID & Type</span>
            </div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)', textTransform: 'capitalize' }}>
              {latestRun.workflow_type}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
              {latestRun.run_id}
            </div>
          </div>

          {/* Close Period */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '0.9rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.35rem' }}>
              <Calendar size={14} aria-hidden="true" />
              <span>Financial Period</span>
            </div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
              {latestRun.period || 'CURRENT'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              {latestRun.created_at ? new Date(latestRun.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'Unspecified timestamp'}
            </div>
          </div>

          {/* Exceptions Detected */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '0.9rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.35rem' }}>
              <FileWarning size={14} aria-hidden="true" />
              <span>Exceptions Detected</span>
            </div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', color: latestRun.exceptions_count > 0 ? 'var(--accent-amber)' : 'var(--accent-emerald)' }}>
              {latestRun.exceptions_count} {latestRun.exceptions_count === 1 ? 'exception' : 'exceptions'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Flagged by financial engine
            </div>
          </div>

          {/* SOP Recommendations */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '0.9rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.35rem' }}>
              <Lightbulb size={14} aria-hidden="true" />
              <span>Agent Recommendations</span>
            </div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--primary)' }}>
              {latestRun.recommendations_count} {latestRun.recommendations_count === 1 ? 'recommendation' : 'recommendations'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              RAG policy guidance
            </div>
          </div>

          {/* Execution Latency */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '0.9rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.35rem' }}>
              <Clock size={14} aria-hidden="true" />
              <span>Workflow Latency</span>
            </div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
              {formatLatency(latestRun.latency_ms)}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Total execution time
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

