import React, { useState, useRef, useEffect } from 'react';
import {
  Upload,
  AlertCircle,
  RotateCcw,
  CheckCircle2,
  FolderUp,
} from 'lucide-react';
import { DOCUMENT_TYPES, getDocumentTypeConfig } from '../services/uploadNormalizers';
import { stageFinancialFile, confirmFinancialFile, validateFileClientSide } from '../services/uploadService';
import FileDropZone from '../components/upload/FileDropZone';
import ProcessingState from '../components/upload/ProcessingState';
import ImportResultsSummary from '../components/upload/ImportResultsSummary';
import FinancialDatabaseSection from '../components/financial/FinancialDatabaseSection';

export default function FinancialUploadPage({ setActiveTab }) {
  // Document context state
  const [selectedDocType, setSelectedDocType] = useState(DOCUMENT_TYPES.GENERAL_LEDGER.id);
  const [currency, setCurrency] = useState('');
  const [period, setPeriod] = useState('');
  const [bankAccount, setBankAccount] = useState('');
  const [usefulLifeUnit, setUsefulLifeUnit] = useState('years');

  // Upload and File state
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [dbRefreshKey, setDbRefreshKey] = useState(0);
  const [needsDocumentTypeChoice, setNeedsDocumentTypeChoice] = useState(false);

  // In-flight cancellation & overlapping request protection
  const activeAbortControllerRef = useRef(null);
  const requestIdRef = useRef(0);

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
    setNeedsDocumentTypeChoice(false);
  };

  const handleUploadAndValidate = async (forceDocumentType = false, overrideDocumentType = null) => {
    if (isUploading || !selectedFile) return;

    const preError = validateFileClientSide(selectedFile);
    if (preError) {
      setFileError(preError);
      return;
    }

    if (activeAbortControllerRef.current) {
      activeAbortControllerRef.current.abort();
    }
    const abortController = new AbortController();
    activeAbortControllerRef.current = abortController;
    const currentRequestId = ++requestIdRef.current;

    setIsUploading(true);
    setUploadError(null);
    setFileError(null);

    try {
      const staged = await stageFinancialFile({ file: selectedFile, signal: abortController.signal });
      const detected = staged.detected_context || {};
      const detectedDocType = detected.documentType;
      const forcedDocumentType = overrideDocumentType || selectedDocType;
      const detectedDocConfig = forceDocumentType
        ? getDocumentTypeConfig(forcedDocumentType)
        : getDocumentTypeConfig(
          Object.values(DOCUMENT_TYPES).find((doc) => doc.id === detectedDocType || doc.id.toUpperCase() === detectedDocType)?.id
            || Object.values(DOCUMENT_TYPES).find((doc) => doc.label.toUpperCase().replaceAll(' ', '_') === detectedDocType)?.id
            || DOCUMENT_TYPES.GENERAL_LEDGER.id
        );
      const detectedCurrency = detected.currency || currency;
      const detectedPeriod = detected.period || period;
      const detectedBankAccount = detected.bankAccount || bankAccount;
      const detectedUsefulLifeUnit = usefulLifeUnit;

      setSelectedDocType(detectedDocConfig.id);
      setCurrency(detectedCurrency);
      setPeriod(detectedPeriod);
      setBankAccount(detectedBankAccount);
      setNeedsDocumentTypeChoice(false);

      const result = await confirmFinancialFile({
        fileId: staged.file_id,
        filename: staged.filename || selectedFile.name,
        documentType: detectedDocConfig.id,
        financeOptions: {
          currency: detectedCurrency,
          period: detectedPeriod,
          bankAccount: detectedDocConfig?.requiresBankAccount ? detectedBankAccount : undefined,
          usefulLifeUnit: detectedDocConfig?.requiresUsefulLifeUnit ? detectedUsefulLifeUnit : undefined,
        },
        signal: abortController.signal,
      });

      if (currentRequestId !== requestIdRef.current) return;
      setImportResult(result);
      if (result.status === 'FAILED') {
        setNeedsDocumentTypeChoice(true);
      }
      // Trigger database refresh
      setDbRefreshKey((prev) => prev + 1);
    } catch (err) {
      if (currentRequestId !== requestIdRef.current) return;
      if (err.name === 'AbortError') return;
      setUploadError(err.message || 'An error occurred during upload. Please retry.');
      if (!forceDocumentType) {
        setNeedsDocumentTypeChoice(true);
      }
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
    setNeedsDocumentTypeChoice(false);
  };

  const handleClearAll = () => {
    handleCancel();
    setSelectedFile(null);
    setFileError(null);
    setUploadError(null);
    setBankAccount('');
    setNeedsDocumentTypeChoice(false);
  };


  const renderDocumentTypeFallback = () => (
    <div
      role="region"
      aria-label="Choose document type"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '0.9rem',
        padding: '1rem',
        backgroundColor: 'rgba(245, 158, 11, 0.08)',
        border: '1px solid rgba(245, 158, 11, 0.35)',
        borderRadius: 'var(--radius-sm)',
      }}
    >
      <div>
        <p style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: '0.25rem' }}>
          We could not confidently detect this file type
        </p>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Choose the correct document type, then retry import.
        </p>
      </div>
      <div
        role="radiogroup"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
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
                padding: '0.85rem',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: isSelected ? 'var(--primary-glow)' : 'var(--bg-card)',
                border: `1.5px solid ${isSelected ? 'var(--primary)' : 'var(--border-color)'}`,
                color: 'var(--text-primary)',
                textAlign: 'left',
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 700 }}>{doc.label}</span>
                {isSelected && <CheckCircle2 size={15} color="var(--primary)" />}
              </div>
            </button>
          );
        })}
      </div>
      <button
        type="button"
        onClick={() => handleUploadAndValidate(true, selectedDocType)}
        disabled={isUploading || !selectedFile}
        className="btn btn-primary"
        style={{ alignSelf: 'flex-start', padding: '0.65rem 1rem' }}
      >
        Retry with selected document type
      </button>
    </div>
  );

  return (
    <div className="page-body" style={{ display: 'flex', flexDirection: 'column', gap: '2.5rem' }}>
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
              Financial Data
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              Upload and validate financial documents for ledger intake, reconciliation, and reporting.
            </p>
          </div>
        </div>
      </div>

      {/* Section 1: Financial File Upload */}
      <section aria-labelledby="financial-file-upload-heading">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
          <FolderUp size={18} color="var(--primary)" />
          <h2
            id="financial-file-upload-heading"
            style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}
          >
            Financial File Upload
          </h2>
        </div>

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
            {/* File Selection / Drag & Drop */}

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
                Document File
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
                  onClick={() => handleUploadAndValidate(needsDocumentTypeChoice, selectedDocType)}
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

            {needsDocumentTypeChoice && !isUploading && renderDocumentTypeFallback()}

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
                  onClick={() => handleUploadAndValidate(needsDocumentTypeChoice, selectedDocType)}
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
                  <span>Upload</span>
                </button>
              </div>
            )}
          </div>
        ) : (
          /* Results View */
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {needsDocumentTypeChoice && renderDocumentTypeFallback()}
            <ImportResultsSummary
              result={importResult}
              onContinueToReconciliation={() => setActiveTab && setActiveTab('reconciliation')}
              onUploadAnother={handleUploadAnother}
              onRetry={() => setNeedsDocumentTypeChoice(true)}
            />
          </div>
        )}
      </section>

      {/* Section 2: Financial Data in Database */}
      <section aria-labelledby="financial-data-database-heading">
        <FinancialDatabaseSection refreshTrigger={dbRefreshKey} />
      </section>
    </div>
  );
}
