import React from 'react';
import { Scale, AlertCircle, CheckCircle, Cpu, FileText, ArrowRight } from 'lucide-react';
import MetricCard from '../components/MetricCard';

export default function DashboardPage({ setActiveTab }) {
  return (
    <div>
      {/* Hero / Overview Header */}
      <div style={{ marginBottom: '2rem' }}>
        <h1 style={{ fontSize: '1.75rem', fontWeight: 700, marginBottom: '0.5rem' }}>
          ClosureIQ — AI-Powered Financial Close Assistant
        </h1>
        <p style={{ color: 'var(--text-secondary)', maxWidth: '750px', fontSize: '0.95rem' }}>
          Accelerate month-end closing with deterministic financial matching, dual AI reasoning agents,
          RAG-grounded accounting SOP compliance, and Human-in-the-Loop decision controls.
        </p>
      </div>

      {/* Quick Metrics */}
      <div className="metrics-grid">
        <MetricCard
          title="Reconciliation Status"
          value="98.4%"
          subtitle="4,210 of 4,280 transactions matched"
          icon={Scale}
          color="var(--accent-emerald)"
        />
        <MetricCard
          title="Active Exceptions"
          value="12"
          subtitle="4 high severity requiring review"
          icon={AlertCircle}
          color="var(--accent-amber)"
        />
        <MetricCard
          title="AI Recommendations"
          value="8 Pending"
          subtitle="Grounded in accounting SOPs"
          icon={Cpu}
          color="var(--primary)"
        />
        <MetricCard
          title="HITL Approvals"
          value="94.2%"
          subtitle="Historical acceptance rate"
          icon={CheckCircle}
          color="var(--accent-blue)"
        />
      </div>

      {/* Two Specialized AI Agents Banner */}
      <div className="card" style={{ marginBottom: '2rem', background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(31, 41, 55, 0.6) 100%)' }}>
        <h2 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Cpu size={20} color="var(--primary)" />
          Two-Agent Collaborative Intelligence Architecture
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
          <div style={{ padding: '1rem', background: 'rgba(17, 24, 39, 0.5)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
            <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#818cf8', marginBottom: '0.35rem' }}>
              Agent 1: Financial Review Agent
            </h3>
            <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
              Evaluates ledger summary health, macro trends, and ensures period-over-period balance sanity.
            </p>
          </div>
          <div style={{ padding: '1rem', background: 'rgba(17, 24, 39, 0.5)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
            <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--accent-blue)', marginBottom: '0.35rem' }}>
              Agent 2: Exception Analysis Agent
            </h3>
            <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
              Deep-dives into specific discrepancies, consults ChromaDB policy RAG, and proposes journal entries for human approval.
            </p>
          </div>
        </div>
      </div>

      {/* Quick Action Navigation */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
        <button
          className="btn btn-secondary"
          onClick={() => setActiveTab('reconciliation')}
          style={{ justifyContent: 'space-between', padding: '1rem 1.25rem' }}
        >
          <span>Open Reconciliation Engine</span>
          <ArrowRight size={16} />
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => setActiveTab('exceptions')}
          style={{ justifyContent: 'space-between', padding: '1rem 1.25rem' }}
        >
          <span>Inspect Financial Exceptions</span>
          <ArrowRight size={16} />
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => setActiveTab('approvals')}
          style={{ justifyContent: 'space-between', padding: '1rem 1.25rem' }}
        >
          <span>Review HITL Approvals</span>
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
