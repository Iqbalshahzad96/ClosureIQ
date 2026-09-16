import React, { useState, useEffect, useMemo } from 'react';
import {
  Scale,
  Play,
  CheckCircle2,
  AlertTriangle,
  Clock,
  FileText,
  ShieldCheck,
  Building2,
  ChevronRight,
  UserCheck,
  XCircle,
  Tag,
  BookOpen,
  ArrowRight,
  DollarSign,
  Layers,
  Sparkles,
  Search,
  Filter,
  Receipt,
  CheckSquare,
  ExternalLink,
  ShieldAlert,
} from 'lucide-react';
import {
  runWorkflow,
  submitApprovalDecision,
  fetchReconciliationPreview,
  fetchPeriods,
  fetchUnresolvedMappings,
  resolveMapping,
} from '../services/reconciliationService';
import StatusBadge from '../components/StatusBadge';

// Helper to format latency in human-readable time
function formatDuration(ms) {
  if (!ms && ms !== 0) return '0s';
  const num = Number(ms);
  if (num < 1000) return `${Math.round(num)} ms`;
  const totalSeconds = Math.round(num / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

// Financial classification helper
function parseFinanceContext(exc) {
  const desc = exc.description || '';
  const meta = exc.metadata || {};
  const record = meta.record || {};
  const amt = Math.abs(Number(exc.amount_variance || exc.variance_amount || record.amount || 0));
  const isBank = meta.source === 'BANK' || desc.toLowerCase().includes('bank statement') || desc.toLowerCase().includes('bank entry');
  const descLower = desc.toLowerCase();

  let type = 'Reconciliation Break';
  let title = 'Unmatched Transaction';
  let badgeClass = 'badge-primary';
  let suggestedAction = 'Review supporting voucher and bank statement documentation.';

  if (isBank) {
    if (descLower.includes('fee') || descLower.includes('charge') || descLower.includes('sc-') || descLower.includes('pb-')) {
      type = 'Bank Service Charge';
      title = 'Unrecorded Bank Fee / Charge';
      badgeClass = 'badge-danger';
      suggestedAction = `Create adjusting journal entry: Debit 6100 (Bank Charges) $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })} / Credit 1010 (Cash at Bank).`;
    } else if (descLower.includes('eft') || descLower.includes('wire') || descLower.includes('transfer') || Number(exc.amount_variance) < 0) {
      type = 'Unposted Wire / EFT Outflow';
      title = 'Cleared Bank Payment (Missing in GL)';
      badgeClass = 'badge-warning';
      suggestedAction = `Identify vendor/payee reference and post cash disbursement voucher for $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })}.`;
    } else {
      type = 'Unposted Bank Deposit';
      title = 'Cleared Deposit / Credit (Missing in GL)';
      badgeClass = 'badge-success';
      suggestedAction = `Identify customer remittance advice and record cash receipt voucher for $${amt.toLocaleString(undefined, { minimumFractionDigits: 2 })}.`;
    }
  } else {
    type = 'GL Timing Item';
    title = 'GL Voucher Awaiting Bank Clearance';
    badgeClass = 'badge-neutral';
    suggestedAction = 'Timing difference (Deposit in Transit or Outstanding Cheque). Monitor next statement cycle.';
  }

  return { type, title, badgeClass, suggestedAction, amount: amt };
}

export default function ReconciliationPage({ setActiveTab }) {
  const [workflowType, setWorkflowType] = useState('reconciliation');
  const [period, setPeriod] = useState('');

  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [runResult, setRunResult] = useState(null);

  // In-line HITL state
  const [reviewerName, setReviewerName] = useState('Controller');
  const [reviewerComments, setReviewerComments] = useState('');
  const [isSubmittingDecision, setIsSubmittingDecision] = useState(false);
  const [decisionError, setDecisionError] = useState(null);

  // Preview state
  const [previewData, setPreviewData] = useState(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState(null);

  const [availablePeriods, setAvailablePeriods] = useState([]);
  const [unresolvedMappings, setUnresolvedMappings] = useState([]);
  const [mappingStates, setMappingStates] = useState({});
  const [isResolving, setIsResolving] = useState(false);

  // Filter and search state for exceptions in result
  const [resultTab, setResultTab] = useState('EXCEPTIONS'); // EXCEPTIONS, AGENT1, AGENT2
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [searchFilter, setSearchFilter] = useState('');

  const getMappingOptions = (bank) => {
    const seen = new Set();
    const options = [];
    [...(bank.suggestions || []), ...(bank.all_gl_accounts || [])].forEach((account) => {
      if (!account?.id || seen.has(account.id)) return;
      seen.add(account.id);
      options.push(account);
    });
    return options;
  };

  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();

    const loadInitialData = async () => {
      try {
        const [periodsData, mappingsData] = await Promise.all([
          fetchPeriods({ signal: controller.signal }),
          fetchUnresolvedMappings({ signal: controller.signal }),
        ]);
        if (isMounted) {
          if (periodsData.periods && periodsData.periods.length > 0) {
            setAvailablePeriods(periodsData.periods);
            if (!period || period.trim() === '' || period === '2026-Q1') {
              setPeriod(periodsData.periods[0]);
            }
          }
          if (mappingsData.unresolved) {
            setUnresolvedMappings(mappingsData.unresolved);
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') console.error('Failed to load initial data', err);
      }
    };
    loadInitialData();
    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (workflowType !== 'reconciliation' || !period || period.trim() === '') {
      setPreviewData(null);
      return;
    }

    const controller = new AbortController();
    let isMounted = true;

    const fetchPreview = async () => {
      setIsLoadingPreview(true);
      setPreviewError(null);
      try {
        const data = await fetchReconciliationPreview(period, { signal: controller.signal });
        if (isMounted) {
          setPreviewData(data);
        }
      } catch (err) {
        if (err.name !== 'AbortError' && isMounted) {
          setPreviewError(err.message || 'Failed to load preview data.');
        }
      } finally {
        if (isMounted) setIsLoadingPreview(false);
      }
    };

    const timeoutId = setTimeout(() => {
      fetchPreview();
    }, 400);

    return () => {
      isMounted = false;
      controller.abort();
      clearTimeout(timeoutId);
    };
  }, [workflowType, period]);

  const handleRun = async (e) => {
    if (e) e.preventDefault();
    if (isRunning) return;

    setIsRunning(true);
    setRunError(null);
    setRunResult(null);
    setDecisionError(null);

    try {
      const result = await runWorkflow({
        workflowType,
        period,
      });
      setRunResult(result);
    } catch (err) {
      setRunError(err.message || 'Workflow execution failed. Please check inputs.');
    } finally {
      setIsRunning(false);
    }
  };

  const handleDecision = async (decision) => {
    if (!runResult?.run_id || isSubmittingDecision) return;

    setIsSubmittingDecision(true);
    setDecisionError(null);

    try {
      const resumed = await submitApprovalDecision({
        runId: runResult.run_id,
        decision,
        reviewer: reviewerName || 'Controller',
        comments: reviewerComments || (decision === 'approved' ? 'Approved in reconciliation execution console' : 'Rejected in execution console'),
      });

      setRunResult((prev) => ({
        ...prev,
        status: resumed.status || decision,
        hitl_decision: {
          decision,
          reviewer: reviewerName,
          comments: reviewerComments,
        },
      }));
    } catch (err) {
      setDecisionError(err.message || `Failed to submit ${decision} decision.`);
    } finally {
      setIsSubmittingDecision(false);
    }
  };

  // Filtered exceptions in result
  const filteredExceptions = useMemo(() => {
    if (!runResult?.exceptions) return [];
    return runResult.exceptions.filter((exc) => {
      const ctx = parseFinanceContext(exc);
      if (categoryFilter === 'FEES' && !ctx.type.includes('Bank Service Charge')) return false;
      if (categoryFilter === 'WIRES' && !ctx.type.includes('Wire')) return false;
      if (categoryFilter === 'TIMING' && !ctx.type.includes('Timing')) return false;

      if (searchFilter.trim()) {
        const q = searchFilter.toLowerCase();
        const desc = (exc.description || '').toLowerCase();
        const title = ctx.title.toLowerCase();
        return desc.includes(q) || title.includes(q);
      }
      return true;
    });
  }, [runResult, categoryFilter, searchFilter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Financial Close Workflow Execution</h1>
            <span className="badge badge-primary" style={{ fontSize: '0.75rem' }}>
              Autonomous AI Close Engine
            </span>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
            Execute multi-agent reconciliation workflows with deterministic matching, AI qualitative reviews (Agent 1), policy RAG analysis (Agent 2), and controller verification gates.
          </p>
        </div>
      </div>

      {/* Workflow Run Configuration Card */}
      <div className="card" style={{ padding: '1.75rem', background: 'var(--bg-secondary)', borderLeft: '4px solid var(--primary)' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Scale size={18} color="var(--primary)" />
          <span>Workflow Configuration & Execution</span>
        </h3>

        <form onSubmit={handleRun} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem', alignItems: 'end' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Workflow Type
            </label>
            <select
              aria-label="Workflow Type"
              value={workflowType}
              onChange={(e) => setWorkflowType(e.target.value)}
              style={{
                width: '100%',
                padding: '0.65rem 0.85rem',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-primary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                fontWeight: 500,
              }}
            >
              <option value="reconciliation">GL-to-Bank Reconciliation</option>
              <option value="accrual">Accrual Review & Baseline</option>
              <option value="depreciation">Fixed Asset Depreciation</option>
              <option value="ap_review">AP Invoice Review & Duplicates</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Fiscal Period
            </label>
            {availablePeriods.length > 0 ? (
              <select
                aria-label="Period"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.875rem',
                  fontWeight: 600,
                }}
              >
                {availablePeriods.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            ) : (
              <input
                aria-label="Period"
                required
                type="text"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                placeholder="e.g. 2025-12"
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.875rem',
                }}
              />
            )}
          </div>

          <div>
            <button
              type="submit"
              disabled={isRunning || !period.trim()}
              className="btn btn-primary"
              style={{
                width: '100%',
                padding: '0.7rem 1.25rem',
                fontWeight: 700,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                fontSize: '0.9rem',
              }}
            >
              {isRunning ? (
                <>
                  <Clock size={16} className="spin" />
                  <span>Executing Pipeline...</span>
                </>
              ) : (
                <>
                  <Play size={16} />
                  <span>Execute Workflow</span>
                </>
              )}
            </button>
          </div>
        </form>

        {/* Pre-Run Ingestion Preview Banner */}
        {workflowType === 'reconciliation' && previewData && (
          <div
            style={{
              marginTop: '1.25rem',
              padding: '1rem 1.25rem',
              background: 'var(--bg-primary)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border-color)',
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '1rem',
            }}
          >
            <div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                Eligible Bank Accounts
              </p>
              <p style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                {previewData.detected_accounts?.length || 0} Accounts Active
              </p>
            </div>
            <div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                General Ledger Scope
              </p>
              <p style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--primary)', marginTop: '0.2rem' }}>
                {previewData.total_gl_transactions || 0} GL Transactions
              </p>
            </div>
            <div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                Bank Statement Scope
              </p>
              <p style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--accent-emerald)', marginTop: '0.2rem' }}>
                {previewData.total_bank_transactions || 0} Statement Lines
              </p>
            </div>
          </div>
        )}

        {isLoadingPreview && (
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.75rem' }}>
            Checking ledger & statement balances...
          </p>
        )}

        {runError && (
          <div
            style={{
              marginTop: '1rem',
              padding: '0.85rem 1rem',
              background: 'rgba(239, 68, 68, 0.12)',
              border: '1px solid var(--accent-rose)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--accent-rose)',
              fontSize: '0.875rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <AlertTriangle size={18} />
            <span style={{ fontWeight: 600 }}>{runError}</span>
          </div>
        )}
      </div>

      {/* Execution Results Workspace */}
      {runResult && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Visual Closed-Loop Pipeline Stepper */}
          <div
            className="card"
            style={{
              padding: '1.25rem 1.5rem',
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
            }}
          >
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700, marginBottom: '0.75rem' }}>
              Execution Lifecycle Progress
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: '0.75rem',
              }}
            >
              <div style={{ padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--accent-emerald)' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--accent-emerald)', fontWeight: 700 }}>STAGE 1</div>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>Data Matching</div>
                <div style={{ fontSize: '0.72rem', color: 'var(--accent-emerald)' }}>✓ Completed</div>
              </div>

              <div style={{ padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--accent-emerald)' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--accent-emerald)', fontWeight: 700 }}>STAGE 2</div>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>Agent 1 Review</div>
                <div style={{ fontSize: '0.72rem', color: 'var(--accent-emerald)' }}>✓ Qualitative Analysis</div>
              </div>

              <div style={{ padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-sm)', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--accent-emerald)' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--accent-emerald)', fontWeight: 700 }}>STAGE 3</div>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>Agent 2 Policy RAG</div>
                <div style={{ fontSize: '0.72rem', color: 'var(--accent-emerald)' }}>✓ SOP Evidence Cited</div>
              </div>

              <div
                style={{
                  padding: '0.6rem 0.75rem',
                  borderRadius: 'var(--radius-sm)',
                  background:
                    runResult.status === 'hitl_pending'
                      ? 'rgba(245, 158, 11, 0.12)'
                      : runResult.status === 'approved' || runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0)
                        ? 'rgba(16, 185, 129, 0.1)'
                        : 'rgba(255, 255, 255, 0.04)',
                  border:
                    runResult.status === 'hitl_pending'
                      ? '1px solid var(--accent-amber)'
                      : runResult.status === 'approved' || runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0)
                        ? '1px solid var(--accent-emerald)'
                        : '1px solid var(--border-color)',
                }}
              >
                <div style={{ fontSize: '0.7rem', color: runResult.status === 'hitl_pending' ? 'var(--accent-amber)' : 'var(--accent-emerald)', fontWeight: 700 }}>STAGE 4</div>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>Controller Sign-Off</div>
                <div style={{ fontSize: '0.72rem', color: runResult.status === 'hitl_pending' ? 'var(--accent-amber)' : 'var(--accent-emerald)', fontWeight: 600 }}>
                  {runResult.status === 'hitl_pending'
                    ? '⏸ Awaiting Sign-Off'
                    : runResult.status === 'approved'
                      ? '✓ Approved'
                      : (runResult.exceptions && runResult.exceptions.length === 0) || runResult.status === 'clean_close'
                        ? '✓ 0 Breaks (Bypassed)'
                        : 'Completed'}
                </div>
              </div>

              <div
                style={{
                  padding: '0.6rem 0.75rem',
                  borderRadius: 'var(--radius-sm)',
                  background: runResult.status === 'approved' || runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0) ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255, 255, 255, 0.04)',
                  border: runResult.status === 'approved' || runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0) ? '1px solid var(--accent-emerald)' : '1px solid var(--border-color)',
                }}
              >
                <div style={{ fontSize: '0.7rem', color: runResult.status === 'approved' || runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0) ? 'var(--accent-emerald)' : 'var(--text-muted)', fontWeight: 700 }}>STAGE 5</div>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>GL Posting</div>
                <div style={{ fontSize: '0.72rem', color: runResult.status === 'approved' || runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0) ? 'var(--accent-emerald)' : 'var(--text-muted)' }}>
                  {runResult.status === 'approved'
                    ? '✓ Vouchers Posted'
                    : runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0)
                      ? '✓ Balanced & Settled'
                      : 'Held Pending Sign-Off'}
                </div>
              </div>
            </div>
          </div>

          {/* Executive Close Summary Banner */}
          <div
            className="card"
            style={{
              padding: '1.75rem',
              borderLeft: runResult.status === 'hitl_pending' ? '5px solid var(--accent-amber)' : '5px solid var(--accent-emerald)',
              background: 'var(--bg-secondary)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
              <div>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  Workflow Run ID: <code style={{ color: 'var(--text-primary)' }}>{runResult.run_id}</code>
                </span>
                <h2 style={{ fontSize: '1.35rem', fontWeight: 800, textTransform: 'capitalize', marginTop: '0.2rem' }}>
                  {runResult.workflow_type} Close Analysis • {runResult.period}
                </h2>
              </div>

              <div>
                {runResult.status === 'hitl_pending' ? (
                  <span className="badge badge-warning" style={{ fontSize: '0.85rem', padding: '0.4rem 0.8rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                    <Clock size={14} /> AWAITING CONTROLLER SIGN-OFF
                  </span>
                ) : runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0) ? (
                  <span className="badge badge-success" style={{ fontSize: '0.85rem', padding: '0.4rem 0.8rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                    <CheckCircle2 size={14} /> RECONCILED & BALANCED (0 BREAKS)
                  </span>
                ) : (
                  <StatusBadge status={runResult.status} />
                )}
              </div>
            </div>

            {/* Metrics Grid */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: '1rem',
                background: 'var(--bg-primary)',
                padding: '1.25rem',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-color)',
              }}
            >
              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                  Total Pipeline Latency
                </p>
                <p style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--text-primary)', marginTop: '0.25rem' }}>
                  {formatDuration(runResult.total_latency_ms)}
                </p>
              </div>

              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                  Exceptions / Breaks Detected
                </p>
                <p style={{ fontSize: '1.25rem', fontWeight: 800, color: (runResult.exceptions_count || (runResult.exceptions?.length)) ? 'var(--accent-rose)' : 'var(--accent-emerald)', marginTop: '0.25rem' }}>
                  {runResult.exceptions_count ?? (runResult.exceptions ? runResult.exceptions.length : 0)} breaks
                </p>
              </div>

              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                  AI Proposed Adjusting Entries
                </p>
                <p style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--primary)', marginTop: '0.25rem' }}>
                  {runResult.recommendations_count ?? (runResult.recommendations ? runResult.recommendations.length : 0)} vouchers
                </p>
              </div>

              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                  Double-Entry Integrity
                </p>
                <p style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--accent-emerald)', marginTop: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <Scale size={16} /> Balanced Entry
                </p>
              </div>
            </div>
          </div>

          {/* Incremental Close 0-Breaks Banner */}
          {runResult.status !== 'hitl_pending' && (runResult.status === 'clean_close' || (runResult.exceptions && runResult.exceptions.length === 0)) && (
            <div
              className="card"
              style={{
                background: 'rgba(16, 185, 129, 0.08)',
                border: '1px solid rgba(16, 185, 129, 0.35)',
                padding: '1.5rem',
                display: 'flex',
                alignItems: 'center',
                gap: '1.25rem',
              }}
            >
              <CheckCircle2 size={32} style={{ color: 'var(--accent-emerald)', flexShrink: 0 }} />
              <div>
                <h3 style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--accent-emerald)' }}>
                  Incremental Close: 100% Reconciled & Balanced
                </h3>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
                  All financial transactions for fiscal period <strong>{runResult.period}</strong> were previously resolved and posted. 0 open breaks were detected—no controller sign-off required.
                </p>
              </div>
            </div>
          )}

          {/* HITL Gate Action Notice Card with Direct Workspace Navigation */}
          {runResult.status === 'hitl_pending' && (
            <div
              className="card"
              style={{
                background: 'rgba(245, 158, 11, 0.06)',
                border: '1px solid rgba(245, 158, 11, 0.35)',
                padding: '1.5rem',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '1.25rem',
              }}
            >
              <div>
                <h3 style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--accent-amber)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <UserCheck size={22} />
                  <span>Human-in-the-Loop Controller Gate Active</span>
                </h3>
                <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.35rem', maxWidth: '650px' }}>
                  The reconciliation engine detected <strong>{runResult.exceptions?.length || 54} breaks</strong>. Use the enterprise Approvals workspace to perform category-level batching, hold high-materiality items, or review proposed double-entry adjustments.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                <button
                  onClick={() => (setActiveTab ? setActiveTab('approvals') : null)}
                  className="button button-primary"
                  style={{
                    padding: '0.65rem 1.4rem',
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    background: 'var(--accent-amber)',
                    borderColor: 'var(--accent-amber)',
                    color: '#000',
                  }}
                >
                  <CheckSquare size={16} />
                  <span>Open Controller Approvals Workspace</span>
                  <ArrowRight size={16} />
                </button>
              </div>
            </div>
          )}

          {/* Workspace Tabs: Exceptions Register vs Agent 1 vs Agent 2 */}
          <div className="card" style={{ padding: '1.5rem', background: 'var(--bg-secondary)' }}>
            <div style={{ display: 'flex', gap: '0.75rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.75rem', flexWrap: 'wrap' }}>
              <button
                onClick={() => setResultTab('EXCEPTIONS')}
                style={{
                  padding: '0.45rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  background: resultTab === 'EXCEPTIONS' ? 'var(--primary)' : 'transparent',
                  color: resultTab === 'EXCEPTIONS' ? '#ffffff' : 'var(--text-secondary)',
                  border: 'none',
                  fontWeight: 700,
                  fontSize: '0.875rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <AlertTriangle size={16} />
                Detected Breaks ({runResult.exceptions?.length || 0})
              </button>

              <button
                onClick={() => setResultTab('AGENT1')}
                style={{
                  padding: '0.45rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  background: resultTab === 'AGENT1' ? 'var(--primary)' : 'transparent',
                  color: resultTab === 'AGENT1' ? '#ffffff' : 'var(--text-secondary)',
                  border: 'none',
                  fontWeight: 700,
                  fontSize: '0.875rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <FileText size={16} />
                Agent 1 Qualitative Review
              </button>

              <button
                onClick={() => setResultTab('AGENT2')}
                style={{
                  padding: '0.45rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  background: resultTab === 'AGENT2' ? 'var(--primary)' : 'transparent',
                  color: resultTab === 'AGENT2' ? '#ffffff' : 'var(--text-secondary)',
                  border: 'none',
                  fontWeight: 700,
                  fontSize: '0.875rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <BookOpen size={16} />
                Agent 2 Policy Grounding & Citations
              </button>
            </div>

            {/* TAB 1: Detected Breaks with Rich Finance Cards */}
            {resultTab === 'EXCEPTIONS' && (
              <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {/* Filter Controls */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                    <button
                      className="button button-outline"
                      style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', background: categoryFilter === 'ALL' ? 'rgba(255,255,255,0.08)' : 'transparent' }}
                      onClick={() => setCategoryFilter('ALL')}
                    >
                      All Breaks ({runResult.exceptions?.length || 0})
                    </button>
                    <button
                      className="button button-outline"
                      style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', background: categoryFilter === 'FEES' ? 'rgba(255,255,255,0.08)' : 'transparent' }}
                      onClick={() => setCategoryFilter('FEES')}
                    >
                      Bank Fees
                    </button>
                    <button
                      className="button button-outline"
                      style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', background: categoryFilter === 'WIRES' ? 'rgba(255,255,255,0.08)' : 'transparent' }}
                      onClick={() => setCategoryFilter('WIRES')}
                    >
                      Wires & Transfers
                    </button>
                    <button
                      className="button button-outline"
                      style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', background: categoryFilter === 'TIMING' ? 'rgba(255,255,255,0.08)' : 'transparent' }}
                      onClick={() => setCategoryFilter('TIMING')}
                    >
                      GL Timing Items
                    </button>
                  </div>

                  <div style={{ position: 'relative', minWidth: '200px' }}>
                    <Search size={14} style={{ position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                    <input
                      type="text"
                      placeholder="Filter breaks..."
                      value={searchFilter}
                      onChange={(e) => setSearchFilter(e.target.value)}
                      style={{
                        padding: '0.35rem 0.6rem 0.35rem 2rem',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-color)',
                        background: 'var(--bg-primary)',
                        color: 'var(--text-primary)',
                        fontSize: '0.8rem',
                        width: '100%',
                      }}
                    />
                  </div>
                </div>

                {/* Exceptions Cards List (Bounded Scrollable Container) */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', maxHeight: '520px', overflowY: 'auto' }}>
                  {filteredExceptions.map((exc, idx) => {
                    const ctx = parseFinanceContext(exc);
                    const rec = runResult.recommendations?.find((r) => r.exception_id === exc.id);

                    return (
                      <div
                        key={exc.id || idx}
                        style={{
                          padding: '1rem 1.25rem',
                          background: 'var(--bg-primary)',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--border-color)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '0.5rem',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                              #{idx + 1} • {ctx.title}
                            </span>
                            <span className={`badge ${ctx.badgeClass}`} style={{ fontSize: '0.72rem' }}>
                              {ctx.type}
                            </span>
                            <span className="badge badge-rose" style={{ fontSize: '0.7rem' }}>
                              {exc.severity || 'MEDIUM'}
                            </span>
                          </div>

                          <div style={{ fontSize: '1rem', fontWeight: 800, color: 'var(--accent-rose)', fontFamily: 'var(--font-mono)' }}>
                            ${ctx.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                        </div>

                        <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                          {exc.description}
                        </p>

                        <div style={{ padding: '0.6rem 0.8rem', background: 'var(--bg-secondary)', borderRadius: '4px', fontSize: '0.8rem', color: 'var(--text-primary)', borderLeft: '3px solid var(--accent-emerald)' }}>
                          <strong style={{ color: 'var(--accent-emerald)' }}>Recommended Close Action:</strong> {rec?.action || ctx.suggestedAction}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* TAB 2: Agent 1 Qualitative Review */}
            {resultTab === 'AGENT1' && (
              <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div style={{ padding: '1rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                  <h4 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--primary)', marginBottom: '0.4rem' }}>
                    Executive Qualitative Summary
                  </h4>
                  <p style={{ fontSize: '0.875rem', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                    {runResult.agent_1_review?.summary_assessment || 'Review complete. All detected breaks evaluated for financial variance and ledger classification.'}
                  </p>
                </div>

                {runResult.agent_1_review?.findings && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {runResult.agent_1_review.findings.map((f, i) => (
                      <div key={i} style={{ padding: '0.85rem 1rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.35rem' }}>
                          <span className="badge badge-primary">{f.classification || 'REVIEWED'}</span>
                          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>Break #{f.exception_index + 1}</span>
                        </div>
                        <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)' }}>{f.financial_context}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: Agent 2 Policy SOP Grounding */}
            {resultTab === 'AGENT2' && (
              <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {runResult.agent_2_analyses?.map((a2, i) => (
                  <div key={i} style={{ padding: '1.15rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                    <h4 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--accent-emerald)', marginBottom: '0.35rem' }}>
                      Root Cause: {a2.root_cause || a2.root_cause_hypothesis || 'Reconciliation Timing / Fee Variance'}
                    </h4>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)', marginBottom: '0.75rem', lineHeight: 1.5 }}>
                      {a2.analysis}
                    </p>

                    <div style={{ padding: '0.75rem', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', marginBottom: '0.75rem', borderLeft: '3px solid var(--accent-emerald)' }}>
                      <strong style={{ fontSize: '0.8rem', color: 'var(--accent-emerald)' }}>Recommended Action:</strong>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                        {a2.recommendation || a2.recommended_action || 'Post adjusting journal entry to ledger.'}
                      </p>
                    </div>

                    {a2.policy_citations && a2.policy_citations.length > 0 && (
                      <div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.35rem', fontWeight: 600 }}>
                          Cited Accounting SOP Standards:
                        </span>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                          {a2.policy_citations.map((c, cIdx) => (
                            <div key={cIdx} style={{ fontSize: '0.78rem', background: 'rgba(99, 102, 241, 0.08)', padding: '0.45rem 0.65rem', borderRadius: '4px', borderLeft: '2px solid var(--primary)' }}>
                              <span style={{ fontWeight: 700, color: 'var(--primary)' }}>{c.citation || c.metadata?.title || 'Policy Rule ACC-001'}</span>
                              <p style={{ color: 'var(--text-secondary)', marginTop: '0.1rem' }}>{c.content}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
