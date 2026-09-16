import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  FileSpreadsheet,
  Building2,
  Receipt,
  Scale,
  TrendingDown,
  Layers,
  ArrowUpDown,
  Calendar,
  Sparkles,
  Info,
} from 'lucide-react';
import {
  fetchFinancialDataSummary,
  fetchFinancialDataPreview,
  formatFinanceCurrency,
  formatFinanceDate,
} from '../../services/financialDataService';

const TYPE_CONFIG = {
  bank_statements: {
    label: 'Bank Statements',
    icon: Building2,
    badgeColor: '#3b82f6',
    description: 'Bank transaction lines & clearing accounts',
  },
  general_ledger: {
    label: 'General Ledger',
    icon: FileSpreadsheet,
    badgeColor: '#8b5cf6',
    description: 'Double-entry journal postings & vouchers',
  },
  trial_balance: {
    label: 'Trial Balance',
    icon: Scale,
    badgeColor: '#10b981',
    description: 'Period debit/credit control balances',
  },
  ap_invoices: {
    label: 'AP Invoices',
    icon: Receipt,
    badgeColor: '#f59e0b',
    description: 'Vendor bills & payable invoices',
  },
  fixed_assets: {
    label: 'Fixed Assets',
    icon: Layers,
    badgeColor: '#06b6d4',
    description: 'Capital asset register & cost basis',
  },
  accruals: {
    label: 'Accruals',
    icon: Sparkles,
    badgeColor: '#ec4899',
    description: 'Accrued expenses & period adjustments',
  },
  depreciation: {
    label: 'Depreciation',
    icon: TrendingDown,
    badgeColor: '#6366f1',
    description: 'Straight-line schedules & net book values',
  },
};

