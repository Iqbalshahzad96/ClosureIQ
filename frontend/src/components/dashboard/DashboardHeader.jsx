import React from 'react';
import { RotateCw } from 'lucide-react';

export default function DashboardHeader({
  lastUpdated,
  isRefreshing,
  onRefresh,
}) {
  const formatTime = (date) => {
    if (!date) return 'Never';
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <header style={{ marginBottom: '2rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '0.5rem' }}>
            ClosureIQ — AI-Powered Financial Close Assistant
          </h1>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '750px', fontSize: '0.95rem' }}>
            Accelerate month-end closing with deterministic financial matching, dual AI reasoning agents,
            RAG-grounded accounting SOP compliance, and Human-in-the-Loop decision controls.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', alignSelf: 'center' }}>
          <span
            style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}
            aria-live="polite"
            data-testid="last-updated-text"
          >
            Last updated: {formatTime(lastUpdated)}
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onRefresh}
            aria-label="Refresh dashboard metrics"
            aria-busy={isRefreshing}
            style={{ padding: '0.5rem 0.9rem' }}
          >
            <RotateCw
              size={15}
              className={isRefreshing ? 'spin-icon' : ''}
              aria-hidden="true"
            />
            <span>{isRefreshing ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
