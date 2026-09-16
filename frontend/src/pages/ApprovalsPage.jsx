import React, { useState, useEffect, useMemo } from 'react';
import {
  CheckSquare,
  Square,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Clock,
  ShieldCheck,
  FileText,
  UserCheck,
  AlertCircle,
  BookOpen,
  ArrowRight,
  DollarSign,
  Scale,
  ListOrdered,
  Receipt,
  Building2,
  ChevronDown,
  ChevronUp,
  Filter,
  Search,
  AlertTriangle,
  Layers,
  PauseCircle,
  Sparkles,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import { fetchPendingApprovals, submitApprovalDecision } from '../services/reconciliationService';

export default function ApprovalsPage() {
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submittingRunId, setSubmittingRunId] = useState(null);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [reviewerName, setReviewerName] = useState('Controller');
  const [commentsMap, setCommentsMap] = useState({});
  const [activeTabMap, setActiveTabMap] = useState({});
  const [selectedEntriesMap, setSelectedEntriesMap] = useState({});
  const [searchQueryMap, setSearchQueryMap] = useState({});
  const [categoryFilterMap, setCategoryFilterMap] = useState({});
  const [expandedMap, setExpandedMap] = useState({});

  const loadPendingApprovals = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPendingApprovals();
      const list = Array.isArray(data) ? data : [];
      setPendingApprovals(list);

      // Default expand the first item, collapse older ones
      setExpandedMap((prev) => {
        const next = { ...prev };
        list.forEach((appr, idx) => {
          if (next[appr.run_id] === undefined) {
            next[appr.run_id] = idx === 0; // first item open by default
          }
        });
        return next;
      });

      // Initialize all proposed entries as selected by default for each run
      setSelectedEntriesMap((prev) => {
        const next = { ...prev };
        list.forEach((appr) => {
          if (!next[appr.run_id]) {
            const allIds = new Set(
              (appr.proposed_journal_entries || []).map((e) => e.exception_id || e.entry_number)
            );
            next[appr.run_id] = allIds;
          }
        });
        return next;
      });
    } catch (err) {
      setError(err.message || 'Failed to load pending approvals');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPendingApprovals();
  }, []);

  const toggleExpand = (runId) => {
    setExpandedMap((prev) => ({
      ...prev,
      [runId]: !prev[runId],
    }));
  };

  const expandAll = () => {
    const next = {};
    pendingApprovals.forEach((appr) => {
      next[appr.run_id] = true;
    });
    setExpandedMap(next);
  };

  const collapseAll = () => {
    const next = {};
    pendingApprovals.forEach((appr) => {
      next[appr.run_id] = false;
    });
    setExpandedMap(next);
  };

  // Classify proposed entry
  const classifyEntry = (entry) => {
    const desc = (entry.description || '').toLowerCase();
    const isFee =
      desc.includes('fee') ||
      desc.includes('charge') ||
      desc.includes('sc-') ||
      desc.includes('pb-') ||
      desc.includes('tariff') ||
      desc.includes('comm');
    const isTiming = entry.action_type === 'TIMING_DIFFERENCE' || desc.includes('gl transaction');
    const isHighMateriality = Number(entry.amount || 0) >= 10000 || desc.includes('wire') || desc.includes('eft');

    return { isFee, isTiming, isHighMateriality };
  };

  const handleToggleEntry = (runId, entryId) => {
    setSelectedEntriesMap((prev) => {
      const current = new Set(prev[runId] || []);
      if (current.has(entryId)) {
        current.delete(entryId);
      } else {
        current.add(entryId);
      }
      return { ...prev, [runId]: current };
    });
  };

  const handleSelectAll = (runId, entries) => {
    const allIds = new Set(entries.map((e) => e.exception_id || e.entry_number));
    setSelectedEntriesMap((prev) => ({ ...prev, [runId]: allIds }));
  };

  const handleDeselectAll = (runId) => {
    setSelectedEntriesMap((prev) => ({ ...prev, [runId]: new Set() }));
  };

  const handleSelectCategory = (runId, entries, categoryType) => {
    setSelectedEntriesMap((prev) => {
      const current = new Set(prev[runId] || []);
      entries.forEach((e) => {
        const { isFee, isTiming, isHighMateriality } = classifyEntry(e);
        const eId = e.exception_id || e.entry_number;
        if (categoryType === 'FEES' && isFee) current.add(eId);
        if (categoryType === 'TIMING' && isTiming) current.add(eId);
        if (categoryType === 'IMMATERIAL' && Number(e.amount || 0) < 10000) current.add(eId);
        if (categoryType === 'HIGH_VALUE' && isHighMateriality) current.add(eId);
      });
      return { ...prev, [runId]: current };
    });
  };

  const handleHoldCategory = (runId, entries, categoryType) => {
    setSelectedEntriesMap((prev) => {
      const current = new Set(prev[runId] || []);
      entries.forEach((e) => {
        const { isFee, isTiming, isHighMateriality } = classifyEntry(e);
        const eId = e.exception_id || e.entry_number;
        if (categoryType === 'FEES' && isFee) current.delete(eId);
        if (categoryType === 'TIMING' && isTiming) current.delete(eId);
        if (categoryType === 'HIGH_VALUE' && isHighMateriality) current.delete(eId);
      });
      return { ...prev, [runId]: current };
    });
  };

  const handleDecision = async (runId, decision, allEntries) => {
    setSubmittingRunId(runId);
    setError(null);
    setSuccessMessage(null);
    try {
      const comments = commentsMap[runId] || '';
      const selectedSet = selectedEntriesMap[runId] || new Set();

      let approvedEntryIds = null;
      let heldEntryIds = null;

      if (decision === 'approved') {
        approvedEntryIds = Array.from(selectedSet);
        heldEntryIds = allEntries
          .map((e) => e.exception_id || e.entry_number)
          .filter((id) => !selectedSet.has(id));
      }

      const result = await submitApprovalDecision({
        runId,
        decision,
        reviewer: reviewerName || 'Controller',
        comments,
        approvedEntryIds,
        heldEntryIds,
      });

      const approvedCount = result.approved_count ?? approvedEntryIds?.length ?? allEntries.length;
      const heldCount = result.held_count ?? heldEntryIds?.length ?? 0;

      if (decision === 'approved') {
        if (heldCount > 0) {
          setSuccessMessage(
            `Selective Approval Successful: ${approvedCount} journal entries posted to GL. ${heldCount} entries held for review.`
          );
        } else {
          setSuccessMessage(`Full Approval Successful: All ${approvedCount} journal entries posted to General Ledger.`);
        }
      } else {
        setSuccessMessage(`Workflow ${runId.slice(0, 8)} rejected. Exceptions remain open for investigation.`);
      }

      // Remove from pending list
      setPendingApprovals((prev) => prev.filter((item) => item.run_id !== runId));

      // Clean up local state
      setCommentsMap((prev) => {
        const next = { ...prev };
        delete next[runId];
        return next;
      });
    } catch (err) {
      setError(err.message || `Failed to submit ${decision} decision`);
    } finally {
      setSubmittingRunId(null);
    }
  };

  const handleCommentChange = (runId, value) => {
    setCommentsMap((prev) => ({
      ...prev,
      [runId]: value,
    }));
  };

  const allExpanded = pendingApprovals.length > 0 && pendingApprovals.every((p) => expandedMap[p.run_id]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Human-in-the-Loop (HITL) Approvals</h1>
            <span className="badge badge-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.75rem' }}>
              <Layers size={13} /> Enterprise Batching Active
            </span>
            {pendingApprovals.length > 0 && (
              <span className="badge badge-warning" style={{ fontSize: '0.75rem', fontWeight: 700 }}>
                {pendingApprovals.length} Pending Review{pendingApprovals.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
            Controller verification & sign-off workspace. Expand review packages to perform category batching or hold material exceptions before posting to the General Ledger.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {pendingApprovals.length > 1 && (
            <button
              className="button button-outline"
              onClick={allExpanded ? collapseAll : expandAll}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.825rem' }}
            >
              {allExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              <span>{allExpanded ? 'Collapse All' : 'Expand All'}</span>
            </button>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>Reviewer:</span>
            <input
              type="text"
              value={reviewerName}
              onChange={(e) => setReviewerName(e.target.value)}
              placeholder="Your Name / Role"
              style={{
                padding: '0.4rem 0.6rem',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                fontSize: '0.85rem',
                width: '140px',
              }}
            />
          </div>

          <button
            className="button button-outline"
            onClick={loadPendingApprovals}
            disabled={loading}
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            <RefreshCw size={16} className={loading ? 'spin' : ''} />
            <span>Refresh Queue</span>
          </button>
        </div>
      </div>

      {/* Success Notification */}
      {successMessage && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(16, 185, 129, 0.12)', border: '1px solid var(--accent-emerald)', color: 'var(--accent-emerald)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <CheckCircle2 size={20} />
          <span style={{ fontWeight: 600 }}>{successMessage}</span>
        </div>
      )}

      {/* Error Notification */}
      {error && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid var(--accent-rose)', color: 'var(--accent-rose)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <AlertCircle size={20} />
          <span style={{ fontWeight: 600 }}>{error}</span>
        </div>
      )}

      {/* Pending List */}
      {loading && pendingApprovals.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3.5rem 1rem' }}>
          <RefreshCw size={36} className="spin" style={{ margin: '0 auto 1rem auto', color: 'var(--primary)' }} />
          <p style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>Loading pending approval queue...</p>
        </div>
      ) : pendingApprovals.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '4rem 1rem' }}>
          <CheckSquare size={52} color="var(--accent-emerald)" style={{ margin: '0 auto 1rem auto', opacity: 0.9 }} />
          <h3 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>No Pending Approvals</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '520px', margin: '0 auto', lineHeight: 1.5 }}>
            All financial close workflows are reconciled and posted. When a month-end close requires controller sign-off, it will pause safely at this verification gate.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {pendingApprovals.map((approval) => {
            const runId = approval.run_id;
            const isExpanded = !!expandedMap[runId];
            const exceptions = approval.exceptions || [];
            const recommendations = approval.recommendations || [];
            const proposedEntries = approval.proposed_journal_entries || [];
            const isSubmitting = submittingRunId === runId;
            const comments = commentsMap[runId] || '';
            const activeTab = activeTabMap[runId] || 'ENTRIES';
            const selectedSet = selectedEntriesMap[runId] || new Set();
            const searchQuery = searchQueryMap[runId] || '';
            const categoryFilter = categoryFilterMap[runId] || 'ALL';

            // Calculate category statistics
            let feeCount = 0;
            let feeAmount = 0;
            let timingCount = 0;
            let timingAmount = 0;
            let highValCount = 0;
            let highValAmount = 0;
            let totalVolume = 0;

            proposedEntries.forEach((e) => {
              const amt = Number(e.amount || 0);
              totalVolume += amt;
              const { isFee, isTiming, isHighMateriality } = classifyEntry(e);
              if (isFee) {
                feeCount += 1;
                feeAmount += amt;
              }
              if (isTiming) {
                timingCount += 1;
                timingAmount += amt;
              }
              if (isHighMateriality) {
                highValCount += 1;
                highValAmount += amt;
              }
            });

            // Calculate Approved vs Held financial volume
            let approvedVolume = 0;
            let approvedCount = 0;
            let heldVolume = 0;
            let heldCount = 0;

            proposedEntries.forEach((e) => {
              const eId = e.exception_id || e.entry_number;
              const amt = Number(e.amount || 0);
              if (selectedSet.has(eId)) {
                approvedCount += 1;
                approvedVolume += amt;
              } else {
                heldCount += 1;
                heldVolume += amt;
              }
            });

            // Filter entries for table
            const filteredEntries = proposedEntries.filter((e) => {
              const { isFee, isTiming, isHighMateriality } = classifyEntry(e);
              if (categoryFilter === 'FEES' && !isFee) return false;
              if (categoryFilter === 'TIMING' && !isTiming) return false;
              if (categoryFilter === 'HIGH_VAL' && !isHighMateriality) return false;
              if (categoryFilter === 'HELD' && selectedSet.has(e.exception_id || e.entry_number)) return false;
              if (categoryFilter === 'SELECTED' && !selectedSet.has(e.exception_id || e.entry_number)) return false;

              if (searchQuery.trim()) {
                const q = searchQuery.toLowerCase();
                const desc = (e.description || '').toLowerCase();
                const dr = (e.debit_account || '').toLowerCase();
                const cr = (e.credit_account || '').toLowerCase();
                const pol = (e.policy_citation || '').toLowerCase();
                return desc.includes(q) || dr.includes(q) || cr.includes(q) || pol.includes(q);
              }
              return true;
            });

            return (
              <div
                key={runId}
                className="card"
                style={{
                  padding: isExpanded ? '1.75rem' : '1.15rem 1.5rem',
                  borderLeft: '5px solid var(--accent-amber)',
                  background: 'var(--bg-secondary)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: isExpanded ? '1.5rem' : '0',
                  boxShadow: '0 6px 20px rgba(0, 0, 0, 0.22)',
                  transition: 'all 0.2s ease',
                }}
              >
                {/* Header bar of card (Clickable Accordion Trigger) */}
                <div
                  onClick={() => toggleExpand(runId)}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleExpand(runId);
                      }}
                      style={{
                        background: isExpanded ? 'var(--primary)' : 'rgba(255,255,255,0.06)',
                        border: '1px solid var(--border-color)',
                        color: isExpanded ? '#fff' : 'var(--text-secondary)',
                        borderRadius: 'var(--radius-sm)',
                        padding: '0.35rem 0.5rem',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                      }}
                    >
                      {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      <span>{isExpanded ? 'Collapse' : 'Expand Package'}</span>
                    </button>

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 800, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                          Reconciliation Review Package • {approval.period || '2025-12'}
                        </span>
                        <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontWeight: 700 }}>
                          <Clock size={12} /> AWAITING SIGN-OFF
                        </span>
                        <span className="badge badge-neutral" style={{ textTransform: 'uppercase' }}>
                          {approval.workflow_type || 'Reconciliation'}
                        </span>
                      </div>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                        Workflow Run ID: <code style={{ color: 'var(--text-secondary)' }}>{runId}</code> | Fiscal Period: <strong style={{ color: 'var(--text-primary)' }}>{approval.period}</strong>
                      </p>
                    </div>
                  </div>

                  {/* Compact Stats Badges in Header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--accent-rose)' }}>
                        ${totalVolume.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {proposedEntries.length} adjusting vouchers
                      </div>
                    </div>

                    <div style={{ textAlign: 'right', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {approval.created_at ? new Date(approval.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recent'}
                    </div>
                  </div>
                </div>

                {/* EXPANDED CONTENT */}
                {isExpanded && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', marginTop: '0.5rem' }}>
                    {/* 3-Tier Enterprise Management by Exception Breakdown Banner */}
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                        gap: '1rem',
                      }}
                    >
                      {/* Tier 1: Routine Bank Fees Card */}
                      <div
                        style={{
                          padding: '1rem 1.15rem',
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-primary)',
                          border: '1px solid var(--border-color)',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          gap: '0.75rem',
                        }}
                      >
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                              Tier 1: Routine Bank Fees
                            </span>
                            <span className="badge badge-neutral" style={{ fontSize: '0.7rem' }}>Low Risk</span>
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '0.3rem' }}>
                            {feeCount} items • ${feeAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                            Standard service charges and tariffs matching policy ACC-001.
                          </p>
                        </div>

                        <div style={{ display: 'flex', gap: '0.4rem' }}>
                          <button
                            className="button button-outline"
                            style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem', flex: 1, borderColor: 'var(--accent-emerald)', color: 'var(--accent-emerald)' }}
                            onClick={() => handleSelectCategory(runId, proposedEntries, 'FEES')}
                          >
                            ✓ Select All Fees ({feeCount})
                          </button>
                        </div>
                      </div>

                      {/* Tier 1: GL Timing Differences Card */}
                      <div
                        style={{
                          padding: '1rem 1.15rem',
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-primary)',
                          border: '1px solid var(--border-color)',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          gap: '0.75rem',
                        }}
                      >
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                              Tier 1: Timing Differences
                            </span>
                            <span className="badge badge-neutral" style={{ fontSize: '0.7rem' }}>Ledger Timing</span>
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: '0.3rem' }}>
                            {timingCount} items • ${timingAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                            Transactions in flight across period boundary (no GL adjustment).
                          </p>
                        </div>

                        <div style={{ display: 'flex', gap: '0.4rem' }}>
                          <button
                            className="button button-outline"
                            style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem', flex: 1, borderColor: 'var(--primary)', color: 'var(--primary)' }}
                            onClick={() => handleSelectCategory(runId, proposedEntries, 'TIMING')}
                          >
                            ✓ Select All Timing ({timingCount})
                          </button>
                        </div>
                      </div>

                      {/* Tier 2: High-Materiality Breaks Card */}
                      <div
                        style={{
                          padding: '1rem 1.15rem',
                          borderRadius: 'var(--radius-sm)',
                          background: 'rgba(239, 68, 68, 0.04)',
                          border: '1px solid rgba(239, 68, 68, 0.35)',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between',
                          gap: '0.75rem',
                        }}
                      >
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.75rem', color: 'var(--accent-rose)', textTransform: 'uppercase', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <AlertTriangle size={13} /> Tier 2: High Materiality (&gt; $10k)
                            </span>
                            <span className="badge badge-danger" style={{ fontSize: '0.7rem' }}>Requires Scrutiny</span>
                          </div>
                          <div style={{ fontSize: '1.25rem', fontWeight: 800, color: 'var(--accent-rose)', marginTop: '0.3rem' }}>
                            {highValCount} items • ${highValAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                            Large EFT/wire outflows and high-risk variances.
                          </p>
                        </div>

                        <div style={{ display: 'flex', gap: '0.4rem' }}>
                          <button
                            className="button button-outline"
                            style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem', flex: 1, borderColor: 'var(--accent-amber)', color: 'var(--accent-amber)' }}
                            onClick={() => handleHoldCategory(runId, proposedEntries, 'HIGH_VALUE')}
                          >
                            ⏸ Hold Material Items ({highValCount})
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Quick Batch Actions Toolbar & Filters */}
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: '0.75rem',
                        padding: '0.75rem 1rem',
                        background: 'var(--bg-primary)',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-color)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)' }}>
                          Batch Controls:
                        </span>
                        <button
                          className="button button-outline"
                          style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }}
                          onClick={() => handleSelectAll(runId, proposedEntries)}
                        >
                          Select All ({proposedEntries.length})
                        </button>
                        <button
                          className="button button-outline"
                          style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }}
                          onClick={() => handleDeselectAll(runId)}
                        >
                          Deselect All
                        </button>
                        <button
                          className="button button-outline"
                          style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem', borderColor: 'var(--accent-emerald)', color: 'var(--accent-emerald)' }}
                          onClick={() => handleSelectCategory(runId, proposedEntries, 'IMMATERIAL')}
                        >
                          Select Immaterial Only (&lt; $10k)
                        </button>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                        {/* Search filter */}
                        <div style={{ position: 'relative', minWidth: '180px' }}>
                          <Search size={14} style={{ position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                          <input
                            type="text"
                            placeholder="Search entries..."
                            value={searchQuery}
                            onChange={(e) => setSearchQueryMap((prev) => ({ ...prev, [runId]: e.target.value }))}
                            style={{
                              padding: '0.35rem 0.6rem 0.35rem 2rem',
                              borderRadius: 'var(--radius-sm)',
                              border: '1px solid var(--border-color)',
                              background: 'var(--bg-secondary)',
                              color: 'var(--text-primary)',
                              fontSize: '0.8rem',
                              width: '100%',
                            }}
                          />
                        </div>

                        {/* Category Filter Select */}
                        <select
                          value={categoryFilter}
                          onChange={(e) => setCategoryFilterMap((prev) => ({ ...prev, [runId]: e.target.value }))}
                          style={{
                            padding: '0.35rem 0.6rem',
                            borderRadius: 'var(--radius-sm)',
                            border: '1px solid var(--border-color)',
                            background: 'var(--bg-secondary)',
                            color: 'var(--text-primary)',
                            fontSize: '0.8rem',
                          }}
                        >
                          <option value="ALL">Show All ({proposedEntries.length})</option>
                          <option value="FEES">Bank Fees ({feeCount})</option>
                          <option value="TIMING">Timing Items ({timingCount})</option>
                          <option value="HIGH_VAL">High Materiality ({highValCount})</option>
                          <option value="SELECTED">Selected to Post ({approvedCount})</option>
                          <option value="HELD">Held for Review ({heldCount})</option>
                        </select>
                      </div>
                    </div>

                    {/* Navigation Tabs (Proposed Entries vs Policy Context) */}
                    <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
                      <button
                        onClick={() => setActiveTabMap((prev) => ({ ...prev, [runId]: 'ENTRIES' }))}
                        style={{
                          padding: '0.4rem 0.8rem',
                          borderRadius: 'var(--radius-sm)',
                          background: activeTab === 'ENTRIES' ? 'var(--primary)' : 'transparent',
                          color: activeTab === 'ENTRIES' ? '#ffffff' : 'var(--text-secondary)',
                          border: 'none',
                          fontWeight: 600,
                          fontSize: '0.85rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.4rem',
                        }}
                      >
                        <ListOrdered size={15} />
                        Proposed Adjusting Journal Entries ({filteredEntries.length} shown)
                      </button>

                      <button
                        onClick={() => setActiveTabMap((prev) => ({ ...prev, [runId]: 'EXCEPTIONS' }))}
                        style={{
                          padding: '0.4rem 0.8rem',
                          borderRadius: 'var(--radius-sm)',
                          background: activeTab === 'EXCEPTIONS' ? 'var(--primary)' : 'transparent',
                          color: activeTab === 'EXCEPTIONS' ? '#ffffff' : 'var(--text-secondary)',
                          border: 'none',
                          fontWeight: 600,
                          fontSize: '0.85rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.4rem',
                        }}
                      >
                        <AlertCircle size={15} />
                        Break Details & AI Policy Citations ({exceptions.length})
                      </button>
                    </div>

                    {/* Tab 1: Proposed Journal Entries Table with Selection Checkboxes */}
                    {activeTab === 'ENTRIES' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        <div style={{ overflowX: 'auto', maxHeight: '420px' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                            <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                              <tr style={{ background: 'var(--bg-primary)', textAlign: 'left', borderBottom: '2px solid var(--border-color)' }}>
                                <th style={{ padding: '0.6rem 0.8rem', width: '40px', textAlign: 'center' }}>
                                  <input
                                    type="checkbox"
                                    checked={filteredEntries.length > 0 && filteredEntries.every((e) => selectedSet.has(e.exception_id || e.entry_number))}
                                    onChange={(e) => {
                                      if (e.target.checked) {
                                        setSelectedEntriesMap((prev) => {
                                          const next = new Set(prev[runId] || []);
                                          filteredEntries.forEach((entry) => next.add(entry.exception_id || entry.entry_number));
                                          return { ...prev, [runId]: next };
                                        });
                                      } else {
                                        setSelectedEntriesMap((prev) => {
                                          const next = new Set(prev[runId] || []);
                                          filteredEntries.forEach((entry) => next.delete(entry.exception_id || entry.entry_number));
                                          return { ...prev, [runId]: next };
                                        });
                                      }
                                    }}
                                    style={{ cursor: 'pointer' }}
                                  />
                                </th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)' }}>#</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)' }}>Status / Action</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)' }}>Description</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)' }}>Debit Account</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)' }}>Credit Account</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)', textAlign: 'right' }}>Amount</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)' }}>Policy Citation</th>
                                <th style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>Action</th>
                              </tr>
                            </thead>
                            <tbody>
                              {filteredEntries.map((entry, idx) => {
                                const eId = entry.exception_id || entry.entry_number;
                                const isSelected = selectedSet.has(eId);
                                const amt = Number(entry.amount || 0);
                                const isHighMateriality = amt >= 10000;

                                return (
                                  <tr
                                    key={idx}
                                    style={{
                                      borderBottom: '1px solid var(--border-color)',
                                      background: isSelected
                                        ? idx % 2 === 0
                                          ? 'rgba(16, 185, 129, 0.03)'
                                          : 'rgba(16, 185, 129, 0.06)'
                                        : 'rgba(239, 68, 68, 0.04)',
                                      opacity: isSelected ? 1 : 0.75,
                                      transition: 'background 0.15s ease',
                                    }}
                                  >
                                    <td style={{ padding: '0.6rem 0.8rem', textAlign: 'center' }}>
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => handleToggleEntry(runId, eId)}
                                        style={{ cursor: 'pointer', transform: 'scale(1.1)' }}
                                      />
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', fontWeight: 600 }}>{entry.entry_number}</td>
                                    <td style={{ padding: '0.6rem 0.8rem' }}>
                                      {isSelected ? (
                                        <span className="badge badge-success" style={{ fontSize: '0.72rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                                          <CheckCircle2 size={11} /> Ready to Post
                                        </span>
                                      ) : (
                                        <span className="badge badge-danger" style={{ fontSize: '0.72rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                                          <PauseCircle size={11} /> Held for Review
                                        </span>
                                      )}
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', color: 'var(--text-primary)', maxWidth: '280px' }}>
                                      <div style={{ fontWeight: isHighMateriality ? 700 : 500 }}>{entry.description}</div>
                                      {isHighMateriality && (
                                        <span style={{ fontSize: '0.7rem', color: 'var(--accent-rose)', fontWeight: 700 }}>
                                          ⚠️ High Materiality
                                        </span>
                                      )}
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', color: 'var(--text-secondary)' }}>
                                      {entry.debit_account}
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', color: 'var(--text-secondary)' }}>
                                      {entry.credit_account}
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', textAlign: 'right', fontWeight: 700, color: isHighMateriality ? 'var(--accent-rose)' : 'var(--text-primary)' }}>
                                      ${amt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                                        <BookOpen size={12} color="var(--primary)" /> {entry.policy_citation}
                                      </span>
                                    </td>
                                    <td style={{ padding: '0.6rem 0.8rem', textAlign: 'center' }}>
                                      <button
                                        onClick={() => handleToggleEntry(runId, eId)}
                                        style={{
                                          padding: '0.25rem 0.5rem',
                                          fontSize: '0.72rem',
                                          borderRadius: 'var(--radius-sm)',
                                          border: isSelected ? '1px solid var(--accent-amber)' : '1px solid var(--accent-emerald)',
                                          background: 'transparent',
                                          color: isSelected ? 'var(--accent-amber)' : 'var(--accent-emerald)',
                                          cursor: 'pointer',
                                          fontWeight: 600,
                                        }}
                                      >
                                        {isSelected ? 'Hold' : 'Include'}
                                      </button>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}

                    {/* Tab 2: Exceptions Breakdown & AI Policy Evidence */}
                    {activeTab === 'EXCEPTIONS' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', maxHeight: '420px', overflowY: 'auto' }}>
                        {exceptions.map((exc, idx) => {
                          const rec = recommendations.find((r) => r.exception_id === exc.id);
                          return (
                            <div
                              key={idx}
                              style={{
                                padding: '0.85rem 1rem',
                                background: 'var(--bg-primary)',
                                borderRadius: 'var(--radius-sm)',
                                border: '1px solid var(--border-color)',
                                fontSize: '0.85rem',
                              }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.35rem' }}>
                                <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                                  Break #{idx + 1}: {exc.description || 'Unmatched Transaction'}
                                </span>
                                <span style={{ fontWeight: 700, color: 'var(--accent-rose)' }}>
                                  ${Math.abs(Number(exc.amount_variance || 0)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                </span>
                              </div>
                              {rec && (
                                <div style={{ marginTop: '0.4rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                  <strong style={{ color: 'var(--accent-emerald)' }}>AI Recommendation:</strong> {rec.action}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Dynamic Financial Impact & Controller Decision Sign-Off Bar */}
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                        padding: '1.25rem',
                        background: 'var(--bg-primary)',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-color)',
                      }}
                    >
                      {/* Live Impact Counter */}
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          flexWrap: 'wrap',
                          gap: '1rem',
                          paddingBottom: '0.85rem',
                          borderBottom: '1px solid var(--border-color)',
                        }}
                      >
                        <div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                            Approved to Post to General Ledger
                          </div>
                          <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--accent-emerald)', marginTop: '0.2rem' }}>
                            {approvedCount} entries • ${approvedVolume.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                        </div>

                        <div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                            Held for Further Accounting Review
                          </div>
                          <div style={{ fontSize: '1.2rem', fontWeight: 800, color: heldCount > 0 ? 'var(--accent-amber)' : 'var(--text-muted)', marginTop: '0.2rem' }}>
                            {heldCount} entries • ${heldVolume.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                        </div>

                        <div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                            Double-Entry Integrity
                          </div>
                          <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--accent-emerald)', marginTop: '0.2rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                            <Scale size={15} /> Balanced Postings
                          </div>
                        </div>
                      </div>

                      {/* Controller Audit Notes */}
                      <div>
                        <label style={{ fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.35rem' }}>
                          Controller Sign-Off Audit Notes & Justification:
                        </label>
                        <textarea
                          rows={2}
                          value={comments}
                          onChange={(e) => handleCommentChange(runId, e.target.value)}
                          placeholder={
                            heldCount > 0
                              ? `e.g. Approved ${approvedCount} routine adjustments. Held ${heldCount} material items pending vendor documentation.`
                              : 'e.g. Reviewed and verified bank reconciliation adjustments for period 2025-12.'
                          }
                          style={{
                            width: '100%',
                            padding: '0.6rem 0.75rem',
                            borderRadius: 'var(--radius-sm)',
                            border: '1px solid var(--border-color)',
                            background: 'var(--bg-secondary)',
                            color: 'var(--text-primary)',
                            fontSize: '0.85rem',
                            resize: 'vertical',
                            fontFamily: 'inherit',
                          }}
                        />
                      </div>

                      {/* Decision Buttons */}
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <button
                          className="button button-danger-outline"
                          onClick={() => handleDecision(runId, 'rejected', proposedEntries)}
                          disabled={isSubmitting}
                          style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.55rem 1.15rem' }}
                        >
                          <XCircle size={16} />
                          <span>Reject Entire Package</span>
                        </button>

                        <button
                          className="button button-primary"
                          onClick={() => handleDecision(runId, 'approved', proposedEntries)}
                          disabled={isSubmitting || approvedCount === 0}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            padding: '0.55rem 1.4rem',
                            fontWeight: 700,
                            background: 'var(--accent-emerald)',
                            borderColor: 'var(--accent-emerald)',
                          }}
                        >
                          <CheckCircle2 size={16} />
                          <span>
                            {isSubmitting
                              ? 'Posting to General Ledger...'
                              : `Approve & Post Selected (${approvedCount}) Entries`}
                          </span>
                        </button>
                      </div>
                    </div>
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
