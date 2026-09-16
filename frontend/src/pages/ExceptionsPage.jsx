import React, { useState, useEffect, useMemo } from 'react';
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
  ArrowRight,
  TrendingDown,
  TrendingUp,
  DollarSign,
  Building2,
  Receipt,
  FileText,
  ShieldAlert,
  HelpCircle,
} from 'lucide-react';
import { fetchExceptions, fetchExceptionsSummary } from '../services/reconciliationService';

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

export function parseExceptionFinanceContext(exc) {
  const desc = exc.description || '';
  const meta = exc.metadata || {};
  const record = meta.record || {};
  const cat = (exc.category || 'RECONCILIATION').toUpperCase();
  const amt = Math.abs(Number(exc.amount_variance || exc.variance_amount || record.amount || 0));

  let type = 'General Reconciliation Break';
  let title = 'Unmatched Transaction';
  let financialImpact = 'Requires accounting investigation and verification.';
  let suggestedAction = 'Review supporting voucher and bank statement documentation.';
  let badgeColor = 'var(--primary)';
  let accountLabel = exc.account_code && exc.account_code !== 'General Exception' ? exc.account_code : '';

  if (cat === 'RECONCILIATION') {
    const isBank = meta.source === 'BANK' || desc.toLowerCase().includes('bank statement') || desc.toLowerCase().includes('bank entry');
    const descLower = desc.toLowerCase();

    if (isBank) {
      if (descLower.includes('fee') || descLower.includes('charge') || descLower.includes('sc-') || descLower.includes('pb-')) {
        type = 'Bank Service Charge';
        title = 'Unrecorded Bank Fee / Charge';
        financialImpact = 'The bank deducted a tariff/service fee from the cash account that has not yet been booked in the GL.';
        suggestedAction = `Create adjusting journal entry: Debit 6100 (Bank Charges) $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })} / Credit 1010 (Cash at Bank) $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })}.`;
        badgeColor = 'var(--accent-rose)';
      } else if (descLower.includes('eft') || descLower.includes('wire') || descLower.includes('transfer') || Number(exc.amount_variance) < 0) {
        type = 'Unposted Wire / EFT Outflow';
        title = 'Cleared Bank Payment (Missing in GL)';
        financialImpact = 'An electronic funds transfer cleared the bank account, but no matching payment voucher exists in the general ledger.';
        suggestedAction = `Identify vendor/payee reference and post cash disbursement voucher for $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })}.`;
        badgeColor = 'var(--accent-amber)';
      } else {
        type = 'Unposted Bank Deposit';
        title = 'Cleared Deposit / Credit (Missing in GL)';
        financialImpact = 'Funds were deposited into the bank account without a corresponding cash receipt voucher in the GL.';
        suggestedAction = `Identify remittance advice and record cash receipt entry for $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })}.`;
        badgeColor = 'var(--accent-emerald)';
      }
      accountLabel = accountLabel || (record.bank_account_name || 'Bank Operating Account');
    } else {
      type = 'Unmatched GL Posting';
      title = 'GL Voucher Awaiting Bank Clearance';
      financialImpact = 'A voucher was posted in the General Ledger, but has not yet appeared on or cleared the official bank statement.';
      suggestedAction = 'Evaluate as a timing difference (Deposit in Transit or Outstanding Cheque). Monitor next cycle clearance.';
      badgeColor = 'var(--primary)';
      accountLabel = accountLabel || (record.account_code ? `GL Account ${record.account_code}` : 'GL Cash Ledger');
    }
  } else if (cat === 'ACCRUAL') {
    type = 'Accrual Schedule Variance';
    title = 'Missing or Discrepant Accrual';
    financialImpact = 'The period accrual posting differs materially from the historical baseline or expected contractual schedule.';
    suggestedAction = 'Validate recurring expense contracts and adjust accrual baseline estimate.';
    badgeColor = 'var(--accent-purple)';
  } else if (cat === 'DEPRECIATION') {
    type = 'Depreciation Schedule Break';
    title = 'Fixed Asset Depreciation Mismatch';
    financialImpact = 'Calculated straight-line depreciation differs from the posted amortization in the fixed asset subledger.';
    suggestedAction = 'Post correcting depreciation adjustment to accumulated depreciation and expense accounts.';
    badgeColor = 'var(--accent-cyan)';
  }

  return {
    type,
    title,
    accountLabel: accountLabel || 'General Cash Account',
    financialImpact,
    suggestedAction,
    badgeColor,
    amount: amt,
  };
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

      const parsed = parseExceptionFinanceContext(item);

      return {
        ...item,
        id,
        account_code: item.account_code || item.account_id || parsed.accountLabel,
        category: item.category || 'RECONCILIATION',
        severity: item.severity || 'MEDIUM',
        status: item.status || 'OPEN',
        description: item.description || 'No description provided',
        period: item.period || 'N/A',
        run_id: item.run_id || null,
        amount_variance: amountVariance,
        variance_amount: amountVariance,
        lineage: (item.lineage && typeof item.lineage === 'object') ? item.lineage : {},
        details: (item.details && typeof item.details === 'object') ? item.details : null,
        financeContext: parsed,
      };
    });
}

