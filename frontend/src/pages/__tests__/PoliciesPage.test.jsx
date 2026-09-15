import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import PoliciesPage from '../PoliciesPage';

describe('PoliciesPage', () => {
  const originalFetch = global.fetch;

  const mockDocumentsPayload = {
    total_documents: 2,
    total_chunks: 5,
    documents: [
      {
        doc_id: 'acc_001_bank_reconciliation',
        policy_id: 'ACC-001',
        policy_name: 'Bank Reconciliation Standard',
        title: 'Bank Reconciliation Standard',
        filename: 'ACC-001_bank_reconciliation.md',
        category: 'BANK_RECONCILIATION',
        chunks_count: 3,
        chunk_count: 3,
        created_at: '2026-01-01T10:00:00Z',
      },
      {
        doc_id: 'acc_002_accrual_policy',
        policy_id: 'ACC-002',
        policy_name: 'Accrual & Expense Matching',
        title: 'Accrual & Expense Matching',
        filename: 'ACC-002_accrual_policy.md',
        category: 'ACCRUAL',
        chunks_count: 2,
        chunk_count: 2,
        created_at: '2026-01-01T10:05:00Z',
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/rag/documents')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDocumentsPayload,
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('renders distinct indexed policy documents and correct document count when backend returns wrapped object', async () => {
    render(<PoliciesPage />);

    // Check loading indicator first
    expect(screen.getByText(/Loading policy documents/i)).toBeInTheDocument();

    // Wait for documents to load
    await waitFor(() => {
      expect(screen.getByText(/Indexed Policy & SOP Documents \(2\)/i)).toBeInTheDocument();
    });

    // Check that ACC-001 and ACC-002 appear in table
    expect(screen.getByText('Bank Reconciliation Standard')).toBeInTheDocument();
    expect(screen.getByText('Accrual & Expense Matching')).toBeInTheDocument();
    expect(screen.getByText('ACC-001_bank_reconciliation.md')).toBeInTheDocument();
    expect(screen.getByText('ACC-002_accrual_policy.md')).toBeInTheDocument();
  });

  it('handles direct array response compatibility', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/rag/documents')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDocumentsPayload.documents,
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Indexed Policy & SOP Documents \(2\)/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Bank Reconciliation Standard')).toBeInTheDocument();
  });

  it('renders empty state when collection has 0 documents', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/rag/documents')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ total_documents: 0, total_chunks: 0, documents: [] }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Indexed Policy & SOP Documents \(0\)/i)).toBeInTheDocument();
      expect(screen.getByText(/No policy documents indexed in ChromaDB yet/i)).toBeInTheDocument();
    });
  });

  it('handles malformed document arrays safely', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/rag/documents')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [null, {}, { doc_id: 'partial-doc' }],
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Indexed Policy & SOP Documents \(2\)/i)).toBeInTheDocument();
    });
    expect(screen.getByText('partial-doc')).toBeInTheDocument();
  });

  it('displays error message gracefully when API fails', async () => {
    global.fetch = vi.fn().mockImplementation((url) => {
      if (String(url).includes('/rag/documents')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: 'Internal Vector Store Error',
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
    });

    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Failed to fetch policy documents/i)).toBeInTheDocument();
    });
  });
});
