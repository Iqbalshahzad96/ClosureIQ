import React from 'react';
import { LineChart, Activity, ShieldCheck, Zap } from 'lucide-react';
import MetricCard from '../components/MetricCard';

export default function ObservabilityPage() {
  return (
    <div>
      <div style={{ marginBottom: '1.5rem' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Observability & Telemetry</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Live metrics, LangGraph run traces, MCP execution logs, token usage, and audit logs.
        </p>
      </div>

      <div className="metrics-grid">
        <MetricCard
          title="Total Orchestrator Runs"
          value="0"
          subtitle="System initialized"
          icon={Activity}
        />
        <MetricCard
          title="Average Latency"
          value="0.0 ms"
          subtitle="Real-time tracking"
          icon={Zap}
        />
        <MetricCard
          title="Token Consumption"
          value="0"
          subtitle="Gemini API tokens"
          icon={LineChart}
        />
        <MetricCard
          title="Audit Trail Records"
          value="0"
          subtitle="SQLite immutable trace log"
          icon={ShieldCheck}
        />
      </div>

      <div className="card">
        <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Run Traces & Audit Logs</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
          No workflow runs recorded yet. Orchestrator trace logs will be streamed here during execution.
        </p>
      </div>
    </div>
  );
}
