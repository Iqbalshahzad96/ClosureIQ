/**
 * Normalization utilities for Financial File Upload.
 *
 * Implements code-controlled document-type-to-adapter mapping,
 * internal X-Import-Options generation from finance fields,
 * defensive parsing of backend responses, and mapping to finance-friendly terminology.
 */

export const DOCUMENT_TYPES = Object.freeze({
  GENERAL_LEDGER: {
    id: 'general_ledger',
    label: 'General Ledger',
    adapterKey: 'enquest_ledger',
    description: 'Enquest ERP standard account ledger exports (.xlsx, .xls).',
    requiresBankAccount: false,
    requiresUsefulLifeUnit: false,
  },
  BANK_STATEMENT: {
    id: 'bank_statement',
    label: 'Bank Statement',
    adapterKey: 'generic_bank',
    description: 'Standard bank statement transaction files (.csv, .xlsx, .xls).',
    requiresBankAccount: true,
    requiresUsefulLifeUnit: false,
  },
  TRIAL_BALANCE: {
    id: 'trial_balance',
    label: 'Trial Balance',
    adapterKey: 'enquest_tb',
    description: 'Periodic trial balance balances and account movements (.xlsx, .xls).',
    requiresBankAccount: false,
    requiresUsefulLifeUnit: false,
  },
  AP_INVOICES: {
    id: 'ap_invoices',
    label: 'Accounts Payable Invoices',
    adapterKey: 'generic_ap_invoice',
    description: 'Supplier invoice registers with invoice dates and amounts (.csv, .xlsx, .xls).',
    requiresBankAccount: false,
    requiresUsefulLifeUnit: false,
  },
  FIXED_ASSETS: {
    id: 'fixed_assets',
    label: 'Fixed Asset Register',
    adapterKey: 'generic_fixed_asset',
    description: 'Fixed asset schedules with asset codes, costs, and depreciation (.csv, .xlsx, .xls).',
    requiresBankAccount: false,
    requiresUsefulLifeUnit: true,
  },
});

export const RESULT_FIELD_LABELS = Object.freeze({
  total_rows: 'Total records',
  valid_rows: 'Successfully added',
  quarantined_rows: 'Rejected records',
  warning_rows: 'Records with warnings',
  duplicate_files: 'Duplicate files',
  technical_duplicate_rows: 'Repeated rows',
  business_duplicate_rows: 'Duplicate transactions',
  skipped_rows: 'Skipped records',
  batch_id: 'Import reference',
});

export const VALID_STATUSES = ['COMPLETED', 'PARTIAL', 'QUARANTINED', 'FAILED', 'DUPLICATE'];

/**
 * Get configuration for a document type key.
 */
export function getDocumentTypeConfig(docTypeId) {
  const match = Object.values(DOCUMENT_TYPES).find((d) => d.id === docTypeId);
  if (!match) {
    throw new Error(`Unsupported document type: ${docTypeId}`);
  }
  return match;
}

/**
 * Build internal X-Import-Options header object from finance form fields.
 * Never exposes JSON fields or raw technical keys to users.
 */
export function buildImportOptions(docTypeId, financeValues = {}) {
  const config = getDocumentTypeConfig(docTypeId);
  const options = {};

  if (financeValues.currency && String(financeValues.currency).trim()) {
    options.currency_code = String(financeValues.currency).trim().toUpperCase();
  }

  if (financeValues.period && String(financeValues.period).trim()) {
    options.fiscal_period = String(financeValues.period).trim();
  }

  if (config.requiresBankAccount && financeValues.bankAccount && String(financeValues.bankAccount).trim()) {
    options.bank_account_id = String(financeValues.bankAccount).trim();
  }

  if (config.requiresUsefulLifeUnit && financeValues.usefulLifeUnit && String(financeValues.usefulLifeUnit).trim()) {
    options.useful_life_unit = String(financeValues.usefulLifeUnit).trim().toLowerCase();
  }

  return options;
}

/**
 * Defensive integer coercion for count metrics.
 */
