import React from 'react';
import { Activity, Clock, ShieldCheck, AlertOctagon, Coins } from 'lucide-react';
import { formatLatency } from '../../services/dashboardNormalizers';
import { LoadingSkeleton, ErrorState } from './SectionState';

export default function ObservabilitySummary({
  metricsState,
  onRetry,
}) {
  const { loading, error, data } = metricsState;

  return (
    <section className="card" style={{ marginBottom: '2rem' }} aria-labelledby="observability-summary-title">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.25rem',
        }}
      >
        <h2
          id="observability-summary-title"
          style={{ fontSize: '1.15rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <Activity size={20} color="var(--primary)" aria-hidden="true" />
          Observability & Runtime Telemetry
        </h2>
      </div>

      {loading ? (
        <LoadingSkeleton label="Loading runtime telemetry..." height={100} />
      ) : error ? (
        <ErrorState
          title="Unable to load observability metrics"
          message="Could not connect to the observability telemetry service."
          onRetry={onRetry}
          retryLabel="Retry observability metrics"
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
          {/* total_runs */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <Activity size={14} aria-hidden="true" />
              <span>Total Runs</span>
            </div>
            <div className="metric-value" style={{ fontSize: '1.5rem' }}>
              {data.total_runs}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Workflow executions</div>
          </div>

          {/* avg_latency_ms */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <Clock size={14} aria-hidden="true" />
              <span>Avg Latency</span>
            </div>
            <div className="metric-value" style={{ fontSize: '1.5rem' }}>
              {formatLatency(data.avg_latency_ms)}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Per completed run</div>
          </div>

          {/* total_token_usage */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <Coins size={14} aria-hidden="true" />
              <span>Token Usage</span>
            </div>
            <div className="metric-value" style={{ fontSize: '1.5rem' }}>
              {data.total_token_usage.toLocaleString()}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Gemini API tokens</div>
          </div>

          {/* error_count */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <AlertOctagon size={14} aria-hidden="true" />
              <span>Workflow Errors</span>
            </div>
            <div className="metric-value" style={{ fontSize: '1.5rem', color: data.error_count > 0 ? 'var(--accent-rose)' : 'var(--text-primary)' }}>
              {data.error_count}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Execution failures</div>
          </div>

          {/* hitl_approvals_count */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--text-muted)', fontSize: '0.8rem', marginBottom: '0.25rem' }}>
              <ShieldCheck size={14} aria-hidden="true" />
              <span>HITL Approvals</span>
            </div>
            <div className="metric-value" style={{ fontSize: '1.5rem', color: 'var(--accent-emerald)' }}>
              {data.hitl_approvals_count}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Human sign-offs</div>
          </div>
        </div>
      )}
    </section>
  );
}

