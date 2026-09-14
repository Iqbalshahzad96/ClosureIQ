import React from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Copy,
  ChevronRight,
  ArrowRight,
  RotateCcw,
  PlusCircle,
  FileCheck,
} from 'lucide-react';
import StatusBadge from '../StatusBadge';
import { RESULT_FIELD_LABELS } from '../../services/uploadNormalizers';

export default function ImportResultsSummary({
  result,
  onContinueToReconciliation,
  onUploadAnother,
  onRetry,
}) {
  if (!result) return null;

  const {
    status,
    isUsable,
    batchId,
    totalRows,
    validRows,
    quarantinedRows,
    warningRows,
    duplicateFiles,
    technicalDuplicateRows,
    businessDuplicateRows,
    skippedRows,
    warnings = [],
    errors = [],
  } = result;

  const getStatusPresentation = () => {
    switch (status) {
      case 'COMPLETED':
        return {
          badgeVariant: 'emerald',
          title: 'Import Completed Successfully',
          description: 'All valid transactions have been mapped and added to the canonical financial ledger.',
          Icon: CheckCircle2,
          iconColor: 'var(--accent-emerald)',
        };
      case 'PARTIAL':
        return {
          badgeVariant: 'amber',
          title: 'Import Partially Completed',
          description: 'Usable records were added to the ledger, but some records failed validation and were quarantined.',
          Icon: AlertTriangle,
          iconColor: 'var(--accent-amber)',
        };
      case 'QUARANTINED':
        return {
          badgeVariant: 'rose',
          title: 'All Records Quarantined',
          description: 'The document was read, but none of the records passed accounting validation rules.',
          Icon: XCircle,
          iconColor: 'var(--accent-rose)',
        };
      case 'DUPLICATE':
        return {
          badgeVariant: 'amber',
          title: 'Duplicate File Detected',
          description: 'This exact document content has already been imported. No duplicate records were added.',
          Icon: Copy,
          iconColor: 'var(--accent-amber)',
        };
      case 'FAILED':
      default:
        return {
          badgeVariant: 'rose',
          title: 'Document Import Failed',
          description: 'The file could not be processed. Please check the document format and try again.',
          Icon: XCircle,
          iconColor: 'var(--accent-rose)',
        };
    }
  };

  const presentation = getStatusPresentation();
  const StatusIcon = presentation.Icon;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1.5rem',
        backgroundColor: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        borderRadius: 'var(--radius-md)',
        padding: '2rem',
      }}
      data-testid="import-results-summary"
    >
      {/* Header status banner */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '1rem' }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: '50%',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
              color: presentation.iconColor,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <StatusIcon size={26} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.35rem' }}>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                {presentation.title}
              </h3>
              <StatusBadge status={status} variant={presentation.badgeVariant} />
            </div>
            <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
              {presentation.description}
            </p>
          </div>
        </div>
      </div>

      {/* Primary KPI Metrics Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1rem',
        }}
      >
        <div className="metric-card" data-testid="metric-total-records">
          <span className="metric-label">{RESULT_FIELD_LABELS.total_rows}</span>
          <div className="metric-value">{totalRows.toLocaleString()}</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>From source file</div>
        </div>

        <div className="metric-card" data-testid="metric-successfully-added">
          <span className="metric-label">{RESULT_FIELD_LABELS.valid_rows}</span>
          <div className="metric-value" style={{ color: 'var(--accent-emerald)' }}>
            {validRows.toLocaleString()}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Available for reconciliation</div>
        </div>

        <div className="metric-card" data-testid="metric-rejected-records">
          <span className="metric-label">{RESULT_FIELD_LABELS.quarantined_rows}</span>
          <div className="metric-value" style={{ color: quarantinedRows > 0 ? 'var(--accent-rose)' : 'var(--text-primary)' }}>
            {quarantinedRows.toLocaleString()}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Requires review or correction</div>
        </div>

        <div className="metric-card" data-testid="metric-records-with-warnings">
          <span className="metric-label">{RESULT_FIELD_LABELS.warning_rows}</span>
          <div className="metric-value" style={{ color: warningRows > 0 ? 'var(--accent-amber)' : 'var(--text-primary)' }}>
            {warningRows.toLocaleString()}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Accepted with flags</div>
        </div>
      </div>

      {/* Secondary details (Repeated rows, duplicate transactions, skipped records, import reference) */}
      <div
        style={{
          backgroundColor: 'var(--bg-card)',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border-color)',
          padding: '1rem 1.25rem',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '1.5rem',
          fontSize: '0.85rem',
        }}
      >
        {technicalDuplicateRows > 0 && (
          <div>
            <span style={{ color: 'var(--text-muted)' }}>{RESULT_FIELD_LABELS.technical_duplicate_rows}: </span>
            <strong style={{ color: 'var(--text-primary)' }}>{technicalDuplicateRows}</strong>
          </div>
        )}
        {businessDuplicateRows > 0 && (
          <div>
            <span style={{ color: 'var(--text-muted)' }}>{RESULT_FIELD_LABELS.business_duplicate_rows}: </span>
            <strong style={{ color: 'var(--text-primary)' }}>{businessDuplicateRows}</strong>
          </div>
        )}
        {skippedRows > 0 && (
          <div>
            <span style={{ color: 'var(--text-muted)' }}>{RESULT_FIELD_LABELS.skipped_rows}: </span>
            <strong style={{ color: 'var(--text-primary)' }}>{skippedRows}</strong>
          </div>
        )}
        {duplicateFiles > 0 && (
          <div>
            <span style={{ color: 'var(--text-muted)' }}>{RESULT_FIELD_LABELS.duplicate_files}: </span>
            <strong style={{ color: 'var(--text-primary)' }}>{duplicateFiles}</strong>
          </div>
        )}
        {batchId && (
          <div style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
            <span>{RESULT_FIELD_LABELS.batch_id}: </span>
            <code style={{ color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.2)', padding: '2px 6px', borderRadius: 4 }}>
              {batchId}
            </code>
          </div>
        )}
      </div>

      {/* Expandable Rejection Reasons / Errors */}
      {errors.length > 0 && (
        <details
          style={{
            backgroundColor: 'rgba(244, 63, 94, 0.05)',
            border: '1px solid rgba(244, 63, 94, 0.25)',
            borderRadius: 'var(--radius-sm)',
            overflow: 'hidden',
          }}
          data-testid="rejection-reasons-details"
        >
          <summary
            style={{
              padding: '0.85rem 1.25rem',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.9rem',
              color: 'var(--accent-rose)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              userSelect: 'none',
            }}
          >
            <AlertTriangle size={16} />
            <span>Rejection Reasons & Errors ({errors.length})</span>
          </summary>
          <div style={{ padding: '0.5rem 1.25rem 1rem', borderTop: '1px solid rgba(244, 63, 94, 0.15)' }}>
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {errors.map((err, idx) => (
                <li
                  key={idx}
                  style={{
                    fontSize: '0.85rem',
                    color: 'var(--text-primary)',
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: '0.5rem',
                  }}
                >
                  <span style={{ color: 'var(--accent-rose)', fontWeight: 600 }}>•</span>
                  <span>
                    {err.rowNumber ? `Row ${err.rowNumber}: ` : ''}
                    {err.message}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </details>
      )}

      {/* Expandable Warnings */}
      {warnings.length > 0 && (
        <details
          style={{
            backgroundColor: 'rgba(245, 158, 11, 0.05)',
            border: '1px solid rgba(245, 158, 11, 0.25)',
            borderRadius: 'var(--radius-sm)',
            overflow: 'hidden',
          }}
          data-testid="warning-records-details"
        >
          <summary
            style={{
              padding: '0.85rem 1.25rem',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.9rem',
              color: 'var(--accent-amber)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              userSelect: 'none',
            }}
          >
            <AlertTriangle size={16} />
            <span>Warnings & Non-Blocking Flags ({warnings.length})</span>
          </summary>
          <div style={{ padding: '0.5rem 1.25rem 1rem', borderTop: '1px solid rgba(245, 158, 11, 0.15)' }}>
            <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {warnings.map((warn, idx) => (
                <li
                  key={idx}
                  style={{
                    fontSize: '0.85rem',
                    color: 'var(--text-primary)',
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: '0.5rem',
                  }}
                >
                  <span style={{ color: 'var(--accent-amber)', fontWeight: 600 }}>•</span>
                  <span>
                    {warn.rowNumber ? `Row ${warn.rowNumber}: ` : ''}
                    {warn.message}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </details>
      )}

      {/* Action Footer */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
          flexWrap: 'wrap',
          paddingTop: '1rem',
          borderTop: '1px solid var(--border-color)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <button
            type="button"
            onClick={onUploadAnother}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.65rem 1.15rem',
              backgroundColor: 'transparent',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            <PlusCircle size={16} />
            <span>Upload Another Document</span>
          </button>

          {!isUsable && onRetry && (
            <button
              type="button"
              onClick={onRetry}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.65rem 1.15rem',
                backgroundColor: 'transparent',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-secondary)',
                fontSize: '0.875rem',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              <RotateCcw size={16} />
              <span>Retry Upload</span>
            </button>
          )}
        </div>

        {/* Continue to Reconciliation provided ONLY after usable import */}
        {isUsable && onContinueToReconciliation && (
          <button
            type="button"
            onClick={onContinueToReconciliation}
            data-testid="continue-to-reconciliation-btn"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.7rem 1.4rem',
              backgroundColor: 'var(--accent-emerald)',
              color: '#fff',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.9rem',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: '0 4px 12px rgba(16, 185, 129, 0.25)',
              transition: 'all 0.15s ease',
            }}
          >
            <span>Continue to Reconciliation</span>
            <ArrowRight size={16} />
          </button>
        )}
      </div>
    </div>
  );
}

