import React from 'react';
import { AlertTriangle } from 'lucide-react';

export default function ExceptionsPage() {
  return (
    <div>
      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Financial Exceptions</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Identified variances, missing accruals, and depreciation anomalies flagged by the financial engine.
        </p>
      </div>

      <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
        <AlertTriangle size={48} color="var(--accent-amber)" style={{ margin: '0 auto 1rem auto', opacity: 0.8 }} />
        <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Exceptions Feed Foundation Initialized</h3>
        <p style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: '0 auto' }}>
          When financial engine calculations detect tolerance breaches, structured exception cards analyzed by Agent 2 will appear here.
        </p>
      </div>
    </div>
  );
}
