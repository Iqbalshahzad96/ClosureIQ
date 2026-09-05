import React from 'react';
import { CheckSquare } from 'lucide-react';

export default function ApprovalsPage() {
  return (
    <div>
      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Human-in-the-Loop (HITL) Approvals</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Mandatory human verification gate for all AI recommendations before adjustments are finalized.
        </p>
      </div>

      <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
        <CheckSquare size={48} color="var(--accent-emerald)" style={{ margin: '0 auto 1rem auto', opacity: 0.8 }} />
        <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Approval Workflow Queue Ready</h3>
        <p style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: '0 auto' }}>
          Accountants will review Agent 2 proposed journal adjustments, examine RAG policy citations, and click Approve or Reject.
        </p>
      </div>
    </div>
  );
}
