import React, { useState, useEffect } from 'react';
import {
  CheckSquare,
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
} from 'lucide-react';
import { fetchPendingApprovals, submitApprovalDecision } from '../services/reconciliationService';

export default function ApprovalsPage() {
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [loading, setLoading] = useState(false);
  const [submittingRunId, setSubmittingRunId] = useState(null);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [reviewerName, setReviewerName] = useState('Accountant');
  const [commentsMap, setCommentsMap] = useState({});

  const loadPendingApprovals = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPendingApprovals();
      setPendingApprovals(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load pending approvals');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPendingApprovals();
  }, []);

  const handleDecision = async (runId, decision) => {
    setSubmittingRunId(runId);
    setError(null);
    setSuccessMessage(null);
    try {
      const comments = commentsMap[runId] || '';
      const result = await submitApprovalDecision({
        runId,
        decision,
        reviewer: reviewerName || 'Accountant',
        comments,
      });

      setSuccessMessage(
        `Workflow ${runId.slice(0, 8)} successfully ${decision.toUpperCase()}. Status is now ${result.status || 'COMPLETED'}.`
      );

      // Remove the approved/rejected item from pending list
      setPendingApprovals((prev) => prev.filter((item) => item.run_id !== runId));
      
      // Clean up comment for this run
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Human-in-the-Loop (HITL) Approvals</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Mandatory human verification gate. Review AI-recommended journal adjustments and policy citations before final ledger posting.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
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
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--accent-emerald)', color: 'var(--accent-emerald)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <CheckCircle2 size={18} />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Error Notification */}
      {error && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--accent-rose)', color: 'var(--accent-rose)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Pending List */}
      {loading && pendingApprovals.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3rem 1rem' }}>
          <RefreshCw size={32} className="spin" style={{ margin: '0 auto 1rem auto', color: 'var(--primary)' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading pending approval queue...</p>
        </div>
      ) : pendingApprovals.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '3.5rem 1rem' }}>
          <CheckSquare size={48} color="var(--accent-emerald)" style={{ margin: '0 auto 1rem auto', opacity: 0.85 }} />
          <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '0.5rem' }}>No Pending Approvals</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto' }}>
            All financial workflows are up to date. When a close workflow requires human approval, it will pause safely at this gate.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {pendingApprovals.map((approval) => {
            const runId = approval.run_id;
            const findings = approval.findings || {};
            const exceptions = approval.exceptions || [];
            const isSubmitting = submittingRunId === runId;
            const comments = commentsMap[runId] || '';

            return (
              <div
                key={runId}
                className="card"
                style={{
                  padding: '1.5rem',
                  borderLeft: '4px solid var(--accent-amber)',
                  background: 'var(--bg-secondary)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '1rem',
                }}
              >
                {/* Header bar of card */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--text-primary)' }}>
                        Workflow: {approval.workflow_type || 'Reconciliation'}
                      </span>
                      <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                        <Clock size={12} /> PENDING APPROVAL
                      </span>
                      <span className="badge badge-neutral">Period: {approval.period || '2026-Q1'}</span>
                    </div>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                      Run ID: <code style={{ color: 'var(--text-secondary)' }}>{runId}</code>
                    </p>
                  </div>

                  <div style={{ textAlign: 'right', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {approval.created_at ? new Date(approval.created_at).toLocaleString() : 'Recent'}
                  </div>
                </div>

                {/* Findings summary / Agent 2 recommendation */}
                <div
                  style={{
                    padding: '1rem',
                    background: 'var(--bg-primary)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-color)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                    <ShieldCheck size={16} color="var(--primary)" />
                    <strong style={{ fontSize: '0.875rem' }}>Agent 2 Proposed Action & Analysis:</strong>
                  </div>

                  <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    {approval.recommendation || findings.summary || 'Review of exceptions and suggested journal entries required.'}
                  </p>

                  {findings.proposed_adjustments && (
                    <div style={{ marginTop: '0.75rem', fontSize: '0.825rem' }}>
                      <strong style={{ color: 'var(--text-primary)' }}>Proposed Journal Entry:</strong>
                      <pre
                        style={{
                          marginTop: '0.25rem',
                          padding: '0.5rem',
                          background: 'var(--bg-secondary)',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '0.75rem',
                          overflowX: 'auto',
                        }}
                      >
                        {typeof findings.proposed_adjustments === 'string'
                          ? findings.proposed_adjustments
                          : JSON.stringify(findings.proposed_adjustments, null, 2)}
                      </pre>
                    </div>
                  )}

                  {findings.citations && findings.citations.length > 0 && (
                    <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <BookOpen size={14} color="var(--primary)" />
                      <span style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>Policy Citations:</span>
                      {findings.citations.map((c, i) => (
                        <span key={i} className="badge badge-neutral" style={{ fontSize: '0.75rem' }}>
                          {typeof c === 'string' ? c : c.policy_name || c.id || JSON.stringify(c)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Exceptions attached to run */}
                {exceptions.length > 0 && (
                  <div>
                    <div style={{ fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
                      Associated Exceptions ({exceptions.length}):
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                      {exceptions.slice(0, 3).map((exc, idx) => (
                        <div
                          key={idx}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            padding: '0.5rem 0.75rem',
                            background: 'var(--bg-primary)',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.8rem',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          <span style={{ fontWeight: 600 }}>{exc.account_code || 'General'}</span>
                          <span style={{ color: 'var(--text-secondary)' }}>{exc.description || 'Variance detected'}</span>
                          {exc.variance_amount !== null && exc.variance_amount !== undefined && (
                            <span style={{ color: 'var(--accent-rose)', fontWeight: 600 }}>
                              ${Number(exc.variance_amount).toFixed(2)}
                            </span>
                          )}
                        </div>
                      ))}
                      {exceptions.length > 3 && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          + {exceptions.length - 3} more exception(s)
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* Reviewer Action Form */}
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.75rem',
                    paddingTop: '0.5rem',
                    borderTop: '1px solid var(--border-color)',
                  }}
                >
                  <input
                    type="text"
                    placeholder="Add audit comments / reason for approval or rejection..."
                    value={comments}
                    onChange={(e) => handleCommentChange(runId, e.target.value)}
                    style={{
                      padding: '0.5rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-color)',
                      background: 'var(--bg-primary)',
                      color: 'var(--text-primary)',
                      fontSize: '0.85rem',
                    }}
                  />

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                    <button
                      className="button button-danger"
                      onClick={() => handleDecision(runId, 'rejected')}
                      disabled={isSubmitting}
                      style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.5rem 1rem' }}
                    >
                      <XCircle size={16} />
                      <span>Reject Recommendation</span>
                    </button>

                    <button
                      className="button button-success"
                      onClick={() => handleDecision(runId, 'approved')}
                      disabled={isSubmitting}
                      style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.5rem 1.25rem' }}
                    >
                      <CheckCircle2 size={16} />
                      <span>Approve & Post</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
