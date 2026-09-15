import React, { useState, useEffect } from 'react';
import {
  AlertTriangle,
  Filter,
  RefreshCw,
  Search,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  Layers,
  ChevronDown,
  ChevronUp,
  Tag,
  Hash,
} from 'lucide-react';
import { fetchExceptions } from '../services/reconciliationService';

export function sanitizeErrorMessage(rawError) {
  if (!rawError) return 'An error occurred while loading exceptions.';
  const str = typeof rawError === 'string' ? rawError : rawError.message || String(rawError);
  const sensitivePatterns = [
    /sqlite/i,
    /operationalerror/i,
    /syntaxerror/i,
    /database/i,
    /traceback/i,
    /table:/i,
    /column:/i,
    /\.py\b/i,
    /\.js\b/i,
    /sql/i,
    /select /i,
    /insert /i,
    /update /i,
    /delete /i,
  ];
  if (sensitivePatterns.some((pattern) => pattern.test(str))) {
    return 'Unable to load financial exceptions due to a server error. Please try again later.';
  }
  return str || 'Unable to load financial exceptions due to a server error. Please try again later.';
}

export function normalizeExceptionsList(raw) {
  let list = [];
  if (Array.isArray(raw)) {
    list = raw;
  } else if (raw && Array.isArray(raw.exceptions)) {
    list = raw.exceptions;
  } else if (raw && Array.isArray(raw.items)) {
    list = raw.items;
  } else if (raw && Array.isArray(raw.data)) {
    list = raw.data;
  }

  return list
    .filter((item) => item !== null && typeof item === 'object')
    .map((item, index) => {
      const id = item.id ? String(item.id) : `exc-synthetic-${index}`;

      let amountVariance = null;
      if (item.amount_variance !== undefined && item.amount_variance !== null) {
        const num = Number(item.amount_variance);
        amountVariance = Number.isFinite(num) ? num : null;
      } else if (item.variance_amount !== undefined && item.variance_amount !== null) {
        const num = Number(item.variance_amount);
        amountVariance = Number.isFinite(num) ? num : null;
      } else if (item.variance !== undefined && item.variance !== null) {
        const num = Number(item.variance);
        amountVariance = Number.isFinite(num) ? num : null;
      }

      return {
        ...item,
        id,
        account_code: item.account_code || item.account_id || 'General Exception',
        category: item.category || 'General',
        severity: item.severity || 'MEDIUM',
        status: item.status || 'OPEN',
        description: item.description || 'No description provided',
        period: item.period || 'N/A',
        run_id: item.run_id || null,
        amount_variance: amountVariance,
        variance_amount: amountVariance,
        lineage: (item.lineage && typeof item.lineage === 'object') ? item.lineage : {},
        details: (item.details && typeof item.details === 'object') ? item.details : null,
      };
    });
}

