import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  uploadFinancialFile,
  validateFileClientSide,
  getContentTypeForFile,
  MAX_FILE_BYTES,
  SUPPORTED_EXTENSIONS,
} from '../uploadService';

describe('uploadService', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  describe('validateFileClientSide', () => {
    it('accepts valid .csv, .xls, and .xlsx files under 25 MiB', () => {
      const validCsv = new File(['col1,col2\nval1,val2'], 'ledger.csv', { type: 'text/csv' });
      const validXlsx = new File([new ArrayBuffer(100)], 'trial_balance.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const validXls = new File([new ArrayBuffer(100)], 'statement.xls', {
        type: 'application/vnd.ms-excel',
      });

      expect(validateFileClientSide(validCsv)).toBeNull();
      expect(validateFileClientSide(validXlsx)).toBeNull();
      expect(validateFileClientSide(validXls)).toBeNull();
    });

    it('rejects empty file (0 bytes)', () => {
      const emptyFile = new File([], 'empty.csv', { type: 'text/csv' });
      const error = validateFileClientSide(emptyFile);
      expect(error).toMatch(/file is empty/i);
    });

    it('rejects file larger than 25 MiB', () => {
      const largeFile = {
        name: 'huge.xlsx',
        size: MAX_FILE_BYTES + 1,
      };
      const error = validateFileClientSide(largeFile);
      expect(error).toMatch(/exceeds the 25 MiB/i);
    });

    it('rejects unsupported file extensions (e.g. .pdf, .json, .txt)', () => {
      const pdfFile = new File(['dummy'], 'invoice.pdf', { type: 'application/pdf' });
      const error = validateFileClientSide(pdfFile);
      expect(error).toMatch(/unsupported file format/i);
    });
  });

  describe('getContentTypeForFile', () => {
    it('returns correct MIME type based on file extension', () => {
      expect(getContentTypeForFile('test.csv')).toBe('text/csv');
      expect(getContentTypeForFile('test.xlsx')).toBe(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      );
      expect(getContentTypeForFile('test.xls')).toBe('application/vnd.ms-excel');
      expect(getContentTypeForFile('test.UNKNOWN')).toBe('application/octet-stream');
    });
  });

  describe('uploadFinancialFile HTTP contract', () => {
    it('sends raw file bytes as body, NOT FormData and NOT JSON', async () => {
      let capturedBody = null;
      let capturedHeaders = null;
      let capturedUrl = null;

      global.fetch = vi.fn().mockImplementation((url, init) => {
        capturedUrl = String(url);
        capturedBody = init.body;
        capturedHeaders = init.headers;
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            batch_id: 'batch-abc',
            status: 'COMPLETED',
            total_rows: 10,
            valid_rows: 10,
          }),
        });
      });

      const file = new File(['a,b,c\n1,2,3'], 'bank.csv', { type: 'text/csv' });
      const result = await uploadFinancialFile({
        file,
        documentType: 'bank_statement',
        financeOptions: {
          currency: 'KES',
          period: '2026-Q1',
          bankAccount: 'bank-1',
        },
      });

      expect(result.status).toBe('COMPLETED');
      expect(result.validRows).toBe(10);

      // Body must be the File / Blob directly, NOT FormData and NOT a JSON string
      expect(capturedBody).toBe(file);
      expect(capturedBody instanceof FormData).toBe(false);
      expect(typeof capturedBody).not.toBe('string');

      // Headers
      expect(capturedHeaders['Content-Type']).toBe('text/csv');
      expect(capturedHeaders['X-Import-Options']).toBe(
        JSON.stringify({
          currency_code: 'KES',
          fiscal_period: '2026-Q1',
          bank_account_id: 'bank-1',
        })
      );

      // URL parameters: must have filename and adapter_key, and OMIT source_system_id
      expect(capturedUrl).toContain('/imports/upload');
      expect(capturedUrl).toContain('filename=bank.csv');
      expect(capturedUrl).toContain('adapter_key=generic_bank');
      expect(capturedUrl).not.toContain('source_system_id');
      expect(capturedUrl).not.toContain('organization_id');
    });

    it('safely encodes query parameters with special characters', async () => {
      let capturedUrl = '';
      global.fetch = vi.fn().mockImplementation((url) => {
        capturedUrl = String(url);
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'COMPLETED', valid_rows: 5 }),
        });
      });

      const file = new File(['test'], 'ledger & close (2026).xlsx');
      await uploadFinancialFile({
        file,
        documentType: 'general_ledger',
        financeOptions: { currency: 'USD' },
      });

      const urlObj = new URL(capturedUrl);
      expect(urlObj.searchParams.get('filename')).toBe('ledger & close (2026).xlsx');
      expect(urlObj.searchParams.get('adapter_key')).toBe('enquest_ledger');
    });

    it('supports cancellation with AbortController signal', async () => {
      const controller = new AbortController();

      global.fetch = vi.fn().mockImplementation((url, init) => {
        return new Promise((_, reject) => {
          init.signal.addEventListener('abort', () => {
            const err = new Error('The user aborted a request.');
            err.name = 'AbortError';
            reject(err);
          });
        });
      });

      const file = new File(['a,b\n1,2'], 'test.csv');
      const uploadPromise = uploadFinancialFile({
        file,
        documentType: 'general_ledger',
        signal: controller.signal,
      });

      controller.abort();

      await expect(uploadPromise).rejects.toMatchObject({ name: 'AbortError' });
    });

    it('maps HTTP 400 error to sanitized financial message', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: async () => 'Invalid source system for organization',
      });

      const file = new File(['a,b'], 'test.csv');
      await expect(
        uploadFinancialFile({ file, documentType: 'general_ledger' })
      ).rejects.toThrow(/validation failed/i);
    });

    it('maps HTTP 413 error to size limit message', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 413,
        text: async () => 'Upload exceeds 25 MiB',
      });

      const file = new File(['a,b'], 'test.csv');
      await expect(
        uploadFinancialFile({ file, documentType: 'general_ledger' })
      ).rejects.toThrow(/exceeds the 25 MiB/i);
    });

    it('maps HTTP 422 error to options format message', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        text: async () => 'X-Import-Options must be a JSON object',
      });

      const file = new File(['a,b'], 'test.csv');
      await expect(
        uploadFinancialFile({ file, documentType: 'general_ledger' })
      ).rejects.toThrow(/invalid import options/i);
    });

    it('maps HTTP 500 error to safe generic server message', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => 'Internal Server Error with stack trace: at sqlalchemy.engine.execute',
      });

      const file = new File(['a,b'], 'test.csv');
      await expect(
        uploadFinancialFile({ file, documentType: 'general_ledger' })
      ).rejects.toThrow(/server could not complete the import/i);
    });
  });
});
