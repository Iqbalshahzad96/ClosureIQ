import React from 'react';

export default function MetricCard({ title, value, subtitle, icon: Icon, color = 'var(--primary)' }) {
  return (
    <div className="metric-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="metric-label">{title}</span>
        {Icon && (
          <div style={{ color, background: 'rgba(255,255,255,0.05)', padding: 6, borderRadius: 6 }}>
            <Icon size={18} />
          </div>
        )}
      </div>
      <div className="metric-value">{value}</div>
      {subtitle && <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{subtitle}</div>}
    </div>
  );
}
