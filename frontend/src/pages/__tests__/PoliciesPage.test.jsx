import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
      if (String(url).includes('/rag/answer')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            answer: 'Accruals should be reviewed under ACC-002.',
            citations: [{ citation: '[ACC-002] Accrual & Expense Matching' }],
          }),
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
      expect(screen.getByText(/Current Policy Files \(2\)/i)).toBeInTheDocument();
    });

    // Check that ACC-001 and ACC-002 appear in table
    expect(screen.getByText('Bank Reconciliation Standard')).toBeInTheDocument();
    expect(screen.getByText('Accrual & Expense Matching')).toBeInTheDocument();
    expect(screen.getByText('ACC-001_bank_reconciliation.md')).toBeInTheDocument();
    expect(screen.getByText('ACC-002_accrual_policy.md')).toBeInTheDocument();
  });

  it('hides upload metadata controls while preserving default upload metadata and the table Category column', async () => {
    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Current Policy Files \(2\)/i)).toBeInTheDocument();
    });

    const uploadCard = screen.getByRole('heading', { name: /Upload Policy \/ SOP Document/i }).closest('.card');
    expect(within(uploadCard).queryByText(/^Category:$/i)).not.toBeInTheDocument();
    expect(within(uploadCard).queryByText(/^Policy Identifier:$/i)).not.toBeInTheDocument();
    expect(within(uploadCard).queryByPlaceholderText(/SOP-REV-01/i)).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Category' })).toBeInTheDocument();

    const initialFile = new File(['# Initial policy'], 'ACC-008_initial_policy.md', {
      type: 'text/markdown',
    });
    const policyFile = new File(['# Policy content'], 'ACC-009_close_checklist.md', {
      type: 'text/markdown',
    });
    fireEvent.change(uploadCard.querySelector('input[type="file"]'), {
      target: { files: [initialFile] },
    });
    fireEvent.change(uploadCard.querySelector('input[type="file"]'), {
      target: { files: [policyFile] },
    });
    fireEvent.click(within(uploadCard).getByRole('button', { name: /Ingest & Index Policy/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/rag/upload'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    const uploadCall = global.fetch.mock.calls.find(([url, options]) => (
      String(url).includes('/rag/upload') && options?.method === 'POST'
    ));
    expect(uploadCall[1].body.get('category')).toBe('RECONCILIATION');
    expect(uploadCall[1].body.get('policy_id')).toBe('ACC-009_close_checklist');
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
      expect(screen.getByText(/Current Policy Files \(2\)/i)).toBeInTheDocument();
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
      expect(screen.getByText(/Current Policy Files \(0\)/i)).toBeInTheDocument();
      expect(screen.getByText(/No policy files found/i)).toBeInTheDocument();
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
      expect(screen.getByText(/Current Policy Files \(2\)/i)).toBeInTheDocument();
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

  it('updates an existing policy file using the document id', async () => {
    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Current Policy Files \(2\)/i)).toBeInTheDocument();
    });

    const updatedFile = new File(['# Updated ACC-002 policy'], 'ACC-002_updated.md', {
      type: 'text/markdown',
    });
    const updateButtons = screen.getAllByRole('button', { name: /update/i });
    fireEvent.click(updateButtons[1]);

    const fileInputs = document.querySelectorAll('input[type="file"]');
    fireEvent.change(fileInputs[2], { target: { files: [updatedFile] } });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/rag/upload'),
        expect.objectContaining({ method: 'POST' })
      );
    });

    const uploadCall = global.fetch.mock.calls.find(([url, options]) => (
      String(url).includes('/rag/upload') && options?.method === 'POST'
    ));
    const formData = uploadCall[1].body;
    expect(formData.get('doc_id')).toBe('acc_002_accrual_policy');
    expect(formData.get('policy_id')).toBe('ACC-002');
    expect(formData.get('category')).toBe('ACCRUAL');
    expect(formData.get('file')).toBe(updatedFile);
  });

  it('shows generated policy answers and sends chat history on follow-up questions', async () => {
    render(<PoliciesPage />);

    await waitFor(() => {
      expect(screen.getByText(/Current Policy Files \(2\)/i)).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText(/What is the accrual threshold/i);
    fireEvent.change(input, { target: { value: 'How should accruals be reviewed?' } });
    fireEvent.click(screen.getByRole('button', { name: /ask policy question/i }));

    await waitFor(() => {
      expect(screen.getByText('Accruals should be reviewed under ACC-002.')).toBeInTheDocument();
    });
    expect(screen.queryByText(/^Citations$/i)).not.toBeInTheDocument();
    expect(screen.queryByText('[ACC-002] Accrual & Expense Matching')).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: 'What about follow up?' } });
    fireEvent.click(screen.getByRole('button', { name: /ask policy question/i }));

    await waitFor(() => {
      const answerCalls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/rag/answer'));
      expect(answerCalls).toHaveLength(2);
    });

    const secondAnswerCall = global.fetch.mock.calls.filter(([url]) => String(url).includes('/rag/answer'))[1];
    const payload = JSON.parse(secondAnswerCall[1].body);
    expect(payload.question).toBe('What about follow up?');
    expect(payload.top_k).toBe(2);
    expect(payload.history).toEqual([
      { role: 'user', content: 'How should accruals be reviewed?' },
      {
        role: 'assistant',
        content: 'Accruals should be reviewed under ACC-002.',
        citations: [{ citation: '[ACC-002] Accrual & Expense Matching' }],
      },
    ]);
  });
});