export default function ExceptionsPage() {
  const [exceptions, setExceptions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('');
  const [period, setPeriod] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const categories = [
    { label: 'All Categories', value: '' },
    { label: 'Reconciliation', value: 'RECONCILIATION' },
    { label: 'Accrual', value: 'ACCRUAL' },
    { label: 'Depreciation', value: 'DEPRECIATION' },
  ];

  const statuses = [
    { label: 'All Statuses', value: '' },
    { label: 'Open', value: 'OPEN' },
    { label: 'In Review', value: 'IN_REVIEW' },
    { label: 'Resolved', value: 'RESOLVED' },
  ];

  const loadExceptions = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchExceptions({
        period: period.trim() || undefined,
        category: selectedCategory || undefined,
        status: selectedStatus || undefined,
      });
      setExceptions(normalizeExceptionsList(data));
    } catch (err) {
      setError(sanitizeErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExceptions();
  }, [selectedCategory, selectedStatus, period]);

  const filteredExceptions = exceptions.filter((exc) => {
    if (!exc) return false;
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    const accountCode = (exc.account_code || '').toLowerCase();
    const desc = (exc.description || '').toLowerCase();
    const cat = (exc.category || '').toLowerCase();
    const id = (exc.id || '').toLowerCase();
    const runId = (exc.run_id || '').toLowerCase();
    return accountCode.includes(term) || desc.includes(term) || cat.includes(term) || id.includes(term) || runId.includes(term);
  });

  const getSeverityBadge = (severity) => {
    const sev = (severity || 'MEDIUM').toUpperCase();
    if (sev === 'HIGH' || sev === 'CRITICAL') {
      return <span className="badge badge-danger">High Severity</span>;
    }
    if (sev === 'MEDIUM') {
      return <span className="badge badge-warning">Medium Severity</span>;
    }
    return <span className="badge badge-info">Low Severity</span>;
  };

  const getStatusBadge = (status) => {
    const st = (status || 'OPEN').toUpperCase();
    if (st === 'RESOLVED') {
      return <span className="badge badge-success"><CheckCircle2 size={12} style={{ marginRight: 4 }} /> Resolved</span>;
    }
    if (st === 'IN_REVIEW') {
      return <span className="badge badge-warning"><Clock size={12} style={{ marginRight: 4 }} /> In Review</span>;
    }
    return <span className="badge badge-danger">Open</span>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Financial Exceptions Feed</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            System-detected reconciliation variances, missing accruals, and depreciation anomalies with full audit lineage.
          </p>
        </div>
        <button
          className="button button-outline"
          onClick={loadExceptions}
          disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          <span>Refresh Feed</span>
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className="card" style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'center', padding: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: '1 1 240px' }}>
          <Search size={16} color="var(--text-muted)" />
          <input
            type="text"
            placeholder="Search by account, ID, or description..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '0.5rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-color)',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
            }}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Filter size={16} color="var(--text-muted)" />
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            style={{
              padding: '0.5rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-color)',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
            }}
          >
            {categories.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            style={{
              padding: '0.5rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-color)',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
            }}
          >
            {statuses.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.825rem', color: 'var(--text-muted)' }}>Period:</span>
          <input
            type="text"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="All periods"
            style={{
              width: '100px',
              padding: '0.5rem 0.75rem',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-color)',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
            }}
          />
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--accent-rose)', color: 'var(--accent-rose)' }}>
          {error}
        </div>
      )}

      {/* Content list */}
      {loading && exceptions.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
          <RefreshCw size={32} className="spin" style={{ margin: '0 auto 1rem auto', color: 'var(--primary)' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading financial exceptions...</p>
        </div>
      ) : filteredExceptions.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
          <AlertTriangle size={48} color="var(--accent-amber)" style={{ margin: '0 auto 1rem auto', opacity: 0.8 }} />
          <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>No Exceptions Found</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: '0 auto' }}>
            {exceptions.length === 0
              ? 'No exceptions detected for this period. Run a close workflow from the Reconciliation page to analyze financial data.'
              : 'No exceptions match your current search and filter criteria.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {filteredExceptions.map((exc) => {
            if (!exc) return null;
            const isExpanded = expandedId === exc.id;
            const lineage = exc.lineage || {};
            const variance = exc.amount_variance !== null && exc.amount_variance !== undefined
              ? Number(exc.amount_variance)
              : null;

            return (
              <div
                key={exc.id}
                className="card"
                style={{
                  padding: '1.25rem',
                  borderLeft: `4px solid ${
                    (exc.severity || '').toUpperCase() === 'HIGH' || (exc.severity || '').toUpperCase() === 'CRITICAL'
                      ? 'var(--accent-rose)'
                      : (exc.severity || '').toUpperCase() === 'MEDIUM'
                      ? 'var(--accent-amber)'
                      : 'var(--primary)'
                  }`,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
                onClick={() => setExpandedId(isExpanded ? null : exc.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>
                        {exc.account_code || 'General Exception'}
                      </span>
                      <span className="badge badge-neutral" style={{ textTransform: 'uppercase', fontSize: '0.75rem' }}>
                        {exc.category || 'General'}
                      </span>
                      {getSeverityBadge(exc.severity)}
                      {getStatusBadge(exc.status)}
                    </div>

                    <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: '0.25rem 0' }}>
                      {exc.description || 'No description provided'}
                    </p>

                    <div style={{ display: 'flex', gap: '1.25rem', marginTop: '0.5rem', fontSize: '0.8rem', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                      <span><strong>Period:</strong> {exc.period || 'N/A'}</span>
                      {exc.run_id && (
                        <span><strong>Run ID:</strong> {exc.run_id.slice(0, 8)}</span>
                      )}
                      {variance !== null && (
                        <span>
                          <strong>Variance:</strong>{' '}
                          <span style={{ color: variance !== 0 ? 'var(--accent-rose)' : 'inherit', fontWeight: 600 }}>
                            ${variance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                        </span>
                      )}
                      <span><strong>ID:</strong> {exc.id ? exc.id.slice(0, 8) : 'N/A'}</span>
                    </div>
                  </div>

                  <button
                    className="button button-ghost"
                    style={{ padding: '0.25rem 0.5rem' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedId(isExpanded ? null : exc.id);
                    }}
                    aria-label="Toggle details"
                  >
                    {isExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                  </button>
                </div>

                {/* Expanded Lineage & Details */}
                {isExpanded && (
                  <div
                    style={{
                      marginTop: '1rem',
                      paddingTop: '1rem',
                      borderTop: '1px solid var(--border-color)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.75rem',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <Layers size={15} color="var(--primary)" /> Source Lineage & Provenance
                    </h4>

                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                        gap: '0.75rem',
                        padding: '0.75rem',
                        background: 'var(--bg-primary)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '0.8rem',
                      }}
                    >
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Source File:</span>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)', wordBreak: 'break-all' }}>
                          {lineage.source_file || lineage.file_id || 'System Generated'}
                        </div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Sheet / Section:</span>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          {lineage.sheet_name || lineage.source_row_identifier || 'N/A'}
                        </div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Source Row / Record ID:</span>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
                          {lineage.row_number !== undefined ? `Row #${lineage.row_number}` : lineage.record_id || 'N/A'}
                        </div>
                      </div>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Import Batch:</span>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
                          {lineage.import_batch_id ? lineage.import_batch_id.slice(0, 8) : 'Direct'}
                        </div>
                      </div>
                    </div>

                    {exc.details && (
                      <div>
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Raw Details / Audit Payload:</span>
                        <pre
                          style={{
                            marginTop: '0.35rem',
                            padding: '0.75rem',
                            background: 'var(--bg-primary)',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.75rem',
                            overflowX: 'auto',
                            color: 'var(--text-secondary)',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          {JSON.stringify(exc.details, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