function safeCount(val) {
  if (typeof val === 'number' && Number.isFinite(val) && val >= 0) {
    return Math.floor(val);
  }
  const parsed = parseInt(val, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

/**
 * Sanitize error and diagnostic strings to ensure no SQL, stack traces, or internal paths leak.
 */
export function sanitizeDiagnosticMessage(msg) {
  if (!msg || typeof msg !== 'string') {
    return 'A processing issue occurred while validating records.';
  }

  // Check for SQL keywords or query fragments
  if (/(\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bFROM\b|\bWHERE\b|\bJOIN\b)/i.test(msg)) {
    return 'A database operation could not be completed.';
  }

  // Check for stack traces or python/system paths
  if (/(\bTraceback\b|File\s+["'].*?["']|\.py\b|[\\/](var|etc|usr|home|users|c:|d:))/i.test(msg)) {
    return 'An internal processing error occurred during file parsing.';
  }

  // Check for sensitive credential leaks
  if (/(\bpassword\b|\bsecret\b|\btoken\b|\bkey=)/i.test(msg)) {
    return 'An authorization issue was detected.';
  }

  // Return cleaned message (max 200 chars)
  return msg.trim().slice(0, 200);
}

/**
 * Normalizes backend ingestion summary into safe, finance-labelled structure.
 */
export function normalizeImportResponse(raw) {
  if (!raw || typeof raw !== 'object') {
    return {
      status: 'FAILED',
      isUsable: false,
      batchId: null,
      sourceFileId: null,
      totalRows: 0,
      validRows: 0,
      quarantinedRows: 0,
      warningRows: 0,
      duplicateFiles: 0,
      technicalDuplicateRows: 0,
      businessDuplicateRows: 0,
      skippedRows: 0,
      warnings: [],
      errors: [{ code: 'ERR_INVALID_RESPONSE', message: 'The server returned an unexpected response format.' }],
    };
  }

  const rawStatus = typeof raw.status === 'string' ? raw.status.toUpperCase().trim() : '';
  const status = VALID_STATUSES.includes(rawStatus) ? rawStatus : 'FAILED';

  const totalRows = safeCount(raw.total_rows);
  const validRows = safeCount(raw.valid_rows);
  const quarantinedRows = safeCount(raw.quarantined_rows);
  const warningRows = safeCount(raw.warning_rows);
  const duplicateFiles = safeCount(raw.duplicate_files);
  const technicalDuplicateRows = safeCount(raw.technical_duplicate_rows);
  const businessDuplicateRows = safeCount(raw.business_duplicate_rows);
  const skippedRows = safeCount(raw.skipped_rows);

  const warnings = Array.isArray(raw.warnings)
    ? raw.warnings.map((w) => ({
        code: typeof w?.code === 'string' ? w.code : 'WARNING',
        message: sanitizeDiagnosticMessage(w?.message || w?.code || 'Record flagged with warning'),
        rowNumber: w?.row_number ? safeCount(w.row_number) : undefined,
      }))
    : [];

  const errors = Array.isArray(raw.errors)
    ? raw.errors.map((e) => ({
        code: typeof e?.code === 'string' ? e.code : 'ERROR',
        message: sanitizeDiagnosticMessage(e?.message || e?.code || 'Record rejected during validation'),
        rowNumber: e?.row_number ? safeCount(e.row_number) : undefined,
      }))
    : [];

  // Usable for continuing to reconciliation only after a usable successful/partial import
  const isUsable = (status === 'COMPLETED' || status === 'PARTIAL') && validRows > 0;

  return {
    status,
    isUsable,
    batchId: typeof raw.batch_id === 'string' ? raw.batch_id : null,
    sourceFileId: typeof raw.source_file_id === 'string' ? raw.source_file_id : null,
    totalRows,
    validRows,
    quarantinedRows,
    warningRows,
    duplicateFiles,
    technicalDuplicateRows,
    businessDuplicateRows,
    skippedRows,
    warnings,
    errors,
  };
}

export function isImportUsableForReconciliation(normalizedResult) {
  return Boolean(normalizedResult?.isUsable);
}

