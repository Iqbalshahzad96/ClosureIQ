import React from 'react';
import { UploadCloud, CheckCircle } from 'lucide-react';

export default function IngestionStatusCard() {
  return (
    <section className="card" style={{ marginBottom: '2rem' }} aria-labelledby="ingestion-status-title">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1rem',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <h2
          id="ingestion-status-title"
          style={{ fontSize: '1.15rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <UploadCloud size={20} color="var(--primary)" aria-hidden="true" />
          Data Ingestion Pipeline Status
        </h2>
        <span
          className="badge badge-indigo"
          style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} aria-hidden="true" />
          Pipeline Ready
        </span>
      </div>

      <div
        style={{
          background: 'rgba(17, 24, 39, 0.4)',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border-subtle)',
          padding: '1.25rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
          <div
            style={{
              color: 'var(--accent-blue)',
              background: 'rgba(56, 189, 248, 0.1)',
              padding: '0.5rem',
              borderRadius: 'var(--radius-sm)',
              marginTop: '0.1rem',
            }}
          >
            <CheckCircle size={20} aria-hidden="true" />
          </div>
          <div>
            <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
              No import status available yet
            </h3>
            <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              The ingestion service processes financial statements via batch triggers and external feeds.
              Historical ingestion status will display here when import logs are synchronized.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

