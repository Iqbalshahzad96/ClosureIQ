import React from 'react';
import { ShieldCheck, Activity } from 'lucide-react';
import StatusBadge from './StatusBadge';

export default function Header({ healthStatus }) {
  const isHealthy = healthStatus?.status === 'healthy';

  return (
    <header className="header">
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <h2 className="title-lg" style={{ fontSize: '1.15rem' }}>
          Month-End Financial Close Workspace
        </h2>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          Period: Not selected
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <StatusBadge
          status={isHealthy ? 'Connected' : 'Connecting'}
          variant={isHealthy ? 'emerald' : 'amber'}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
          <ShieldCheck size={18} color="var(--primary)" />
          <span>HITL Mode: Active</span>
        </div>
      </div>
    </header>
  );
}
