import React, { useState } from 'react';
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
} from 'lucide-react';
import { runWorkflow, submitApprovalDecision } from '../services/reconciliationService';
import StatusBadge from '../components/StatusBadge';

export default function ReconciliationPage() {
  const [workflowType, setWorkflowType] = useState('reconciliation');
  const [accountCode, setAccountCode] = useState('1010');
  const [period, setPeriod] = useState('2026-Q1');
  const [limit, setLimit] = useState(50);

  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [runResult, setRunResult] = useState(null);

  // In-line HITL state
  const [reviewerName, setReviewerName] = useState('Senior Accountant');
  const [reviewerComments, setReviewerComments] = useState('');
  const [isSubmittingDecision, setIsSubmittingDecision] = useState(false);
  const [decisionError, setDecisionError] = useState(null);

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
        accountCode: workflowType === 'reconciliation' || workflowType === 'accrual' ? accountCode : undefined,
        period,
        limit,
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
        reviewer: reviewerName,
        comments: reviewerComments,
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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Financial Close Workflow Execution</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Deterministic rule engines, AI qualitative review (Agent 1), policy RAG analysis (Agent 2), and HITL approval gates.
          </p>
        </div>
      </div>

      {/* Workflow Run Configuration Card */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h3 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Scale size={18} color="var(--primary)" />
          <span>Workflow Configuration</span>
        </h3>

        <form onSubmit={handleRun} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.25rem', alignItems: 'end' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Workflow Type
            </label>
            <select
              value={workflowType}
              onChange={(e) => setWorkflowType(e.target.value)}
              style={{
                width: '100%',
                padding: '0.6rem 0.8rem',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
              }}
            >
              <option value="reconciliation">GL-to-Bank Reconciliation</option>
              <option value="accrual">Accrual Review & Baseline</option>
              <option value="depreciation">Fixed Asset Depreciation</option>
              <option value="ap_review">AP Invoice Review & Duplicates</option>
            </select>
          </div>

          {(workflowType === 'reconciliation' || workflowType === 'accrual') && (
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
                Account Code
              </label>
              <input
                type="text"
                value={accountCode}
                onChange={(e) => setAccountCode(e.target.value)}
                placeholder="e.g. 1010"
                style={{
                  width: '100%',
                  padding: '0.6rem 0.8rem',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.875rem',
                }}
              />
            </div>
          )}

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Period
            </label>
            <input
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="e.g. 2026-Q1"
              style={{
                width: '100%',
                padding: '0.6rem 0.8rem',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
              }}
            />
          </div>

          <div>
            <button
              type="submit"
              disabled={isRunning}
              className="btn btn-primary"
              style={{ width: '100%', padding: '0.65rem 1rem' }}
            >
              {isRunning ? (
                <>
                  <Clock size={16} className="spin-icon" />
                  <span>Executing Pipeline...</span>
                </>
              ) : (
                <>
                  <Play size={16} />
                  <span>Run Workflow</span>
                </>
              )}
            </button>
          </div>
        </form>

        {runError && (
          <div style={{ marginTop: '1rem', padding: '0.75rem 1rem', background: 'rgba(244, 63, 94, 0.1)', border: '1px solid rgba(244, 63, 94, 0.3)', borderRadius: 'var(--radius-sm)', color: 'var(--accent-rose)', fontSize: '0.875rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertTriangle size={16} />
            <span>{runError}</span>
          </div>
        )}
      </div>

      {/* Execution Results */}
      {runResult && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Header Card */}
          <div className="card" style={{ borderLeft: runResult.status === 'clean_close' || runResult.status === 'approved' ? '4px solid var(--accent-emerald)' : runResult.status === 'hitl_pending' ? '4px solid var(--accent-amber)' : '4px solid var(--accent-rose)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '1rem' }}>
              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>Run ID: {runResult.run_id}</span>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 700, textTransform: 'capitalize' }}>
                  {runResult.workflow_type} — {runResult.period}
                </h2>
              </div>
              <StatusBadge status={runResult.status} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', background: 'var(--bg-secondary)', padding: '1rem', borderRadius: 'var(--radius-sm)' }}>
              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Status</p>
                <p style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{runResult.status}</p>
              </div>
              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Latency</p>
                <p style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{runResult.total_latency_ms} ms</p>
              </div>
              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Exceptions Detected</p>
                <p style={{ fontSize: '1.1rem', fontWeight: 700, color: runResult.exceptions_count > 0 ? 'var(--accent-amber)' : 'var(--accent-emerald)' }}>
                  {runResult.exceptions_count ?? (runResult.exceptions ? runResult.exceptions.length : 0)}
                </p>
              </div>
              <div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Recommendations</p>
                <p style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {runResult.recommendations_count ?? (runResult.recommendations ? runResult.recommendations.length : 0)}
                </p>
              </div>
            </div>
          </div>

          {/* In-line HITL Review Gate Action Card */}
          {runResult.status === 'hitl_pending' && (
            <div className="card" style={{ background: 'rgba(245, 158, 11, 0.05)', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--accent-amber)', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <UserCheck size={20} />
                <span>Human-in-the-Loop Review Required</span>
              </h3>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                This workflow detected exceptions requiring human sign-off before completion. Inspect the Agent reasoning below and submit your decision.
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1rem', marginBottom: '1rem' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.3rem' }}>Reviewer Name</label>
                  <input
                    type="text"
                    value={reviewerName}
                    onChange={(e) => setReviewerName(e.target.value)}
                    style={{ width: '100%', padding: '0.5rem', borderRadius: 'var(--radius-sm)', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: '#fff', fontSize: '0.875rem' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.3rem' }}>Audit Notes / Reason</label>
                  <input
                    type="text"
                    value={reviewerComments}
                    onChange={(e) => setReviewerComments(e.target.value)}
                    placeholder="e.g. Approved adjustment after vendor cross-check"
                    style={{ width: '100%', padding: '0.5rem', borderRadius: 'var(--radius-sm)', background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: '#fff', fontSize: '0.875rem' }}
                  />
                </div>
              </div>

              {decisionError && (
                <p style={{ color: 'var(--accent-rose)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>{decisionError}</p>
              )}

              <div style={{ display: 'flex', gap: '1rem' }}>
                <button
                  type="button"
                  disabled={isSubmittingDecision}
                  onClick={() => handleDecision('approved')}
                  className="btn"
                  style={{ backgroundColor: 'var(--accent-emerald)', color: '#fff' }}
                >
                  <CheckCircle2 size={16} />
                  <span>Approve Workflow</span>
                </button>
                <button
                  type="button"
                  disabled={isSubmittingDecision}
                  onClick={() => handleDecision('rejected')}
                  className="btn"
                  style={{ backgroundColor: 'var(--accent-rose)', color: '#fff' }}
                >
                  <XCircle size={16} />
                  <span>Reject Workflow</span>
                </button>
              </div>
            </div>
          )}

          {/* Exceptions & Findings Breakdown */}
          {runResult.exceptions && runResult.exceptions.length > 0 && (
            <div className="card">
              <h3 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '1rem' }}>
                Detected Exceptions ({runResult.exceptions.length})
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {runResult.exceptions.map((exc, idx) => (
                  <div key={exc.id || idx} style={{ padding: '1rem', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                      <span className={`badge ${exc.severity === 'HIGH' ? 'badge-rose' : exc.severity === 'MEDIUM' ? 'badge-amber' : 'badge-indigo'}`}>
                        {exc.severity || 'MEDIUM'}
                      </span>
                      <span style={{ fontSize: '0.9rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                        Variance: ${Number(exc.amount_variance || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.875rem', color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                      {exc.description}
                    </p>

                    {/* Source Lineage Badge */}
                    {exc.lineage && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'var(--bg-card)', padding: '0.4rem 0.6rem', borderRadius: '4px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        <Tag size={12} color="var(--primary)" />
                        <span>Source: <strong>{exc.lineage.source_file?.original_filename || 'Canonical DB'}</strong></span>
                        {exc.lineage.source_row_identifier && (
                          <span>| Row: <strong>{exc.lineage.source_row_identifier}</strong></span>
                        )}
                        {exc.lineage.source_system?.display_name && (
                          <span>| System: <strong>{exc.lineage.source_system.display_name}</strong></span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Agent 1 Qualitative Review Findings */}
          {runResult.agent_1_review && Object.keys(runResult.agent_1_review).length > 0 && (
            <div className="card">
              <h3 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <FileText size={18} color="var(--primary)" />
                <span>Agent 1 (Financial Review) Assessment</span>
              </h3>
              <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                {runResult.agent_1_review.summary_assessment || 'Review complete.'}
              </p>

              {runResult.agent_1_review.findings && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {runResult.agent_1_review.findings.map((f, i) => (
                    <div key={i} style={{ padding: '0.75rem', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.3rem' }}>
                        <span className="badge badge-indigo">{f.classification || 'REVIEWED'}</span>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Exception #{f.exception_index + 1}</span>
                      </div>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>{f.financial_context}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Agent 2 Policy Grounded Analyses */}
          {runResult.agent_2_analyses && runResult.agent_2_analyses.length > 0 && (
            <div className="card">
              <h3 style={{ fontSize: '1.05rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <BookOpen size={18} color="var(--accent-emerald)" />
                <span>Agent 2 (Exception Analysis & Policy Evidence)</span>
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {runResult.agent_2_analyses.map((a2, i) => (
                  <div key={i} style={{ padding: '1rem', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                    <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--accent-emerald)', marginBottom: '0.3rem' }}>
                      Root Cause: {a2.root_cause || a2.root_cause_hypothesis || 'Under Investigation'}
                    </h4>
                    <p style={{ fontSize: '0.875rem', color: 'var(--text-primary)', marginBottom: '0.75rem' }}>
                      {a2.analysis}
                    </p>

                    <div style={{ padding: '0.75rem', background: 'var(--bg-card)', borderRadius: 'var(--radius-sm)', marginBottom: '0.75rem' }}>
                      <strong style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Recommended Action:</strong>
                      <p style={{ fontSize: '0.875rem', color: '#fff', marginTop: '0.2rem' }}>
                        {a2.recommendation || a2.recommended_action || 'No action needed'}
                      </p>
                    </div>

                    {/* Policy Citations */}
                    {a2.policy_citations && a2.policy_citations.length > 0 && (
                      <div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>Cited Accounting SOPs:</span>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                          {a2.policy_citations.map((c, cIdx) => (
                            <div key={cIdx} style={{ fontSize: '0.75rem', background: 'rgba(99, 102, 241, 0.08)', padding: '0.4rem 0.6rem', borderRadius: '4px', borderLeft: '2px solid var(--primary)' }}>
                              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.citation || c.metadata?.title || 'Policy Rule'}</span>
                              <p style={{ color: 'var(--text-secondary)', marginTop: '0.1rem' }}>{c.content}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
