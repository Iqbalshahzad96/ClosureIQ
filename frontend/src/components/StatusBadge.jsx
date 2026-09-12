import React from 'react';

export default function StatusBadge({ status, variant = 'indigo' }) {
  const variantClass = {
    emerald: 'badge-emerald',
    amber: 'badge-amber',
    indigo: 'badge-indigo',
    rose: 'badge-rose',
  }[variant] || 'badge-indigo';

  return (
    <span className={`badge ${variantClass}`}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />
      {status}
    </span>
  );
}
