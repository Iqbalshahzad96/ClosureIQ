import React from 'react';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ReconciliationPage from '../ReconciliationPage';
import * as service from '../../services/reconciliationService';

vi.mock('../../services/reconciliationService', () => ({
  runWorkflow: vi.fn(), submitApprovalDecision: vi.fn(),
  fetchReconciliationPreview: vi.fn(), fetchPeriods: vi.fn(),
  fetchUnresolvedMappings: vi.fn(), resolveMapping: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  service.fetchPeriods.mockResolvedValue({ periods: ['2026-01', '2025-12'] });
  service.fetchUnresolvedMappings.mockResolvedValue({ unresolved: [] });
  service.fetchReconciliationPreview.mockResolvedValue({
    detected_accounts: [{ account_code: '1010' }], total_gl_transactions: 1, total_bank_transactions: 1,
  });
  service.runWorkflow.mockResolvedValue({ status: 'clean_close' });
});
afterEach(cleanup);

it.each(['reconciliation', 'accrual', 'depreciation', 'ap_review'])(
  '%s runs with only the workflow and selected period', async (workflowType) => {
    render(<ReconciliationPage />);
    await waitFor(() => expect(screen.getByLabelText('Period').value).toBe('2026-01'));
    fireEvent.change(screen.getByLabelText('Workflow Type'), { target: { value: workflowType } });
    expect(screen.queryByText('Account Code')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Period'), { target: { value: '2025-12' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run Workflow' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run Workflow' }));
    await waitFor(() => expect(service.runWorkflow).toHaveBeenCalledWith({ workflowType, period: '2025-12' }));
  },
);
