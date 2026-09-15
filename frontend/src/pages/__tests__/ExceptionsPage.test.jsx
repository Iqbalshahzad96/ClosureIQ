import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import ExceptionsPage from '../ExceptionsPage';

describe('ExceptionsPage', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const mockDirectListExceptions = [
    {
      id: 'exc-recon-001',
      period: '2025-12',
      category: 'RECONCILIATION',
      severity: 'HIGH',
      amount_variance: 15000.0,
      description: 'Uncredited cash deposit in GL not found on bank statement',
      status: 'OPEN',
      created_at: '2025-12-20T10:00:00Z',
    },
    {
      id: 'exc-recon-002',
      period: '2025-12',
      category: 'RECONCILIATION',
      severity: 'MEDIUM',
      amount_variance: -2500.0,
      description: 'Monthly account fee on bank statement not in GL',
      status: 'OPEN',
      created_at: '2025-12-22T08:00:00Z',
    },
    {
      id: 'exc-accrual-003',
      period: '2026-Q1',
      category: 'ACCRUAL',
      severity: 'LOW',
      amount_variance: 500.0,
      description: 'Minor software license variance against baseline',
      status: 'RESOLVED',
      created_at: '2026-01-15T12:00:00Z',
    },
  ];

  it('renders non-empty direct API array and does not show "No Exceptions Found"', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/exceptions/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDirectListExceptions,
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<ExceptionsPage />);

    // Wait for records to appear
    await waitFor(() => {
      expect(screen.getByText('Uncredited cash deposit in GL not found on bank statement')).toBeInTheDocument();
    });

    expect(screen.queryByText('No Exceptions Found')).not.toBeInTheDocument();
    expect(screen.getByText('Monthly account fee on bank statement not in GL')).toBeInTheDocument();
    expect(screen.getByText('High Severity')).toBeInTheDocument();
    expect(screen.getByText('Medium Severity')).toBeInTheDocument();
  });

  it('renders empty state when API returns empty array', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/exceptions/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<ExceptionsPage />);

    await waitFor(() => {
      expect(screen.getByText('No Exceptions Found')).toBeInTheDocument();
    });
  });

  it('safely handles partial and malformed exception records without crashing', async () => {
    const malformedData = [
      null,
      {},
      { id: 'malformed-1', description: null, amount_variance: 'invalid_num' },
      { id: 'valid-partial', period: '2025-12', category: 'ACCRUAL', description: 'Valid partial item' },
    ];

    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/exceptions/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => malformedData,
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<ExceptionsPage />);

    await waitFor(() => {
      expect(screen.getByText('Valid partial item')).toBeInTheDocument();
    });
  });

  it('sanitizes raw backend/database error messages', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/exceptions/')) {
        return Promise.reject(new Error('sqlite3.OperationalError: no such table: exception_records at file "app/db.py" line 42'));
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<ExceptionsPage />);

    await waitFor(() => {
      expect(
        screen.getByText('Unable to load financial exceptions due to a server error. Please try again later.')
      ).toBeInTheDocument();
    });

    // Ensure raw SQL / file info is NEVER displayed
    expect(screen.queryByText(/sqlite3\.OperationalError/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/app\/db\.py/i)).not.toBeInTheDocument();
  });

  it('retains run_id and period context on workflow exception items', async () => {
    const itemsWithRunContext = [
      {
        id: 'exc-with-run',
        period: '2025-12',
        run_id: 'run-alpha-12345678',
        category: 'RECONCILIATION',
        severity: 'HIGH',
        amount_variance: 5000.0,
        description: 'Context retained item',
        status: 'OPEN',
      },
    ];

    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/exceptions/')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => itemsWithRunContext,
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<ExceptionsPage />);

    await waitFor(() => {
      expect(screen.getByText('Context retained item')).toBeInTheDocument();
      expect(screen.getByText(/2025-12/)).toBeInTheDocument();
      expect(screen.getByText(/run-alph/)).toBeInTheDocument();
    });
  });
});
