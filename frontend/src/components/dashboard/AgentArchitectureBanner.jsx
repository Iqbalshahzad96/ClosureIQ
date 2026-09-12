import React from 'react';
import { Cpu } from 'lucide-react';

export default function AgentArchitectureBanner() {
  return (
    <section
      className="card"
      style={{
        marginBottom: '2rem',
        background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(31, 41, 55, 0.6) 100%)',
      }}
      aria-labelledby="agent-architecture-title"
    >
      <h2
        id="agent-architecture-title"
        style={{
          fontSize: '1.15rem',
          fontWeight: 600,
          marginBottom: '1rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
        }}
      >
        <Cpu size={20} color="var(--primary)" aria-hidden="true" />
        Two-Agent Collaborative Intelligence Architecture
      </h2>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap: '1.5rem',
        }}
      >
        <div
          style={{
            padding: '1rem',
            background: 'rgba(17, 24, 39, 0.5)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-color)',
          }}
        >
          <h3
            style={{
              fontSize: '0.95rem',
              fontWeight: 600,
              color: '#818cf8',
              marginBottom: '0.35rem',
            }}
          >
            Agent 1: Exception Review Agent
          </h3>
          <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
            Classifies exceptions and explains financial context without recalculation.
          </p>
        </div>

        <div
          style={{
            padding: '1rem',
            background: 'rgba(17, 24, 39, 0.5)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-color)',
          }}
        >
          <h3
            style={{
              fontSize: '0.95rem',
              fontWeight: 600,
              color: 'var(--accent-blue)',
              marginBottom: '0.35rem',
            }}
          >
            Agent 2: Exception Analysis Agent
          </h3>
          <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>
            Performs RAG-grounded investigation and recommendations; does not directly create journal entries.
          </p>
        </div>
      </div>
    </section>
  );
}

