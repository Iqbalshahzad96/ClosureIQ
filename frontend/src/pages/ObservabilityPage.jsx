import React, { useState, useEffect } from 'react';
import {
  Activity,
  LineChart,
  ShieldCheck,
  Zap,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertCircle,
  Eye,
  X,
  FileCode,
  Layers,
} from 'lucide-react';
import MetricCard from '../components/MetricCard';
import {
  fetchObservabilityMetrics,
  fetchObservabilityRuns,
  fetchRunTrace,
} from '../services/reconciliationService';

export default function ObservabilityPage() {
  const [metrics, setMetrics] = useState({
    total_runs: 0,
    average_latency_ms: 0,
    total_tokens: 0,
    audit_trail_count: 0,
    hitl_approvals_count: 0,
    error_count: 0,
  });
  const [runs, setRuns] = useState([]);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRunTrace, setSelectedRunTrace] = useState(null);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [error, setError] = useState(null);

  const loadData = async () => {
    setLoadingMetrics(true);
    setLoadingRuns(true);
    setError(null);

    try {
      const [m, r] = await Promise.all([
        fetchObservabilityMetrics().catch((err) => {
          console.warn('Metrics fetch error:', err);
          return null;
        }),
        fetchObservabilityRuns().catch((err) => {
          console.warn('Runs fetch error:', err);
          return [];
        }),
      ]);

      if (m) {
        setMetrics({
          total_runs: m.total_runs || m.runs_count || 0,
          average_latency_ms: m.average_latency_ms || m.avg_latency || 0,
          total_tokens: m.total_tokens || m.token_consumption || 0,
          audit_trail_count: m.audit_trail_count || m.audit_records || 0,
          hitl_approvals_count: m.hitl_approvals_count || 0,
          error_count: m.error_count || 0,
        });
      }

      if (Array.isArray(r)) {
        setRuns(r);
      }
    } catch (err) {
      setError(err.message || 'Failed to load observability data');
    } finally {
      setLoadingMetrics(false);
      setLoadingRuns(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleInspectRun = async (runId) => {
    setLoadingTrace(true);
    setSelectedRunTrace(null);
    try {
      const trace = await fetchRunTrace(runId);
      setSelectedRunTrace(trace);
    } catch (err) {
      setError(`Failed to fetch trace for ${runId}: ${err.message}`);
    } finally {
      setLoadingTrace(false);
    }
  };

  const getStatusBadge = (status) => {
    const s = (status || 'UNKNOWN').toUpperCase();
    if (s === 'COMPLETED' || s === 'RESOLVED' || s === 'APPROVED') {
      return <span className="badge badge-success">{s}</span>;
    }
    if (s === 'PENDING_APPROVAL' || s === 'IN_REVIEW') {
      return <span className="badge badge-warning">{s}</span>;
    }
    if (s === 'ERROR' || s === 'REJECTED' || s === 'FAILED') {
      return <span className="badge badge-danger">{s}</span>;
    }
    return <span className="badge badge-neutral">{s}</span>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Observability & Telemetry</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Live metrics, LangGraph orchestrator traces, token consumption, and tamper-evident audit logs.
          </p>
        </div>

        <button
          className="button button-outline"
          onClick={loadData}
          disabled={loadingMetrics || loadingRuns}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={16} className={loadingMetrics || loadingRuns ? 'spin' : ''} />
          <span>Refresh Telemetry</span>
        </button>
      </div>

      {error && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--accent-rose)', color: 'var(--accent-rose)' }}>
          {error}
        </div>
      )}

      {/* Metrics Grid */}
      <div className="metrics-grid">
        <MetricCard
          title="Total Orchestrator Runs"
          value={String(metrics.total_runs)}
          subtitle={`${metrics.hitl_approvals_count} HITL Approvals`}
          icon={Activity}
        />
        <MetricCard
          title="Average Latency"
          value={`${Number(metrics.average_latency_ms).toFixed(1)} ms`}
          subtitle="End-to-end execution"
          icon={Zap}
        />
        <MetricCard
          title="Token Consumption"
          value={metrics.total_tokens.toLocaleString()}
          subtitle="Agent reasoning tokens"
          icon={LineChart}
        />
        <MetricCard
          title="Audit Trail Records"
          value={String(metrics.audit_trail_count)}
          subtitle="Immutable trace log"
          icon={ShieldCheck}
        />
      </div>

      {/* Runs Table */}
      <div className="card" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Workflow Execution Runs</h3>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Showing {runs.length} recorded run(s)
          </span>
        </div>

        {loadingRuns ? (
          <div style={{ textAlign: 'center', padding: '2.5rem 1rem' }}>
            <RefreshCw size={28} className="spin" style={{ margin: '0 auto 0.75rem auto', color: 'var(--primary)' }} />
            <p style={{ color: 'var(--text-secondary)' }}>Loading execution traces...</p>
          </div>
        ) : runs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--text-muted)' }}>
            <Clock size={36} style={{ margin: '0 auto 0.75rem auto', opacity: 0.6 }} />
            <p>No workflow runs recorded yet. Execute a reconciliation run to generate traces.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Run ID</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Workflow</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Period</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Status</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Latency</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Timestamp</th>
                  <th style={{ padding: '0.75rem 0.5rem', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r, idx) => {
                  const runId = r.run_id || r.id || `run-${idx}`;
                  return (
                    <tr key={runId} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '0.75rem 0.5rem', fontFamily: 'monospace', fontWeight: 600 }}>
                        {runId.slice(0, 8)}...
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem', textTransform: 'capitalize' }}>
                        {r.workflow_type || 'Reconciliation'}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem' }}>
                        {r.period || '2026-Q1'}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem' }}>
                        {getStatusBadge(r.status)}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem' }}>
                        {r.latency_ms ? `${Number(r.latency_ms).toFixed(1)} ms` : r.execution_time_ms ? `${Number(r.execution_time_ms).toFixed(1)} ms` : 'N/A'}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        {r.created_at ? new Date(r.created_at).toLocaleTimeString() : 'Recent'}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem', textAlign: 'right' }}>
                        <button
                          className="button button-outline"
                          style={{ padding: '0.3rem 0.6rem', fontSize: '0.775rem', display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}
                          onClick={() => handleInspectRun(runId)}
                        >
                          <Eye size={13} />
                          <span>Inspect Trace</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Trace Inspector Modal */}
      {selectedRunTrace && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1.5rem',
          }}
          onClick={() => setSelectedRunTrace(null)}
        >
          <div
            className="card"
            style={{
              width: '100%',
              maxWidth: '850px',
              maxHeight: '90vh',
              overflowY: 'auto',
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              padding: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Layers size={20} color="var(--primary)" />
                <h3 style={{ fontSize: '1.15rem', fontWeight: 700 }}>
                  Trace Detail: {selectedRunTrace.run_id || 'Workflow Run'}
                </h3>
              </div>
              <button
                className="button button-ghost"
                onClick={() => setSelectedRunTrace(null)}
                style={{ padding: '0.25rem 0.5rem' }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem', padding: '0.75rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)' }}>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Status</span>
                <div>{getStatusBadge(selectedRunTrace.status)}</div>
              </div>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Workflow Type</span>
                <div style={{ fontWeight: 600 }}>{selectedRunTrace.workflow_type || 'Reconciliation'}</div>
              </div>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Execution Latency</span>
                <div style={{ fontWeight: 600 }}>{selectedRunTrace.latency_ms ? `${Number(selectedRunTrace.latency_ms).toFixed(1)} ms` : 'N/A'}</div>
              </div>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Tokens Used</span>
                <div style={{ fontWeight: 600 }}>{selectedRunTrace.tokens_used || selectedRunTrace.token_consumption || 0}</div>
              </div>
            </div>

            <div>
              <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <FileCode size={15} /> Complete Trace / Audit Payload:
              </h4>
              <pre
                style={{
                  padding: '1rem',
                  background: 'var(--bg-primary)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.8rem',
                  overflowX: 'auto',
                  maxHeight: '400px',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)',
                }}
              >
                {JSON.stringify(selectedRunTrace, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
