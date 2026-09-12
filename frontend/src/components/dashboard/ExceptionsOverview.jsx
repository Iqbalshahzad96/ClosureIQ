import React from 'react';
import { AlertTriangle, Layers, ShieldAlert, CheckCircle2 } from 'lucide-react';
import { LoadingSkeleton, ErrorState, EmptyState } from './SectionState';

export default function ExceptionsOverview({
  exceptionsState,
  onRetry,
}) {
  const { loading, error, data } = exceptionsState;

  const categories = [
    { key: 'RECONCILIATION', label: 'Reconciliation', count: data.byCategory.RECONCILIATION || 0 },
    { key: 'ACCRUAL', label: 'Accruals', count: data.byCategory.ACCRUAL || 0 },
    { key: 'DEPRECIATION', label: 'Depreciation', count: data.byCategory.DEPRECIATION || 0 },
    { key: 'OTHER', label: 'Other', count: data.byCategory.OTHER || 0 },
  ];

  const severities = [
    { key: 'CRITICAL', label: 'Critical', count: data.bySeverity.CRITICAL || 0, color: 'var(--accent-rose)' },
    { key: 'HIGH', label: 'High', count: data.bySeverity.HIGH || 0, color: 'var(--accent-amber)' },
    { key: 'MEDIUM', label: 'Medium', count: data.bySeverity.MEDIUM || 0, color: 'var(--accent-blue)' },
    { key: 'LOW', label: 'Low', count: data.bySeverity.LOW || 0, color: 'var(--accent-emerald)' },
  ];

  const totalReported = data.activeCount + data.resolvedCount;

  return (
    <section className="card" style={{ marginBottom: '2rem' }} aria-labelledby="exceptions-overview-title">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.25rem',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <h2
          id="exceptions-overview-title"
          style={{ fontSize: '1.15rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <AlertTriangle size={20} color="var(--accent-amber)" aria-hidden="true" />
          Financial Exception Telemetry
        </h2>
        {!loading && !error && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <span>Active: <strong style={{ color: 'var(--text-primary)' }}>{data.activeCount}</strong></span>
            <span>Resolved: <strong style={{ color: 'var(--accent-emerald)' }}>{data.resolvedCount}</strong></span>
          </div>
        )}
      </div>

      {loading ? (
        <LoadingSkeleton label="Loading exception telemetry..." height={120} />
      ) : error ? (
        <ErrorState
          title="Unable to load exceptions"
          message="Could not connect to the financial exceptions service."
          onRetry={onRetry}
          retryLabel="Retry exceptions"
        />
      ) : totalReported === 0 ? (
        <EmptyState
          message="No exception records available. Run a financial close workflow to generate exception results."
          icon={CheckCircle2}
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
          {/* Category Breakdown */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Layers size={15} aria-hidden="true" />
              Active by Workflow Category
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {categories.map((cat) => (
                <div key={cat.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.825rem' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>{cat.label}</span>
                  <span
                    style={{
                      fontWeight: 600,
                      color: cat.count > 0 ? 'var(--text-primary)' : 'var(--text-muted)',
                      background: 'rgba(255, 255, 255, 0.05)',
                      padding: '0.15rem 0.5rem',
                      borderRadius: 4,
                    }}
                  >
                    {cat.count}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Severity Breakdown */}
          <div style={{ background: 'rgba(17, 24, 39, 0.4)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
            <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <ShieldAlert size={15} aria-hidden="true" />
              Active by Risk Severity
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {severities.map((sev) => (
                <div key={sev.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.825rem' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: sev.color }} aria-hidden="true" />
                    <span>{sev.label}</span>
                  </span>
                  <span
                    style={{
                      fontWeight: 600,
                      color: sev.count > 0 ? sev.color : 'var(--text-muted)',
                      background: 'rgba(255, 255, 255, 0.05)',
                      padding: '0.15rem 0.5rem',
                      borderRadius: 4,
                    }}
                  >
                    {sev.count}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

