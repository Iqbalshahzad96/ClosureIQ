import { describe, it, expect } from 'vitest';
import {
  DOCUMENT_TYPES,
  getDocumentTypeConfig,
  buildImportOptions,
  normalizeImportResponse,
  RESULT_FIELD_LABELS,
  isImportUsableForReconciliation,
  sanitizeDiagnosticMessage,
} from '../uploadNormalizers';

describe('uploadNormalizers', () => {
  describe('Document types and adapter mapping', () => {
    it('maps document types to approved internal adapter keys', () => {
      expect(DOCUMENT_TYPES.GENERAL_LEDGER.adapterKey).toBe('enquest_ledger');
      expect(DOCUMENT_TYPES.BANK_STATEMENT.adapterKey).toBe('generic_bank');
      expect(DOCUMENT_TYPES.TRIAL_BALANCE.adapterKey).toBe('enquest_tb');
      expect(DOCUMENT_TYPES.AP_INVOICES.adapterKey).toBe('generic_ap_invoice');
      expect(DOCUMENT_TYPES.FIXED_ASSETS.adapterKey).toBe('generic_fixed_asset');
    });

    it('retrieves config for valid document type and throws for unknown type', () => {
      const config = getDocumentTypeConfig('bank_statement');
      expect(config.label).toBe('Bank Statement');
      expect(config.adapterKey).toBe('generic_bank');
      expect(config.requiresBankAccount).toBe(true);

      expect(() => getDocumentTypeConfig('unknown_erp')).toThrow(/unsupported document type/i);
    });
  });

  describe('buildImportOptions', () => {
    it('constructs options for bank statement including bank_account_id', () => {
      const options = buildImportOptions('bank_statement', {
        currency: 'KES',
        period: '2026-Q1',
        bankAccount: 'bank-operating-01',
      });
      expect(options).toEqual({
        currency_code: 'KES',
        fiscal_period: '2026-Q1',
        bank_account_id: 'bank-operating-01',
      });
    });

    it('constructs options for general ledger without bank account', () => {
      const options = buildImportOptions('general_ledger', {
        currency: 'USD',
        period: '2026-Q1',
        bankAccount: 'ignored-account',
      });
      expect(options).toEqual({
        currency_code: 'USD',
        fiscal_period: '2026-Q1',
      });
      expect(options.bank_account_id).toBeUndefined();
    });

    it('constructs options for fixed assets with useful_life_unit', () => {
      const options = buildImportOptions('fixed_assets', {
        currency: 'KES',
        period: '2026-Q1',
        usefulLifeUnit: 'years',
      });
      expect(options).toEqual({
        currency_code: 'KES',
        fiscal_period: '2026-Q1',
        useful_life_unit: 'years',
      });
    });

    it('omits empty or whitespace-only optional fields', () => {
      const options = buildImportOptions('bank_statement', {
        currency: ' ',
        period: '',
        bankAccount: 'bank-01',
      });
      expect(options).toEqual({
        bank_account_id: 'bank-01',
      });
    });
  });

  describe('normalizeImportResponse', () => {
    it('normalizes a successful COMPLETED backend response with exact counts', () => {
      const backendRes = {
        batch_id: 'batch-1234',
        source_system_id: 'runtime-src-1',
        status: 'COMPLETED',
        files_processed: 1,
        total_rows: 150,
        valid_rows: 150,
        quarantined_rows: 0,
        warning_rows: 2,
        duplicate_files: 0,
        technical_duplicate_rows: 0,
        business_duplicate_rows: 0,
        skipped_rows: 3,
        warnings: [{ code: 'WARN_DUAL_POSTING', message: 'Dual sided posting detected' }],
        errors: [],
      };

      const normalized = normalizeImportResponse(backendRes);
      expect(normalized.status).toBe('COMPLETED');
      expect(normalized.batchId).toBe('batch-1234');
      expect(normalized.totalRows).toBe(150);
      expect(normalized.validRows).toBe(150);
      expect(normalized.quarantinedRows).toBe(0);
      expect(normalized.warningRows).toBe(2);
      expect(normalized.skippedRows).toBe(3);
      expect(normalized.warnings).toHaveLength(1);
      expect(normalized.warnings[0].code).toBe('WARN_DUAL_POSTING');
      expect(normalized.isUsable).toBe(true);
    });

    it('handles PARTIAL status with usable rows', () => {
      const backendRes = {
        batch_id: 'batch-partial',
        status: 'PARTIAL',
        total_rows: 100,
        valid_rows: 85,
        quarantined_rows: 15,
        warning_rows: 0,
      };
      const normalized = normalizeImportResponse(backendRes);
      expect(normalized.status).toBe('PARTIAL');
      expect(normalized.isUsable).toBe(true);
      expect(normalized.validRows).toBe(85);
      expect(normalized.quarantinedRows).toBe(15);
    });

    it('handles FAILED and QUARANTINED as non-usable for reconciliation', () => {
      const failed = normalizeImportResponse({ status: 'FAILED', total_rows: 50, valid_rows: 0 });
      expect(failed.isUsable).toBe(false);

      const quarantined = normalizeImportResponse({ status: 'QUARANTINED', total_rows: 50, valid_rows: 0 });
      expect(quarantined.isUsable).toBe(false);
    });

    it('handles DUPLICATE status gracefully', () => {
      const duplicate = normalizeImportResponse({
        batch_id: 'batch-dup',
        status: 'DUPLICATE',
        duplicate_files: 1,
        total_rows: 0,
        valid_rows: 0,
      });
      expect(duplicate.status).toBe('DUPLICATE');
      expect(duplicate.duplicateFiles).toBe(1);
      expect(duplicate.isUsable).toBe(false);
    });

    it('defensively sanitizes malformed, missing, and non-finite counts without NaN or crash', () => {
      const malformed = normalizeImportResponse({
        status: null,
        total_rows: 'not-a-number',
        valid_rows: -5,
        quarantined_rows: Infinity,
        warning_rows: NaN,
        warnings: 'not-an-array',
        errors: null,
      });

      expect(malformed.status).toBe('FAILED');
      expect(malformed.totalRows).toBe(0);
      expect(malformed.validRows).toBe(0);
      expect(malformed.quarantinedRows).toBe(0);
      expect(malformed.warningRows).toBe(0);
      expect(malformed.warnings).toEqual([]);
      expect(malformed.errors).toEqual([]);
      expect(malformed.isUsable).toBe(false);
    });
  });

  describe('Sanitizing diagnostics and error messages', () => {
    it('strips SQL, stack traces, internal paths, and raw credentials', () => {
      const dirty1 = 'Database error: SELECT * FROM credentials WHERE key="abc" at line 42 in /var/app/db.py';
      const clean1 = sanitizeDiagnosticMessage(dirty1);
      expect(clean1).not.toContain('SELECT');
      expect(clean1).not.toContain('/var/app/db.py');
      expect(clean1).toBe('A database operation could not be completed.');

      const dirty2 = 'Traceback (most recent call last):\n  File "storage.py", line 12\nZeroDivisionError';
      const clean2 = sanitizeDiagnosticMessage(dirty2);
      expect(clean2).not.toContain('Traceback');
      expect(clean2).not.toContain('storage.py');
    });

    it('preserves clean finance-friendly messages', () => {
      const clean = 'Missing required booking date on row 14.';
      expect(sanitizeDiagnosticMessage(clean)).toBe(clean);
    });
  });

  describe('RESULT_FIELD_LABELS mapping', () => {
    it('maps all backend fields to expected finance terminology', () => {
      expect(RESULT_FIELD_LABELS.total_rows).toBe('Total records');
      expect(RESULT_FIELD_LABELS.valid_rows).toBe('Successfully added');
      expect(RESULT_FIELD_LABELS.quarantined_rows).toBe('Rejected records');
      expect(RESULT_FIELD_LABELS.warning_rows).toBe('Records with warnings');
      expect(RESULT_FIELD_LABELS.duplicate_files).toBe('Duplicate files');
      expect(RESULT_FIELD_LABELS.technical_duplicate_rows).toBe('Repeated rows');
      expect(RESULT_FIELD_LABELS.business_duplicate_rows).toBe('Duplicate transactions');
      expect(RESULT_FIELD_LABELS.skipped_rows).toBe('Skipped records');
      expect(RESULT_FIELD_LABELS.batch_id).toBe('Import reference');
    });
  });
});

