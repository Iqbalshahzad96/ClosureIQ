import React from 'react';
import { LayoutDashboard, UploadCloud, Scale, AlertTriangle, CheckSquare, LineChart, Sparkles } from 'lucide-react';

export default function Sidebar({ activeTab, setActiveTab }) {
  const menuItems = [
    { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
    { id: 'financial-upload', label: 'Financial Upload', icon: UploadCloud },
    { id: 'reconciliation', label: 'Reconciliation', icon: Scale },
    { id: 'exceptions', label: 'Exceptions', icon: AlertTriangle },
    { id: 'approvals', label: 'Approvals (HITL)', icon: CheckSquare },
    { id: 'observability', label: 'Observability', icon: LineChart },
  ];

  return (
    <aside className="sidebar">
      <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <div style={{ width: 34, height: 34, borderRadius: 8, background: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Sparkles size={20} color="#fff" />
        </div>
        <div>
          <h1 style={{ fontSize: '1.15rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-primary)' }}>ClosureIQ</h1>
          <p style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>Financial Close AI</p>
        </div>
      </div>

      <nav style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                padding: '0.75rem 1rem',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.9rem',
                fontWeight: isActive ? 600 : 400,
                color: isActive ? '#fff' : 'var(--text-secondary)',
                backgroundColor: isActive ? 'var(--primary)' : 'transparent',
                textAlign: 'left',
                transition: 'all 0.15s ease',
              }}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div style={{ marginTop: 'auto', padding: '1.25rem', borderTop: '1px solid var(--border-color)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
        <p>Capstone MVP • 7-Day Sprint</p>
        <p style={{ marginTop: '0.25rem' }}>2 Specialized Agents</p>
      </div>
    </aside>
  );
}