const PAGE_SIZE = 50;

export default function ExceptionsPage() {
  const [exceptions, setExceptions] = useState([]);
  const [summaryMetrics, setSummaryMetrics] = useState({
    total_count: 0,
    open_count: 0,
    in_review_count: 0,
    resolved_count: 0,
    high_severity_count: 0,
    gross_variance_volume: 0,
    unposted_bank_fees: 0,
  });
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('');
  const [activeTab, setActiveTab] = useState('ALL');
  const [period, setPeriod] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedId, setExpandedId] = useState(null);

  const observerRef = React.useRef(null);
  const loadMoreTriggerRef = React.useRef(null);

  const categories = [
    { label: 'All Categories', value: '' },
    { label: 'Bank Reconciliation', value: 'RECONCILIATION' },
    { label: 'Accruals & Reserves', value: 'ACCRUAL' },
    { label: 'Fixed Assets Depreciation', value: 'DEPRECIATION' },
  ];

  const statuses = [
    { label: 'All Statuses', value: '' },
    { label: 'Open (Unresolved)', value: 'OPEN' },
    { label: 'In Review (HITL Gate)', value: 'IN_REVIEW' },
    { label: 'Resolved & Posted', value: 'RESOLVED' },
  ];

  const loadInitialData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [res, summary] = await Promise.all([
        fetchExceptions({
          period: period.trim() || undefined,
          category: selectedCategory || undefined,
          status: selectedStatus || undefined,
          limit: PAGE_SIZE,
          offset: 0,
        }),
        fetchExceptionsSummary({
          period: period.trim() || undefined,
          category: selectedCategory || undefined,
          status: selectedStatus || undefined,
        }).catch(() => null),
      ]);

      const normalized = normalizeExceptionsList(res);
      setExceptions(normalized);
      setHasMore(normalized.length === PAGE_SIZE);

      if (summary) {
        setSummaryMetrics(summary);
      } else {
        setSummaryMetrics((prev) => ({
          ...prev,
          total_count: res.totalCount ?? normalized.length,
        }));
      }
    } catch (err) {
      setError(sanitizeErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const loadMoreExceptions = async () => {
    if (loading || loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await fetchExceptions({
        period: period.trim() || undefined,
        category: selectedCategory || undefined,
        status: selectedStatus || undefined,
        limit: PAGE_SIZE,
        offset: exceptions.length,
      });

      const nextBatch = normalizeExceptionsList(res);
      if (nextBatch.length === 0) {
        setHasMore(false);
      } else {
        setExceptions((prev) => {
          const existingIds = new Set(prev.map((item) => item.id));
          const uniqueNew = nextBatch.filter((item) => !existingIds.has(item.id));
          return [...prev, ...uniqueNew];
        });
        setHasMore(nextBatch.length === PAGE_SIZE);
      }
    } catch (err) {
      console.error('Failed to load more exceptions:', err);
    } finally {
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, [selectedCategory, selectedStatus, period]);

  // Infinite Scroll IntersectionObserver
  useEffect(() => {
    if (loading) return;

    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          loadMoreExceptions();
        }
      },
      { threshold: 0.1, rootMargin: '100px' }
    );

    if (loadMoreTriggerRef.current) {
      observerRef.current.observe(loadMoreTriggerRef.current);
    }

    return () => {
      if (observerRef.current) observerRef.current.disconnect();
    };
  }, [hasMore, loadingMore, loading, exceptions.length, selectedCategory, selectedStatus, period]);

  // Tab & Search Filtering
  const filteredExceptions = useMemo(() => {
    return exceptions.filter((exc) => {
      if (!exc) return false;

      // Quick Tab Filter
      if (activeTab === 'FEES' && !exc.financeContext.type.toLowerCase().includes('fee') && !exc.financeContext.type.toLowerCase().includes('charge')) {
        return false;
      }
      if (activeTab === 'EFT' && !exc.financeContext.type.toLowerCase().includes('wire') && !exc.financeContext.type.toLowerCase().includes('eft')) {
        return false;
      }
      if (activeTab === 'GL' && !exc.financeContext.type.toLowerCase().includes('gl')) {
        return false;
      }

      if (!searchTerm) return true;
      const term = searchTerm.toLowerCase();
      const accountCode = (exc.account_code || '').toLowerCase();
      const desc = (exc.description || '').toLowerCase();
      const cat = (exc.category || '').toLowerCase();
      const id = (exc.id || '').toLowerCase();
      const title = (exc.financeContext.title || '').toLowerCase();
      const type = (exc.financeContext.type || '').toLowerCase();
      return (
        accountCode.includes(term) ||
        desc.includes(term) ||
        cat.includes(term) ||
        id.includes(term) ||
        title.includes(term) ||
        type.includes(term)
      );
    });
  }, [exceptions, activeTab, searchTerm]);

  const getSeverityBadge = (severity) => {
    const sev = (severity || 'MEDIUM').toUpperCase();
    if (sev === 'HIGH' || sev === 'CRITICAL') {
      return <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><ShieldAlert size={12} /> High Severity</span>;
    }
    if (sev === 'MEDIUM') {
      return <span className="badge badge-warning">Medium Severity</span>;
    }
    return <span className="badge badge-info">Low Severity</span>;
  };

  const getStatusBadge = (status) => {
    const st = (status || 'OPEN').toUpperCase();
    if (st === 'RESOLVED') {
      return <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><CheckCircle2 size={12} /> Resolved</span>;
    }
    if (st === 'IN_REVIEW') {
      return <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><Clock size={12} /> In Review</span>;
    }
    return <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><AlertTriangle size={12} /> Open Break</span>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Page Title */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Financial Exceptions & Reconciliation Breaks</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Auditable inventory of General Ledger and Bank discrepancies, unposted service fees, and timing differences.
          </p>
        </div>
        <button
          className="button button-outline"
          onClick={loadInitialData}
          disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
          <span>Refresh Feed</span>
        </button>
      </div>

      {/* Financial Overview KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        <div className="card" style={{ padding: '1.25rem', background: 'var(--bg-secondary)', borderLeft: '4px solid var(--primary)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Total Breaks</span>
            <Layers size={18} color="var(--primary)" />
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.4rem', color: 'var(--text-primary)' }}>
            {summaryMetrics.total_count || exceptions.length}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            {summaryMetrics.open_count} Open / Pending Close Resolution
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem', background: 'var(--bg-secondary)', borderLeft: '4px solid var(--accent-rose)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Gross Variance Volume</span>
            <DollarSign size={18} color="var(--accent-rose)" />
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.4rem', color: 'var(--accent-rose)' }}>
            ${(summaryMetrics.gross_variance_volume || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            Across all unreconciled GL & bank items
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem', background: 'var(--bg-secondary)', borderLeft: '4px solid var(--accent-amber)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>High Severity Breaks</span>
            <ShieldAlert size={18} color="var(--accent-amber)" />
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.4rem', color: 'var(--accent-amber)' }}>
            {summaryMetrics.high_severity_count || 0}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            Variances exceeding $1,000 threshold
          </div>
        </div>

        <div className="card" style={{ padding: '1.25rem', background: 'var(--bg-secondary)', borderLeft: '4px solid var(--accent-purple)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Unposted Bank Fees</span>
            <Receipt size={18} color="var(--accent-purple)" />
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 800, marginTop: '0.4rem', color: 'var(--text-primary)' }}>
            ${(summaryMetrics.unposted_bank_fees || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            Tariffs & fees requiring ledger adjustment
          </div>
        </div>
      </div>

      {/* Quick Category Tab Chips */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        {[
          { id: 'ALL', label: `All Exceptions (${summaryMetrics.total_count || exceptions.length})` },
          { id: 'FEES', label: '🏦 Bank Service Charges' },
          { id: 'EFT', label: '💸 Wires & Transfers' },
          { id: 'GL', label: '⏱️ GL Postings / Timing Items' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '0.45rem 0.9rem',
              borderRadius: '20px',
              border: '1px solid',
              borderColor: activeTab === tab.id ? 'var(--primary)' : 'var(--border-color)',
              background: activeTab === tab.id ? 'var(--primary)' : 'var(--bg-secondary)',
              color: activeTab === tab.id ? '#ffffff' : 'var(--text-secondary)',
              fontSize: '0.825rem',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search & Filter Toolbar */}
      <div className="card" style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'center', padding: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: '1 1 260px' }}>
          <Search size={16} color="var(--text-muted)" />
          <input
            type="text"
            placeholder="Search by reference (e.g. PB-ANN-FEE), account, or description..."
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
            placeholder="e.g. 2025-12"
            style={{
              width: '110px',
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

      {/* Feed List */}
      {loading && exceptions.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
          <RefreshCw size={32} className="spin" style={{ margin: '0 auto 1rem auto', color: 'var(--primary)' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading financial exceptions feed...</p>
        </div>
      ) : filteredExceptions.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3.5rem 1rem' }}>
          <CheckCircle2 size={48} color="var(--accent-emerald)" style={{ margin: '0 auto 1rem auto', opacity: 0.85 }} />
          <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '0.5rem' }}>No Exceptions Found</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto' }}>
            {searchTerm || selectedCategory || selectedStatus || activeTab !== 'ALL'
              ? 'No exceptions match your current search and filter criteria.'
              : 'All General Ledger and Bank accounts are balanced and reconciled for this close period.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          {filteredExceptions.map((exc) => {
            if (!exc) return null;
            const isExpanded = expandedId === exc.id;
            const lineage = exc.lineage || {};
            const ctx = exc.financeContext;
            const variance = exc.amount_variance !== null && exc.amount_variance !== undefined
              ? Math.abs(Number(exc.amount_variance))
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
                  background: 'var(--bg-secondary)',
                }}
                onClick={() => setExpandedId(isExpanded ? null : exc.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                  <div style={{ flex: 1 }}>
                    {/* Header line */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 700, fontSize: '1.025rem', color: 'var(--text-primary)' }}>
                        {ctx.title}
                      </span>
                      <span className="badge badge-neutral" style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                        {ctx.type}
                      </span>
                      {getSeverityBadge(exc.severity)}
                      {getStatusBadge(exc.status)}
                    </div>

                    {/* Accounting description */}
                    <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', margin: '0.35rem 0', lineHeight: 1.45 }}>
                      {exc.description || 'No description provided'}
                    </p>

                    {/* Financial summary bar */}
                    <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.6rem', fontSize: '0.8rem', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                      <span>
                        <strong style={{ color: 'var(--text-secondary)' }}>Account:</strong> {ctx.accountLabel}
                      </span>
                      <span>
                        <strong style={{ color: 'var(--text-secondary)' }}>Period:</strong> {exc.period || 'N/A'}
                      </span>
                      {variance !== null && (
                        <span>
                          <strong style={{ color: 'var(--text-secondary)' }}>Variance Amount:</strong>{' '}
                          <span style={{ color: 'var(--accent-rose)', fontWeight: 700 }}>
                            ${variance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                        </span>
                      )}
                      <span>
                        <strong style={{ color: 'var(--text-secondary)' }}>Exception ID:</strong> <code style={{ color: 'var(--text-muted)' }}>{exc.id ? exc.id.slice(0, 12) : 'N/A'}</code>
                      </span>
                    </div>
                  </div>

                  <button
                    className="button button-ghost"
                    style={{ padding: '0.3rem 0.6rem', color: 'var(--text-muted)' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedId(isExpanded ? null : exc.id);
                    }}
                    aria-label="Toggle details"
                  >
                    {isExpanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                  </button>
                </div>

                {/* Expanded Finance Analysis & Lineage Box */}
                {isExpanded && (
                  <div
                    style={{
                      marginTop: '1rem',
                      paddingTop: '1rem',
                      borderTop: '1px solid var(--border-color)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.85rem',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* Financial Context & Required Resolution */}
                    <div style={{ padding: '0.85rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                      <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--primary)', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        Financial Impact & Root Cause Analysis
                      </div>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', lineHeight: 1.45 }}>
                        {ctx.financialImpact}
                      </p>
                      <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-emerald)', marginBottom: '0.2rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        Recommended Accounting Action
                      </div>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)', fontWeight: 500, lineHeight: 1.45 }}>
                        {ctx.suggestedAction}
                      </p>
                    </div>

                    {/* Technical File Lineage */}
                    {lineage && (lineage.filename || lineage.sheet_name || lineage.source_system) && (
                      <div style={{ padding: '0.75rem', background: 'rgba(0,0,0,0.15)', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        <strong>Source File Audit Lineage:</strong>{' '}
                        {lineage.filename && <span>File: <code>{lineage.filename}</code></span>}
                        {lineage.sheet_name && <span> | Sheet: <code>{lineage.sheet_name}</code></span>}
                        {lineage.row_number && <span> | Row: <code>{lineage.row_number}</code></span>}
                        {lineage.source_system && <span> | System: <code>{lineage.source_system}</code></span>}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Infinite Scroll & Load More Footer */}
          <div ref={loadMoreTriggerRef} style={{ padding: '1rem 0', textAlign: 'center' }}>
            {loadingMore ? (
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.6rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                <RefreshCw size={18} className="spin" style={{ color: 'var(--primary)' }} />
                <span>Loading next 50 exceptions...</span>
              </div>
            ) : hasMore ? (
              <button
                className="button button-outline"
                onClick={loadMoreExceptions}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.6rem 1.4rem',
                  fontSize: '0.875rem',
                  borderRadius: '20px',
                }}
              >
                <span>Load More Breaks (+50)</span>
                <ChevronDown size={16} />
              </button>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.825rem', paddingTop: '0.5rem' }}>
                ✓ All {summaryMetrics.total_count || exceptions.length} financial exceptions loaded
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
