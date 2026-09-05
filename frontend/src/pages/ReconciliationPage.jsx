import React from 'react';
import { Scale, Play } from 'lucide-react';

export default function ReconciliationPage() {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>GL-to-Bank Reconciliation</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Deterministic rule-based matching engine comparing General Ledger with bank statement feeds.
          </p>
        </div>
        <button className="btn btn-primary">
          <Play size={16} />
          <span>Run Reconciliation</span>
        </button>
      </div>

      <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
        <Scale size={48} color="var(--primary)" style={{ margin: '0 auto 1rem auto', opacity: 0.8 }} />
        <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Reconciliation Module Ready</h3>
        <p style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: '0 auto' }}>
          Deterministic matching algorithms (1-to-1 reference & date matching, 1-to-many aggregations) will execute here during Milestone 1.
        </p>
      </div>
    </div>
  );
}
