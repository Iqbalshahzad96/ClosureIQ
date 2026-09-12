import React from 'react';
import { AlertCircle, RotateCw } from 'lucide-react';

export function LoadingSkeleton({ label = 'Loading section...', height = 80 }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="loading-skeleton"
      style={{
        minHeight: height,
        borderRadius: 'var(--radius-sm)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(255, 255, 255, 0.03)',
        border: '1px dashed var(--border-color)',
        color: 'var(--text-muted)',
        fontSize: '0.85rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <RotateCw className="spin-icon" size={16} aria-hidden="true" />
        <span>{label}</span>
      </div>
    </div>
  );
}

export function ErrorState({
  title = 'Unable to load data',
  message = 'A connection error occurred while loading this section.',
  onRetry,
  retryLabel = 'Retry',
  compact = false,
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      style={{
        padding: compact ? '0.75rem 1rem' : '1.25rem',
        borderRadius: 'var(--radius-sm)',
        background: 'rgba(244, 63, 94, 0.08)',
        border: '1px solid rgba(244, 63, 94, 0.3)',
        display: 'flex',
        flexDirection: compact ? 'row' : 'column',
        alignItems: compact ? 'center' : 'flex-start',
        justifyContent: 'space-between',
        gap: '0.75rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <AlertCircle size={18} color="var(--accent-rose)" aria-hidden="true" />
        <div>
          <strong style={{ fontSize: '0.875rem', color: '#fca5a5' }}>{title}</strong>
          {!compact && (
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              {message}
            </p>
          )}
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="btn btn-secondary retry-button"
          aria-label={retryLabel}
          style={{
            fontSize: '0.8rem',
            padding: '0.35rem 0.75rem',
            color: '#ffffff',
            borderColor: 'rgba(244, 63, 94, 0.4)',
          }}
        >
          <RotateCw size={14} aria-hidden="true" />
          <span>{retryLabel}</span>
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message, icon: Icon }) {
  return (
    <div
      style={{
        padding: '2rem 1rem',
        textAlign: 'center',
        color: 'var(--text-muted)',
      }}
    >
      {Icon && <Icon size={32} style={{ margin: '0 auto 0.5rem auto', opacity: 0.5 }} aria-hidden="true" />}
      <p style={{ fontSize: '0.875rem' }}>{message}</p>
    </div>
  );
}