export default function FinancialDatabaseSection({ refreshTrigger }) {
  const [summary, setSummary] = useState(null);
  const [selectedType, setSelectedType] = useState('bank_statements');
  const [previewData, setPreviewData] = useState(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState(true);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [summaryError, setSummaryError] = useState(null);
  const [previewError, setPreviewError] = useState(null);

  const loadSummary = useCallback(async () => {
    setIsLoadingSummary(true);
    setSummaryError(null);
    try {
      const data = await fetchFinancialDataSummary();
      setSummary(data);
    } catch (err) {
      setSummaryError(err.message || 'Failed to load financial database summary.');
    } finally {
      setIsLoadingSummary(false);
    }
  }, []);

  const loadPreview = useCallback(async (type) => {
    if (!type) return;
    setIsLoadingPreview(true);
    setPreviewError(null);
    try {
      const data = await fetchFinancialDataPreview(type, 15);
      setPreviewData(data);
    } catch (err) {
      setPreviewError(err.message || `Failed to load preview for ${type}.`);
    } finally {
      setIsLoadingPreview(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary, refreshTrigger]);

  useEffect(() => {
    loadPreview(selectedType);
  }, [loadPreview, selectedType, refreshTrigger]);

  const handleTypeSelect = (typeKey) => {
    setSelectedType(typeKey);
  };

  const reconStats = {
    total_records: summary?.all_time_reconciliation?.total_records ?? 0,
    reconciled_records: summary?.all_time_reconciliation?.reconciled_records ?? 0,
    unreconciled_records: summary?.all_time_reconciliation?.unreconciled_records ?? 0,
    reconciled_percentage: summary?.all_time_reconciliation?.reconciled_percentage ?? 0.0,
    bank_total: summary?.all_time_reconciliation?.bank_total ?? 0,
    bank_reconciled: summary?.all_time_reconciliation?.bank_reconciled ?? 0,
    gl_total: summary?.all_time_reconciliation?.gl_total ?? 0,
    gl_reconciled: summary?.all_time_reconciliation?.gl_reconciled ?? 0,
  };

  const isDatabaseEmpty = (reconStats.total_records || 0) === 0 &&
    (!summary?.data_types || Object.values(summary.data_types).every((t) => (t.total_count || 0) === 0));

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1.5rem',
        marginTop: '1rem',
      }}
    >
      {/* Section Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '1rem',
          paddingBottom: '0.75rem',
          borderBottom: '1px solid var(--border-color)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: 'rgba(99, 102, 241, 0.15)',
              color: 'var(--primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Database size={18} />
          </div>
          <div>
            <h2
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                color: 'var(--text-primary)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              Financial Data in Database
            </h2>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
              Live inventory of ingested financial records, reconciliation health, and schedules
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => {
            loadSummary();
            loadPreview(selectedType);
          }}
          disabled={isLoadingSummary || isLoadingPreview}
          data-testid="refresh-database-btn"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.4rem',
            padding: '0.45rem 0.85rem',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-primary)',
            fontSize: '0.8rem',
            fontWeight: 500,
            cursor: isLoadingSummary ? 'not-allowed' : 'pointer',
            transition: 'all 0.15s ease',
          }}
        >
          <RefreshCw size={14} className={isLoadingSummary || isLoadingPreview ? 'animate-spin' : ''} />
          <span>Refresh Data</span>
        </button>
      </div>

      {/* Error State */}
      {summaryError && (
        <div
          role="alert"
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '0.75rem',
            padding: '1rem',
            backgroundColor: 'rgba(244, 63, 94, 0.1)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--accent-rose)',
            fontSize: '0.875rem',
          }}
        >
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ flex: 1 }}>
            <p style={{ fontWeight: 600, margin: 0 }}>Failed to load financial data summary</p>
            <p style={{ color: 'var(--text-primary)', fontSize: '0.825rem', marginTop: '0.25rem' }}>
              {summaryError}
            </p>
          </div>
          <button
            type="button"
            onClick={loadSummary}
            style={{
              padding: '0.35rem 0.75rem',
              backgroundColor: 'rgba(244, 63, 94, 0.2)',
              border: '1px solid rgba(244, 63, 94, 0.4)',
              borderRadius: 'var(--radius-sm)',
              color: '#fff',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* All-Time Reconciliation Metric Banner */}
      {!summaryError && (
        <div
          data-testid="all-time-reconciliation-card"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '1rem',
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            padding: '1.25rem 1.5rem',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.04)',
          }}
        >
          {/* Main Percentage Metric */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              borderRight: '1px solid var(--border-color)',
              paddingRight: '1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
              <CheckCircle2 size={16} color="var(--primary)" />
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                All-Time Reconciled Percentage
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
              <span
                data-testid="all-time-reconciled-percentage-value"
                style={{
                  fontSize: '2rem',
                  fontWeight: 800,
                  color: reconStats.reconciled_percentage >= 80 ? 'var(--accent-emerald)' : 'var(--primary)',
                  letterSpacing: '-0.03em',
                }}
              >
                {isLoadingSummary ? '—' : `${reconStats.reconciled_percentage}%`}
              </span>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                across GL & bank records
              </span>
            </div>
          </div>

          {/* Total Considered */}
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
              Total Records Considered
            </span>
            <span
              data-testid="all-time-total-records"
              style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '0.2rem' }}
            >
              {isLoadingSummary ? '—' : Number(reconStats.total_records || 0).toLocaleString()}
            </span>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
              {reconStats.bank_total} Bank • {reconStats.gl_total} GL Postings
            </span>
          </div>

          {/* Reconciled Count */}
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
              Reconciled Records
            </span>
            <span
              data-testid="all-time-reconciled-records"
              style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--accent-emerald)', marginTop: '0.2rem' }}
            >
              {isLoadingSummary ? '—' : Number(reconStats.reconciled_records || 0).toLocaleString()}
            </span>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
              Matched & confirmed
            </span>
          </div>

          {/* Unreconciled Count */}
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
              Unreconciled Records
            </span>
            <span
              data-testid="all-time-unreconciled-records"
              style={{ fontSize: '1.35rem', fontWeight: 700, color: reconStats.unreconciled_records > 0 ? 'var(--accent-rose)' : 'var(--text-muted)', marginTop: '0.2rem' }}
            >
              {isLoadingSummary ? '—' : Number(reconStats.unreconciled_records || 0).toLocaleString()}
            </span>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
              Pending close resolution
            </span>
          </div>
        </div>
      )}

      {/* Empty Database State Notice */}
      {isDatabaseEmpty && !isLoadingSummary && !summaryError && (
        <div
          data-testid="empty-database-notice"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '1rem',
            padding: '1.25rem',
            backgroundColor: 'rgba(99, 102, 241, 0.05)',
            border: '1px dashed var(--border-color)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-secondary)',
          }}
        >
          <Info size={22} color="var(--primary)" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <p style={{ fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
              Database is currently empty
            </p>
            <p style={{ fontSize: '0.825rem', margin: '0.25rem 0 0 0' }}>
              Upload your financial spreadsheets or bank statements in the section above to populate ledger balances and run reconciliation.
            </p>
          </div>
        </div>
      )}

      {/* 7 Data Type Cards / Tabs */}
      <div
        role="tablist"
        aria-label="Financial Data Types"
        data-testid="financial-data-cards-grid"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '0.85rem',
        }}
      >
        {Object.entries(TYPE_CONFIG).map(([typeKey, cfg]) => {
          const typeData = summary?.data_types?.[typeKey] || {
            total_count: 0,
            reconciled_count: null,
            unreconciled_count: null,
            latest_import_date: null,
          };
          const isSelected = selectedType === typeKey;
          const IconComponent = cfg.icon;

          return (
            <div
              key={typeKey}
              role="tab"
              aria-selected={isSelected}
              tabIndex={0}
              onClick={() => handleTypeSelect(typeKey)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  handleTypeSelect(typeKey);
                }
              }}
              data-testid={`data-card-${typeKey}`}
              style={{
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                padding: '1rem',
                backgroundColor: isSelected ? 'var(--primary-glow)' : 'var(--bg-card)',
                border: `1.5px solid ${isSelected ? 'var(--primary)' : 'var(--border-color)'}`,
                borderRadius: 'var(--radius-md)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                boxShadow: isSelected ? '0 4px 12px rgba(99, 102, 241, 0.15)' : 'none',
                outline: 'none',
              }}
            >
              {/* Card Top */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div
                      style={{
                        width: 28,
                        height: 28,
                        borderRadius: 6,
                        backgroundColor: isSelected ? 'var(--primary)' : 'rgba(255, 255, 255, 0.06)',
                        color: isSelected ? '#fff' : cfg.badgeColor,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <IconComponent size={15} />
                    </div>
                    <span
                      style={{
                        fontSize: '0.9rem',
                        fontWeight: 600,
                        color: isSelected ? '#fff' : 'var(--text-primary)',
                      }}
                    >
                      {cfg.label}
                    </span>
                  </div>
                  {typeData.is_derived && (
                    <span
                      style={{
                        fontSize: '0.65rem',
                        padding: '0.15rem 0.4rem',
                        borderRadius: 4,
                        backgroundColor: 'rgba(99, 102, 241, 0.2)',
                        color: 'var(--primary)',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                      }}
                    >
                      Calculated
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.4rem', marginTop: '0.35rem' }}>
                  <span
                    data-testid={`card-count-${typeKey}`}
                    style={{
                      fontSize: '1.4rem',
                      fontWeight: 700,
                      color: isSelected ? '#fff' : 'var(--text-primary)',
                    }}
                  >
                    {isLoadingSummary ? '—' : typeData.total_count.toLocaleString()}
                  </span>
                  <span style={{ fontSize: '0.725rem', color: isSelected ? 'rgba(255, 255, 255, 0.7)' : 'var(--text-muted)' }}>
                    records
                  </span>
                </div>
              </div>

              {/* Card Footer Info */}
              <div style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: isSelected ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid var(--border-color)', fontSize: '0.725rem' }}>
                {/* Reconciled / Unreconciled breakdown if applicable */}
                {typeData.reconciled_count !== null && typeData.reconciled_count !== undefined ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                    <span style={{ color: 'var(--accent-emerald)', fontWeight: 600 }}>
                      ✓ {typeData.reconciled_count} {typeData.reconciled_label || 'Reconciled'}
                    </span>
                    <span style={{ color: typeData.unreconciled_count > 0 ? 'var(--accent-rose)' : 'var(--text-muted)', fontWeight: 500 }}>
                      {typeData.unreconciled_count} {typeData.unreconciled_label || 'Unreconciled'}
                    </span>
                  </div>
                ) : (
                  <div style={{ color: isSelected ? 'rgba(255, 255, 255, 0.6)' : 'var(--text-muted)', marginBottom: '0.35rem' }}>
                    {cfg.description}
                  </div>
                )}

                {/* Latest Import Date */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', color: isSelected ? 'rgba(255, 255, 255, 0.65)' : 'var(--text-muted)' }}>
                  <Calendar size={11} />
                  <span>
                    {formatFinanceDate(typeData.latest_import_date)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Preview Table Section */}
      <div
        data-testid="preview-table-container"
        style={{
          display: 'flex',
          flexDirection: 'column',
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-md)',
          overflow: 'hidden',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.04)',
        }}
      >
        {/* Table Header / Subtitle */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border-color)',
            backgroundColor: 'var(--bg-secondary)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {TYPE_CONFIG[selectedType]?.label || 'Record'} Preview (Latest Records)
            </span>
            <span
              style={{
                fontSize: '0.725rem',
                padding: '0.15rem 0.5rem',
                borderRadius: 12,
                backgroundColor: 'rgba(99, 102, 241, 0.12)',
                color: 'var(--primary)',
                fontWeight: 600,
              }}
            >
              {previewData?.records?.length || 0} displayed
            </span>
          </div>

          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Showing top records sorted by date
          </span>
        </div>

        {/* Table Body / Loading / Empty State */}
        {isLoadingPreview ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 0.75rem auto', color: 'var(--primary)' }} />
            <p style={{ margin: 0 }}>Loading {TYPE_CONFIG[selectedType]?.label} preview records...</p>
          </div>
        ) : previewError ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--accent-rose)', fontSize: '0.875rem' }}>
            <AlertCircle size={24} style={{ margin: '0 auto 0.5rem auto' }} />
            <p style={{ fontWeight: 600, margin: 0 }}>Unable to load preview</p>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-primary)', margin: '0.25rem 0 0.75rem 0' }}>{previewError}</p>
            <button
              type="button"
              onClick={() => loadPreview(selectedType)}
              style={{
                padding: '0.4rem 0.85rem',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '0.75rem',
                cursor: 'pointer',
              }}
            >
              Retry
            </button>
          </div>
        ) : !previewData?.records || previewData.records.length === 0 ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            <FileSpreadsheet size={28} style={{ margin: '0 auto 0.75rem auto', opacity: 0.4 }} />
            <p style={{ fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>
              No {TYPE_CONFIG[selectedType]?.label} in database
            </p>
            <p style={{ fontSize: '0.8rem', margin: '0.25rem 0 0 0' }}>
              Import a spreadsheet or statement file in the section above to populate this table.
            </p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table
              data-testid="preview-table"
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                textAlign: 'left',
                fontSize: '0.825rem',
              }}
            >
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', backgroundColor: 'rgba(255, 255, 255, 0.02)' }}>
                  {previewData.columns?.map((col) => (
                    <th
                      key={col.key}
                      style={{
                        padding: '0.75rem 1rem',
                        fontWeight: 600,
                        color: 'var(--text-secondary)',
                        fontSize: '0.775rem',
                        textTransform: 'uppercase',
                        letterSpacing: '0.03em',
                      }}
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewData.records.map((row, idx) => (
                  <tr
                    key={row.id || idx}
                    style={{
                      borderBottom: '1px solid var(--border-color)',
                      transition: 'background-color 0.1s ease',
                    }}
                  >
                    {previewData.columns?.map((col) => {
                      const val = row[col.key];

                      if (col.is_currency) {
                        return (
                          <td
                            key={col.key}
                            style={{
                              padding: '0.75rem 1rem',
                              fontVariantNumeric: 'tabular-nums',
                              fontWeight: 500,
                              color: 'var(--text-primary)',
                            }}
                          >
                            {formatFinanceCurrency(val, row.currency_code || 'KES')}
                          </td>
                        );
                      }

                      if (col.is_status) {
                        const isGood =
                          String(val).toLowerCase().includes('reconciled') ||
                          String(val).toLowerCase() === 'paid' ||
                          String(val).toLowerCase() === 'active';
                        return (
                          <td key={col.key} style={{ padding: '0.75rem 1rem' }}>
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.25rem',
                                padding: '0.2rem 0.55rem',
                                borderRadius: 12,
                                fontSize: '0.725rem',
                                fontWeight: 600,
                                backgroundColor: isGood ? 'rgba(16, 185, 129, 0.12)' : 'rgba(244, 63, 94, 0.12)',
                                color: isGood ? 'var(--accent-emerald)' : 'var(--accent-rose)',
                              }}
                            >
                              {val || '-'}
                            </span>
                          </td>
                        );
                      }

                      return (
                        <td
                          key={col.key}
                          style={{
                            padding: '0.75rem 1rem',
                            color: 'var(--text-primary)',
                          }}
                        >
                          {val !== null && val !== undefined && val !== '' ? String(val) : '-'}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
