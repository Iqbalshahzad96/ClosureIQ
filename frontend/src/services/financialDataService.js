/**
 * Financial Data Service
 *
 * Provides API client methods for fetching financial database summaries,
 * all-time reconciliation metrics, and dataset-specific preview records.
 */

import { apiClient } from './api';

export const FINANCIAL_DATA_TYPES = {
  BANK_STATEMENTS: {
    id: 'bank_statements',
    label: 'Bank Statements',
    description: 'Bank transactions and cash ledger feeds',
    hasReconciliation: true,
  },
  GENERAL_LEDGER: {
    id: 'general_ledger',
    label: 'General Ledger',
    description: 'Journal entries and debit/credit postings',
    hasReconciliation: true,
  },
  TRIAL_BALANCE: {
    id: 'trial_balance',
    label: 'Trial Balance',
    description: 'Period-end trial balance control accounts',
    hasReconciliation: false,
  },
  AP_INVOICES: {
    id: 'ap_invoices',
    label: 'AP Invoices',
    description: 'Accounts payable vendor invoices and settlements',
    hasReconciliation: true,
    reconciledLabel: 'Paid',
    unreconciledLabel: 'Open / Pending',
  },
  FIXED_ASSETS: {
    id: 'fixed_assets',
    label: 'Fixed Assets',
    description: 'Capital asset register, acquisition costs, and book values',
    hasReconciliation: true,
    reconciledLabel: 'Active',
    unreconciledLabel: 'Disposed / Inactive',
  },
  ACCRUALS: {
    id: 'accruals',
    label: 'Accruals',
    description: 'Expense and revenue period accruals',
    hasReconciliation: false,
  },
  DEPRECIATION: {
    id: 'depreciation',
    label: 'Depreciation',
    description: 'Straight-line schedules and accumulated depreciation',
    hasReconciliation: false,
    isDerived: true,
  },
};

const DEFAULT_SUMMARY = {
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
    bank_statements: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null, has_reconciliation: true },
    general_ledger: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null, has_reconciliation: true },
    trial_balance: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null, has_reconciliation: false },
    ap_invoices: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null, has_reconciliation: true },
    fixed_assets: { total_count: 0, reconciled_count: 0, unreconciled_count: 0, latest_import_date: null, has_reconciliation: true },
    accruals: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null, has_reconciliation: false },
    depreciation: { total_count: 0, reconciled_count: null, unreconciled_count: null, latest_import_date: null, has_reconciliation: false, is_derived: true },
  },
};

/**
 * Fetch overall summary counts and all-time reconciliation rate.
 */
export async function fetchFinancialDataSummary(organizationId = 'default_org') {
  try {
    const data = await apiClient(`/financial-data/summary?organization_id=${encodeURIComponent(organizationId)}`);
    return data || DEFAULT_SUMMARY;
  } catch (error) {
    return DEFAULT_SUMMARY;
  }
}

/**
 * Fetch preview rows for a specific financial data type.
 */
export async function fetchFinancialDataPreview(dataType, limit = 20, organizationId = 'default_org') {
  try {
    const data = await apiClient(
      `/financial-data/${encodeURIComponent(dataType)}?limit=${limit}&organization_id=${encodeURIComponent(organizationId)}`
    );
    return data || { data_type: dataType, display_name: dataType, columns: [], records: [], count: 0 };
  } catch (error) {
    return { data_type: dataType, display_name: dataType, columns: [], records: [], count: 0 };
  }
}

/**
 * Format currency amount for finance UI displays.
 */
export function formatFinanceCurrency(val, currency = 'KES') {
  if (val === null || val === undefined || isNaN(Number(val))) return '-';
  const num = Number(val);
  const formatted = Math.abs(num).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const prefix = num < 0 ? `-${currency} ` : `${currency} `;
  return `${prefix}${formatted}`;
}

/**
 * Format ISO datetime string into finance-friendly date label.
 */
export function formatFinanceDate(isoString) {
  if (!isoString) return 'No imports yet';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return 'No imports yet';
    return d.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return 'No imports yet';
  }
}
