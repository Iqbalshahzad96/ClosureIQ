import React from 'react';
import { render, screen, waitFor, fireEvent, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import FinancialUploadPage from '../FinancialUploadPage';
import App from '../../App';
import { MAX_FILE_BYTES } from '../../services/uploadService';

describe('FinancialUploadPage (Required 16 Offline Deterministic Tests)', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const setupMockFetch = (mockResponse, status = 200, ok = true) => {
    global.fetch = vi.fn().mockImplementation((url, init) => {
      const urlStr = String(url);
      if (urlStr.includes('/financial-data/summary')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            all_time_reconciliation: {
              total_records: 10,
              reconciled_records: 8,
              unreconciled_records: 2,
              reconciled_percentage: 80.0,
              bank_total: 5,
              bank_reconciled: 4,
              gl_total: 5,
              gl_reconciled: 4,
            },
            data_types: {
              bank_statements: { total_count: 5, reconciled_count: 4, unreconciled_count: 1, latest_import_date: '2026-03-15T10:00:00Z', has_reconciliation: true },
              general_ledger: { total_count: 5, reconciled_count: 4, unreconciled_count: 1, latest_import_date: '2026-03-15T10:00:00Z', has_reconciliation: true },
              trial_balance: { total_count: 2, reconciled_count: null, unreconciled_count: null, latest_import_date: '2026-03-15T10:00:00Z', has_reconciliation: false },
              ap_invoices: { total_count: 3, reconciled_count: 2, unreconciled_count: 1, latest_import_date: '2026-03-15T10:00:00Z', has_reconciliation: true },
              fixed_assets: { total_count: 1, reconciled_count: 1, unreconciled_count: 0, latest_import_date: '2026-03-15T10:00:00Z', has_reconciliation: true },
              accruals: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null, has_reconciliation: false },
              depreciation: { total_count: 1, reconciled_count: null, unreconciled_count: null, latest_import_date: '2026-03-15T10:00:00Z', has_reconciliation: false, is_derived: true },
            },
          }),
        });
      }
      if (urlStr.includes('/financial-data/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            data_type: 'bank_statements',
            display_name: 'Bank Statements',
            columns: [
              { key: 'booking_date', label: 'Date' },
              { key: 'description', label: 'Description' },
              { key: 'amount', label: 'Amount', is_currency: true },
              { key: 'status', label: 'Status', is_status: true },
            ],
            records: [
              { id: '1', booking_date: '2026-03-15', description: 'Sample Tx', amount: 1500.0, status: 'Reconciled' },
            ],
          }),
        });
      }
      return Promise.resolve({
        ok,
        status,
        text: async () => (typeof mockResponse === 'string' ? mockResponse : JSON.stringify(mockResponse)),
        json: async () => (typeof mockResponse === 'object' ? mockResponse : JSON.parse(mockResponse)),
      });
    });
  };

  // 1. Valid CSV/XLS/XLSX selection
  it('1. accepts valid CSV, XLS, and XLSX file selections without client-side error', async () => {
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    const fileInput = screen.getByTestId('file-upload-input');

    // Test CSV
    const csvFile = new File(['a,b\n1,2'], 'ledger.csv', { type: 'text/csv' });
    fireEvent.change(fileInput, { target: { files: [csvFile] } });
    expect(screen.getByText('ledger.csv')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // Test XLSX
    const xlsxFile = new File(['content'], 'statement.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    fireEvent.change(fileInput, { target: { files: [xlsxFile] } });
    expect(screen.getByText('statement.xlsx')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // Test XLS
    const xlsFile = new File(['content'], 'trial_balance.xls', { type: 'application/vnd.ms-excel' });
    fireEvent.change(fileInput, { target: { files: [xlsFile] } });
    expect(screen.getByText('trial_balance.xls')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  // 2. Drag/drop and keyboard-accessible file selection
  it('2. supports drag/drop and keyboard-accessible file selection', async () => {
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    const dropZone = screen.getByRole('button', {
      name: /upload financial document file/i,
    });
    expect(dropZone).toBeInTheDocument();
    expect(dropZone).toHaveAttribute('tabindex', '0');

    // Drag over & drop
    const droppedFile = new File(['col1,col2\n10,20'], 'dropped_ledger.csv', { type: 'text/csv' });
    fireEvent.dragEnter(dropZone);
    fireEvent.dragOver(dropZone);
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [droppedFile] },
    });

    expect(screen.getByText('dropped_ledger.csv')).toBeInTheDocument();

    // Keyboard accessibility: pressing Enter or Space activates the file picker
    const fileInput = screen.getByTestId('file-upload-input');
    const clickSpy = vi.spyOn(fileInput, 'click');

    fireEvent.keyDown(dropZone, { key: 'Enter', code: 'Enter' });
    expect(clickSpy).toHaveBeenCalled();

    clickSpy.mockClear();
    fireEvent.keyDown(dropZone, { key: ' ', code: 'Space' });
    expect(clickSpy).toHaveBeenCalled();
  });

  // 3. Unsupported, empty and over-25-MiB rejection
  it('3. rejects unsupported extensions, empty files, and over-25-MiB files before sending', async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy;

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);
    const fileInput = screen.getByTestId('file-upload-input');

    // A: Unsupported extension (.pdf)
    const pdfFile = new File(['pdf-data'], 'report.pdf', { type: 'application/pdf' });
    fireEvent.change(fileInput, { target: { files: [pdfFile] } });
    expect(screen.getByRole('alert')).toHaveTextContent(/unsupported file format/i);
    expect(screen.getByTestId('upload-and-validate-btn')).toBeDisabled();

    // B: Empty file (0 bytes)
    const emptyFile = new File([], 'empty.csv', { type: 'text/csv' });
    fireEvent.change(fileInput, { target: { files: [emptyFile] } });
    expect(screen.getByRole('alert')).toHaveTextContent(/file is empty \(0 bytes\)/i);
    expect(screen.getByTestId('upload-and-validate-btn')).toBeDisabled();

    // C: Over 25 MiB
    const largeFile = {
      name: 'large.xlsx',
      size: MAX_FILE_BYTES + 1024,
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    };
    fireEvent.change(fileInput, { target: { files: [largeFile] } });
    expect(screen.getByRole('alert')).toHaveTextContent(/exceeds the 25 MiB upload limit/i);
    expect(screen.getByTestId('upload-and-validate-btn')).toBeDisabled();

    // Verify upload fetch was never called
    const uploadCalls = fetchSpy.mock.calls.filter(([url]) => String(url).includes('/imports/'));
    expect(uploadCalls.length).toBe(0);
  });

  // 4. Exact raw-body request—not FormData
  it('4. sends exact raw file bytes as body, NOT FormData and NOT JSON', async () => {
    let capturedBody = null;
    let capturedContentType = null;

    global.fetch = vi.fn().mockImplementation((url, init) => {
      if (String(url).includes('/imports/')) {
        capturedBody = init?.body;
        capturedContentType = init?.headers?.['Content-Type'];
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'COMPLETED',
          valid_rows: 5,
          total_rows: 5,
        }),
      });
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    const validCsv = new File(['id,amount\n1,100'], 'transactions.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [validCsv] } });

    const uploadBtn = screen.getByTestId('upload-and-validate-btn');
    await act(async () => {
      fireEvent.click(uploadBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Completed Successfully/i)).toBeInTheDocument();
    });

    // Verify body is the exact File instance directly
    expect(capturedBody).toBe(validCsv);
    expect(capturedBody instanceof FormData).toBe(false);
    expect(typeof capturedBody).not.toBe('string');
    expect(capturedContentType).toBe('text/csv');
  });

  // 5. Correct internal adapter and import-options mapping
  it('5. maps document type to correct internal adapter and generates X-Import-Options from finance fields', async () => {
    let capturedUrl = '';
    let capturedImportOptions = null;

    global.fetch = vi.fn().mockImplementation((url, init) => {
      if (String(url).includes('/imports/')) {
        capturedUrl = String(url);
        capturedImportOptions = JSON.parse(init?.headers?.['X-Import-Options'] || '{}');
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ status: 'COMPLETED', valid_rows: 10, total_rows: 10 }),
      });
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    // Select Bank Statement
    const bankDocOption = screen.getByRole('radio', { name: /Bank Statement/i });
    fireEvent.click(bankDocOption);

    // Enter Bank Account
    const bankAccInput = screen.getByLabelText(/Bank Account/i);
    fireEvent.change(bankAccInput, { target: { value: 'Operating-Account-101' } });

    // Select Currency USD
    const currencySelect = screen.getByLabelText(/Currency/i);
    fireEvent.change(currencySelect, { target: { value: 'USD' } });

    // Change Period
    const periodInput = screen.getByLabelText(/Financial Period/i);
    fireEvent.change(periodInput, { target: { value: '2026-02' } });

    // Select File
    const file = new File(['tx'], 'bank_feb.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Completed Successfully/i)).toBeInTheDocument();
    });

    // Check adapter_key in query params
    const urlObj = new URL(capturedUrl);
    expect(urlObj.searchParams.get('adapter_key')).toBe('generic_bank');
    expect(urlObj.searchParams.get('filename')).toBe('bank_feb.csv');

    // Check X-Import-Options header
    expect(capturedImportOptions).toEqual({
      currency_code: 'USD',
      fiscal_period: '2026-02',
      bank_account_id: 'Operating-Account-101',
    });
  });

  // 6. Normal upload omits source_system_id
  it('6. normal upload completely omits source_system_id from URL query parameters', async () => {
    let capturedUrl = '';
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/imports/')) {
        capturedUrl = String(url);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ status: 'COMPLETED', valid_rows: 1 }),
      });
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    const file = new File(['data'], 'ledger.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Completed Successfully/i)).toBeInTheDocument();
    });

    const urlObj = new URL(capturedUrl);
    expect(urlObj.searchParams.has('source_system_id')).toBe(false);
    expect(urlObj.searchParams.has('organization_id')).toBe(false);
  });

  // 7. Support backend statuses: COMPLETED, PARTIAL, QUARANTINED, FAILED, and DUPLICATE
  it('7. handles all backend statuses (COMPLETED, PARTIAL, QUARANTINED, FAILED, DUPLICATE) with appropriate states', async () => {
    const statuses = [
      { status: 'COMPLETED', title: /Import Completed Successfully/i, usable: true },
      { status: 'PARTIAL', title: /Import Partially Completed/i, usable: true },
      { status: 'QUARANTINED', title: /All Records Quarantined/i, usable: false },
      { status: 'FAILED', title: /Document Import Failed/i, usable: false },
      { status: 'DUPLICATE', title: /Duplicate File Detected/i, usable: false },
    ];

    for (const testCase of statuses) {
      setupMockFetch({
        status: testCase.status,
        total_rows: 20,
        valid_rows: testCase.usable ? 15 : 0,
        quarantined_rows: testCase.status === 'QUARANTINED' ? 20 : 0,
        duplicate_files: testCase.status === 'DUPLICATE' ? 1 : 0,
      });

      const { unmount } = render(<FinancialUploadPage setActiveTab={vi.fn()} />);
      const file = new File(['data'], 'test.csv', { type: 'text/csv' });
      fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

      await act(async () => {
        fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
      });

      await waitFor(() => {
        expect(screen.getByText(testCase.title)).toBeInTheDocument();
      });

      if (testCase.usable) {
        expect(screen.getByTestId('continue-to-reconciliation-btn')).toBeInTheDocument();
      } else {
        expect(screen.queryByTestId('continue-to-reconciliation-btn')).not.toBeInTheDocument();
      }

      unmount();
    }
  });

  // 8. Result counts and labels
  it('8. displays correct result counts with finance-friendly labels and secondary details', async () => {
    setupMockFetch({
      status: 'PARTIAL',
      batch_id: 'batch-ref-888',
      total_rows: 50,
      valid_rows: 40,
      quarantined_rows: 10,
      warning_rows: 4,
      duplicate_files: 0,
      technical_duplicate_rows: 2,
      business_duplicate_rows: 1,
      skipped_rows: 3,
      warnings: [{ code: 'WARN_DUAL_POSTING', message: 'Dual-sided posting detected on voucher 44' }],
      errors: [{ code: 'ERR_INVALID_DATE', message: 'Invalid booking date format' }],
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);
    const file = new File(['data'], 'test.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Partially Completed/i)).toBeInTheDocument();
    });

    // Primary KPI cards
    const totalCard = screen.getByTestId('metric-total-records');
    expect(within(totalCard).getByText('Total records')).toBeInTheDocument();
    expect(within(totalCard).getByText('50')).toBeInTheDocument();

    const validCard = screen.getByTestId('metric-successfully-added');
    expect(within(validCard).getByText('Successfully added')).toBeInTheDocument();
    expect(within(validCard).getByText('40')).toBeInTheDocument();

    const rejCard = screen.getByTestId('metric-rejected-records');
    expect(within(rejCard).getByText('Rejected records')).toBeInTheDocument();
    expect(within(rejCard).getByText('10')).toBeInTheDocument();

    const warnCard = screen.getByTestId('metric-records-with-warnings');
    expect(within(warnCard).getByText('Records with warnings')).toBeInTheDocument();
    expect(within(warnCard).getByText('4')).toBeInTheDocument();

    // Secondary details
    const resultsSummary = screen.getByTestId('import-results-summary');
    expect(within(resultsSummary).getByText(/Repeated rows:/i)).toBeInTheDocument();
    expect(within(resultsSummary).getByText('2')).toBeInTheDocument();
    expect(within(resultsSummary).getByText(/Duplicate transactions:/i)).toBeInTheDocument();
    expect(within(resultsSummary).getByText('1')).toBeInTheDocument();
    expect(within(resultsSummary).getByText(/Skipped records:/i)).toBeInTheDocument();
    expect(within(resultsSummary).getByText('3')).toBeInTheDocument();
    expect(within(resultsSummary).getByText(/Import reference:/i)).toBeInTheDocument();
    expect(within(resultsSummary).getByText('batch-ref-888')).toBeInTheDocument();

    // Expandable details
    expect(within(resultsSummary).getByTestId('rejection-reasons-details')).toBeInTheDocument();
    expect(within(resultsSummary).getByText(/Invalid booking date format/i)).toBeInTheDocument();
    expect(within(resultsSummary).getByTestId('warning-records-details')).toBeInTheDocument();
    expect(within(resultsSummary).getByText(/Dual-sided posting detected/i)).toBeInTheDocument();
  });

  // 9. Malformed/partial/non-finite response
  it('9. defensively handles malformed, partial, or non-finite backend responses without crashing or showing NaN', async () => {
    setupMockFetch({
      status: null,
      total_rows: 'bad-number',
      valid_rows: -10,
      quarantined_rows: NaN,
      warning_rows: Infinity,
      batch_id: null,
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);
    const file = new File(['data'], 'test.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Document Import Failed/i)).toBeInTheDocument();
    });

    expect(screen.queryByText(/\bNaN\b/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bInfinity\b/)).not.toBeInTheDocument();
  });

  // 10. HTTP 400, 413, 422 and 500 with sanitized UI errors
  it('10. handles HTTP 400, 413, 422, and 500 with sanitized UI error messages', async () => {
    const errorCases = [
      { status: 400, response: 'Invalid date on row 3', expected: /File validation failed: Invalid date on row 3/i },
      { status: 413, response: 'Upload exceeds 25 MiB', expected: /File exceeds the 25 MiB upload limit/i },
      { status: 422, response: 'X-Import-Options must be a JSON object', expected: /Invalid import options provided/i },
      { status: 500, response: 'Traceback: internal error in database', expected: /The server could not complete the import/i },
    ];

    for (const ec of errorCases) {
      setupMockFetch(ec.response, ec.status, false);

      const { unmount } = render(<FinancialUploadPage setActiveTab={vi.fn()} />);
      const file = new File(['test'], 'data.csv', { type: 'text/csv' });
      fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

      await act(async () => {
        fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
      });

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent(ec.expected);
      });

      // No raw internal traces leaked
      expect(screen.queryByText(/Traceback/i)).not.toBeInTheDocument();

      unmount();
    }
  });

  // 11. Double-submit prevention
  it('11. prevents double submissions while an upload is currently in flight', async () => {
    let uploadCallCount = 0;
    let finishUpload;
    const uploadPromise = new Promise((resolve) => {
      finishUpload = resolve;
    });

    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/imports/')) {
        uploadCallCount++;
        return uploadPromise.then(() => ({
          ok: true,
          status: 200,
          json: async () => ({ status: 'COMPLETED', valid_rows: 5 }),
        }));
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ all_time_reconciliation: { total_records: 0 }, data_types: {} }),
      });
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);
    const file = new File(['data'], 'test.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    const uploadBtn = screen.getByTestId('upload-and-validate-btn');

    // Click upload once
    await act(async () => {
      fireEvent.click(uploadBtn);
    });

    // Button should be gone or disabled, processing state displayed
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText(/Processing Financial Document/i)).toBeInTheDocument();

    // Repeated clicks should be guarded
    expect(uploadCallCount).toBe(1);

    // Complete upload
    await act(async () => {
      finishUpload();
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Completed Successfully/i)).toBeInTheDocument();
    });
    expect(uploadCallCount).toBe(1);
  });

  // 12. Cancellation, unmount and stale-response protection
  it('12. handles cancellation, unmount, and ignores stale overlapping responses', async () => {
    // Part A: Cancellation via Cancel button
    let abortListenerCalled = false;
    global.fetch = vi.fn().mockImplementation((url, init) => {
      init.signal.addEventListener('abort', () => {
        abortListenerCalled = true;
      });
      return new Promise(() => {}); // Never finishes
    });

    const { unmount } = render(<FinancialUploadPage setActiveTab={vi.fn()} />);
    const file = new File(['data'], 'test.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    expect(screen.getByText(/Cancel Upload/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Cancel Upload/i));

    expect(abortListenerCalled).toBe(true);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    // Part B: Unmount aborts in-flight request
    let unmountAborted = false;
    global.fetch = vi.fn().mockImplementation((url, init) => {
      init.signal.addEventListener('abort', () => {
        unmountAborted = true;
      });
      return new Promise(() => {});
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });
    unmount();
    expect(unmountAborted).toBe(true);
  });

  // 13. Retry preserves user input
  it('13. preserves user inputs and selected file after a recoverable upload error', async () => {
    let failFirst = true;
    global.fetch = vi.fn().mockImplementation(() => {
      if (failFirst) {
        return Promise.resolve({
          ok: false,
          status: 400,
          text: async () => 'Missing required column',
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ status: 'COMPLETED', valid_rows: 10 }),
      });
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    // Custom period and currency
    fireEvent.change(screen.getByLabelText(/Financial Period/i), { target: { value: '2026-Q3' } });
    fireEvent.change(screen.getByLabelText(/Currency/i), { target: { value: 'EUR' } });

    const file = new File(['data'], 'my_ledger.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    // Submit and fail
    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/File validation failed: Missing required column/i);
    });

    // Form inputs and selected file remain preserved
    expect(screen.getByLabelText(/Financial Period/i)).toHaveValue('2026-Q3');
    expect(screen.getByLabelText(/Currency/i)).toHaveValue('EUR');
    expect(screen.getByText('my_ledger.csv')).toBeInTheDocument();

    // Retry with preserved file
    failFirst = false;
    const retryBtn = screen.getByRole('button', { name: /retry/i });
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Completed Successfully/i)).toBeInTheDocument();
    });
  });

  // 14. Clear/another-upload resets safely
  it('14. safely clears input file and resets upload state', async () => {
    setupMockFetch({ status: 'COMPLETED', valid_rows: 15 });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);
    const file = new File(['data'], 'test.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    // Test Clear before upload
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(screen.queryByText('test.csv')).not.toBeInTheDocument();

    // Re-select and upload
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Import Completed Successfully/i)).toBeInTheDocument();
    });

    // Upload Another Document resets view
    fireEvent.click(screen.getByRole('button', { name: /upload another document/i }));
    expect(screen.queryByText(/Import Completed Successfully/i)).not.toBeInTheDocument();
    expect(screen.getByTestId('upload-and-validate-btn')).toBeInTheDocument();
  });

  // 15. Sidebar navigation
  it('15. allows opening Financial Data from the sidebar and continuing to Reconciliation', async () => {
    setupMockFetch({ status: 'COMPLETED', valid_rows: 25, total_rows: 25 });

    render(<App />);

    // Click Financial Data in Sidebar
    const uploadSidebarBtn = screen.getByRole('button', { name: /Financial Data/i });
    expect(uploadSidebarBtn).toBeInTheDocument();
    fireEvent.click(uploadSidebarBtn);

    // Page renders with Financial Data title
    expect(screen.getByRole('heading', { name: /^Financial Data$/i })).toBeInTheDocument();

    // Complete an upload
    const file = new File(['data'], 'test.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId('upload-and-validate-btn'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('continue-to-reconciliation-btn')).toBeInTheDocument();
    });

    // Click Continue to Reconciliation -> navigation switches to Reconciliation page
    fireEvent.click(screen.getByTestId('continue-to-reconciliation-btn'));

    await waitFor(() => {
      expect(screen.getByText(/GL-to-Bank Reconciliation/i)).toBeInTheDocument();
    });
  });

  // 16. No technical labels, JSON editor or fabricated results visible
  it('16. ensures no technical fields, JSON editors, or fabricated results are visible to users', async () => {
    setupMockFetch({ file_id: 'staged-1', detected_context: { documentType: 'general_ledger' } });
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    // Developer / technical terms must NOT be visible in the user interface
    expect(screen.queryByText('source_system_id')).not.toBeInTheDocument();
    expect(screen.queryByText('adapter_key')).not.toBeInTheDocument();
    expect(screen.queryByText('organization_id')).not.toBeInTheDocument();
    expect(screen.queryByText(/JSON/i)).not.toBeInTheDocument();
    expect(screen.queryByText('enquest_ledger')).not.toBeInTheDocument();
    expect(screen.queryByText('generic_bank')).not.toBeInTheDocument();
    expect(screen.queryByText(/batch configuration/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /json/i })).not.toBeInTheDocument();

    // Stage a file to check Document Type selection options
    const file = new File(['test,data'], 'ledger.csv', { type: 'text/csv' });
    fireEvent.change(screen.getByTestId('file-upload-input'), { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByRole('radio', { name: /General Ledger/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /Bank Statement/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /Trial Balance/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /Accounts Payable Invoices/i })).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: /Fixed Asset Register/i })).toBeInTheDocument();
    });
  });

  // 17. Section headers render correctly
  it('17. renders both Financial File Upload and Financial Data in Database section headers', async () => {
    setupMockFetch({});
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    expect(screen.getByRole('heading', { name: /^Financial Data$/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Financial File Upload/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Financial Data in Database/i })).toBeInTheDocument();
  });

  // 18. All-time reconciliation percentage metric card
  it('18. displays All-Time Reconciled Percentage metric across GL and Bank records', async () => {
    setupMockFetch({});
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('all-time-reconciliation-card')).toBeInTheDocument();
      expect(screen.getByText(/All-Time Reconciled Percentage/i)).toBeInTheDocument();
      expect(screen.getByTestId('all-time-reconciled-percentage-value')).toHaveTextContent('80%');
      expect(screen.getByTestId('all-time-total-records')).toHaveTextContent('10');
      expect(screen.getByTestId('all-time-reconciled-records')).toHaveTextContent('8');
      expect(screen.getByTestId('all-time-unreconciled-records')).toHaveTextContent('2');
    });
  });

  // 19. Renders all 7 financial data cards
  it('19. renders separate cards for all 7 financial data types with counts and dates', async () => {
    setupMockFetch({});
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('data-card-bank_statements')).toBeInTheDocument();
      expect(screen.getByTestId('data-card-general_ledger')).toBeInTheDocument();
      expect(screen.getByTestId('data-card-trial_balance')).toBeInTheDocument();
      expect(screen.getByTestId('data-card-ap_invoices')).toBeInTheDocument();
      expect(screen.getByTestId('data-card-fixed_assets')).toBeInTheDocument();
      expect(screen.getByTestId('data-card-accruals')).toBeInTheDocument();
      expect(screen.getByTestId('data-card-depreciation')).toBeInTheDocument();

      expect(screen.getByTestId('card-count-bank_statements')).toHaveTextContent('5');
      expect(screen.getByTestId('card-count-general_ledger')).toHaveTextContent('5');
      expect(screen.getByTestId('card-count-trial_balance')).toHaveTextContent('2');
      expect(screen.getByTestId('card-count-ap_invoices')).toHaveTextContent('3');
      expect(screen.getByTestId('card-count-fixed_assets')).toHaveTextContent('1');
    });
  });

  // 20. Empty database state handling
  it('20. displays empty state notice when database has no records', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      const urlStr = String(url);
      if (urlStr.includes('/financial-data/summary')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            all_time_reconciliation: {
              total_records: 0,
              reconciled_records: 0,
              unreconciled_records: 0,
              reconciled_percentage: 0.0,
              bank_total: 0,
              bank_reconciled: 0,
              gl_total: 0,
              gl_reconciled: 0,
            },
            data_types: {
              bank_statements: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null },
              general_ledger: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null },
              trial_balance: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null },
              ap_invoices: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null },
              fixed_assets: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null },
              accruals: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null },
              depreciation: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null, is_derived: true },
            },
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ data_type: 'bank_statements', columns: [], records: [] }),
      });
    });

    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('empty-database-notice')).toBeInTheDocument();
      expect(screen.getByText(/Database is currently empty/i)).toBeInTheDocument();
    });
  });

  // 21. Preview table interaction
  it('21. displays live preview table when selecting data type card', async () => {
    setupMockFetch({});
    render(<FinancialUploadPage setActiveTab={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('preview-table')).toBeInTheDocument();
      expect(screen.getByText('Sample Tx')).toBeInTheDocument();
    });
  });
});

