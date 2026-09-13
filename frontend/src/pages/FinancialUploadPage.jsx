import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Upload,
  FileSpreadsheet,
  AlertCircle,
  HelpCircle,
  Building2,
  Calendar,
  Coins,
  CreditCard,
  Clock,
  RotateCcw,
  CheckCircle2,
} from 'lucide-react';
import { DOCUMENT_TYPES } from '../services/uploadNormalizers';
import { uploadFinancialFile, validateFileClientSide } from '../services/uploadService';
import FileDropZone from '../components/upload/FileDropZone';
import ProcessingState from '../components/upload/ProcessingState';
import ImportResultsSummary from '../components/upload/ImportResultsSummary';

const CURRENCY_OPTIONS = ['KES', 'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'ZAR'];

export default function FinancialUploadPage({ setActiveTab }) {
  // Document type and finance parameters
  const [selectedDocType, setSelectedDocType] = useState(DOCUMENT_TYPES.GENERAL_LEDGER.id);
  const [currency, setCurrency] = useState('KES');
  const [period, setPeriod] = useState('2026-Q1');
  const [bankAccount, setBankAccount] = useState('');
  const [usefulLifeUnit, setUsefulLifeUnit] = useState('years');

  // File and upload state
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [importResult, setImportResult] = useState(null);

  // In-flight cancellation and stale-response protection
  const activeAbortControllerRef = useRef(null);
  const requestIdRef = useRef(0);

  // Cleanup on unmount: abort in-flight upload
  useEffect(() => {
    return () => {
      if (activeAbortControllerRef.current) {
        activeAbortControllerRef.current.abort();
      }
    };
  }, []);

  const handleFileSelect = (file, error) => {
    setSelectedFile(file);
    setFileError(error);
    setUploadError(null);
    if (!error && file) {
      setImportResult(null);
    }
  };

  const handleUploadAndValidate = async () => {
    // 1. Prevent double submission
    if (isUploading) return;

    // 2. Validate file
    if (!selectedFile) {
      setFileError('Please select a financial document to upload.');
      return;
    }
    const preError = validateFileClientSide(selectedFile);
    if (preError) {
      setFileError(preError);
      return;
    }

    // 3. Conditional field validation for Bank Statement
    const currentDocConfig = Object.values(DOCUMENT_TYPES).find((d) => d.id === selectedDocType);
    if (currentDocConfig?.requiresBankAccount && !bankAccount.trim()) {
      setUploadError('Please specify the Bank Account reference for this bank statement.');
      return;
    }

    // Set up cancellation and requestId
    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort();
    }
    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    const currentRequestId = ++requestIdRef.current;

    setIsUploading(true);
    setUploadError(null);
    setFileError(null);
    setImportResult(null);

    try {
      const result = await uploadFinancialFile({
        file: selectedFile,
        documentType: selectedDocType,
        financeOptions: {
          currency,
          period,
          bankAccount,
          usefulLifeUnit,
        },
        signal: abortController.signal,
      });

      // Ignore stale response if another request has been started
      if (currentRequestId !== requestIdRef.current) {
        return;
      }

      setImportResult(result);
    } catch (err) {
      if (currentRequestId !== requestIdRef.current) {
        return;
      }
      if (err.name === 'AbortError') {
        return; // User cancelled or unmounted
      }
      // Recoverable error preserves the selected file and form inputs
      setUploadError(err.message || 'An error occurred during upload. Please retry.');
    } finally {
      if (currentRequestId === requestIdRef.current) {
        setIsUploading(false);
      }
    }
  };

  const handleCancel = () => {
    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort();
      activeAbortControllerRef.current = null;
    }
    setIsUploading(false);
  };

  const handleUploadAnother = () => {
    setSelectedFile(null);
    setFileError(null);
    setUploadError(null);
    setImportResult(null);
  };

  const handleClearAll = () => {
    handleCancel();
    setSelectedFile(null);
    setFileError(null);
    setUploadError(null);
    setImportResult(null);
    setBankAccount('');
  };

  const currentDocConfig = Object.values(DOCUMENT_TYPES).find((d) => d.id === selectedDocType);

  return (
    <div className="page-body" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      {/* Page Header */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              backgroundColor: 'var(--primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
            }}
          >
            <Upload size={20} />
          </div>
          <div>
            <h1 style={{ fontSize: '1.65rem', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
              Financial File Upload
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              Upload and validate financial documents for ledger intake and reconciliation.
            </p>
          </div>
        </div>
      </div>

      {/* Main Upload Flow */}
      {!importResult ? (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '2rem',
            backgroundColor: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            padding: '2rem',
          }}
        >
          {/* Step 1: Select Document Type */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.9rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '0.75rem',
              }}
            >
              1. Document Type
            </label>
            <div
              role="radiogroup"
              aria-label="Document Type Selection"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: '0.75rem',
              }}
            >
              {Object.values(DOCUMENT_TYPES).map((doc) => {
                const isSelected = selectedDocType === doc.id;
                return (
                  <button
                    key={doc.id}
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    disabled={isUploading}
                    onClick={() => {
                      setSelectedDocType(doc.id);
                      setUploadError(null);
                    }}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'flex-start',
                      padding: '1rem',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: isSelected ? 'var(--primary-glow)' : 'var(--bg-card)',
                      border: `1.5px solid ${isSelected ? 'var(--primary)' : 'var(--border-color)'}`,
                      cursor: isUploading ? 'not-allowed' : 'pointer',
                      textAlign: 'left',
                      transition: 'all 0.15s ease',
                      opacity: isUploading ? 0.7 : 1,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginBottom: '0.35rem' }}>
                      <span style={{ fontSize: '0.9rem', fontWeight: 600, color: isSelected ? '#fff' : 'var(--text-primary)' }}>
                        {doc.label}
                      </span>
                      {isSelected && <CheckCircle2 size={16} color="var(--primary)" />}
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                      {doc.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Step 2: Financial Parameters */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.9rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '0.75rem',
              }}
            >
              2. Financial Context
            </label>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                gap: '1rem',
                backgroundColor: 'var(--bg-card)',
                padding: '1.25rem',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border-color)',
              }}
            >
              {/* Financial Period */}
              <div>
                <label
                  htmlFor="field-financial-period"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    fontSize: '0.8rem',
                    fontWeight: 500,
                    color: 'var(--text-secondary)',
                    marginBottom: '0.4rem',
                  }}
                >
                  <Calendar size={14} />
                  <span>Financial Period</span>
                </label>
                <input
                  id="field-financial-period"
                  type="text"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                  disabled={isUploading}
                  placeholder="e.g. 2026-Q1"
                  style={{
                    width: '100%',
                    padding: '0.55rem 0.75rem',
                    backgroundColor: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                    fontSize: '0.875rem',
                    outline: 'none',
                  }}
                />
              </div>

              {/* Currency */}
              <div>
                <label
                  htmlFor="field-currency"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    fontSize: '0.8rem',
                    fontWeight: 500,
                    color: 'var(--text-secondary)',
                    marginBottom: '0.4rem',
                  }}
                >
                  <Coins size={14} />
                  <span>Currency</span>
                </label>
                <select
                  id="field-currency"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  disabled={isUploading}
                  style={{
                    width: '100%',
                    padding: '0.55rem 0.75rem',
                    backgroundColor: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                    fontSize: '0.875rem',
                    outline: 'none',
                  }}
                >
                  {CURRENCY_OPTIONS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              {/* Conditional Bank Account (Bank Statement only) */}
              {currentDocConfig?.requiresBankAccount && (
                <div>
                  <label
                    htmlFor="field-bank-account"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                      fontSize: '0.8rem',
                      fontWeight: 500,
                      color: 'var(--text-secondary)',
                      marginBottom: '0.4rem',
                    }}
                  >
                    <CreditCard size={14} />
                    <span>Bank Account</span>
                  </label>
                  <input
                    id="field-bank-account"
                    type="text"
                    value={bankAccount}
                    onChange={(e) => setBankAccount(e.target.value)}
                    disabled={isUploading}
                    placeholder="e.g. Operating-Account-01"
                    style={{
                      width: '100%',
                      padding: '0.55rem 0.75rem',
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                      fontSize: '0.875rem',
                      outline: 'none',
                    }}
                  />
                </div>
              )}

              {/* Conditional Useful Life Unit (Fixed Assets only) */}
              {currentDocConfig?.requiresUsefulLifeUnit && (
                <div>
                  <label
                    htmlFor="field-useful-life-unit"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                      fontSize: '0.8rem',
                      fontWeight: 500,
                      color: 'var(--text-secondary)',
                      marginBottom: '0.4rem',
                    }}
                  >
                    <Clock size={14} />
                    <span>Useful Life Unit</span>
                  </label>
                  <select
                    id="field-useful-life-unit"
                    value={usefulLifeUnit}
                    onChange={(e) => setUsefulLifeUnit(e.target.value)}
                    disabled={isUploading}
                    style={{
                      width: '100%',
                      padding: '0.55rem 0.75rem',
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                      fontSize: '0.875rem',
                      outline: 'none',
                    }}
                  >
                    <option value="years">Years</option>
                    <option value="months">Months</option>
                  </select>
                </div>
              )}
            </div>
          </div>

          {/* Step 3: File Selection / Drag & Drop */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.9rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '0.75rem',
              }}
            >
              3. Document File
            </label>
            <FileDropZone
              selectedFile={selectedFile}
              onFileSelect={handleFileSelect}
              disabled={isUploading}
              error={fileError}
            />
          </div>

          {/* Upload In-Flight Processing State */}
          {isUploading && (
            <ProcessingState
              filename={selectedFile?.name}
              onCancel={handleCancel}
              message="Uploading document and validating records against canonical accounting rules..."
            />
          )}

          {/* Recoverable Error Banner */}
          {uploadError && !isUploading && (
            <div
              role="alert"
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.75rem',
                padding: '1rem 1.25rem',
                backgroundColor: 'rgba(244, 63, 94, 0.1)',
                border: '1px solid rgba(244, 63, 94, 0.3)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--accent-rose)',
                fontSize: '0.875rem',
              }}
            >
              <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
              <div style={{ flex: 1 }}>
                <p style={{ fontWeight: 600, marginBottom: '0.25rem' }}>Upload Could Not Be Completed</p>
                <p style={{ color: 'var(--text-primary)', fontSize: '0.85rem' }}>{uploadError}</p>
              </div>
              <button
                type="button"
                onClick={handleUploadAndValidate}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.4rem 0.75rem',
                  backgroundColor: 'rgba(244, 63, 94, 0.2)',
                  border: '1px solid rgba(244, 63, 94, 0.4)',
                  borderRadius: 'var(--radius-sm)',
                  color: '#fff',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                <RotateCcw size={13} />
                <span>Retry</span>
              </button>
            </div>
          )}

          {/* Action Footer */}
          {!isUploading && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: '1rem',
                paddingTop: '1rem',
                borderTop: '1px solid var(--border-color)',
              }}
            >
              {selectedFile && (
                <button
                  type="button"
                  onClick={handleClearAll}
                  style={{
                    padding: '0.65rem 1.25rem',
                    backgroundColor: 'transparent',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-secondary)',
                    fontSize: '0.875rem',
                    cursor: 'pointer',
                  }}
                >
                  Clear
                </button>
              )}

              <button
                type="button"
                onClick={handleUploadAndValidate}
                disabled={isUploading || !selectedFile || Boolean(fileError)}
                data-testid="upload-and-validate-btn"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.75rem 1.75rem',
                  backgroundColor:
                    !selectedFile || Boolean(fileError) ? 'var(--border-color)' : 'var(--primary)',
                  color: !selectedFile || Boolean(fileError) ? 'var(--text-muted)' : '#fff',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  cursor: !selectedFile || Boolean(fileError) ? 'not-allowed' : 'pointer',
                  transition: 'all 0.15s ease',
                  boxShadow:
                    selectedFile && !fileError ? '0 4px 12px rgba(99, 102, 241, 0.25)' : 'none',
                }}
              >
                <Upload size={16} />
                <span>Upload and Validate</span>
              </button>
            </div>
          )}
        </div>
      ) : (
        /* Results View */
        <ImportResultsSummary
          result={importResult}
          onContinueToReconciliation={() => setActiveTab && setActiveTab('reconciliation')}
          onUploadAnother={handleUploadAnother}
          onRetry={handleUploadAndValidate}
        />
      )}
    </div>
  );
}

