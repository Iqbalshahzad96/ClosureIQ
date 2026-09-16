"""
Financial Data API Routes

Provides summary metrics, all-time reconciliation statistics,
and dataset preview records for:
- Bank Statements
- General Ledger
- Trial Balance
- AP Invoices
- Fixed Assets
- Accruals
- Depreciation (derived from Fixed Assets)
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import (
    Account,
    APInvoice,
    BankAccount,
    BankTransaction,
    FixedAsset,
    JournalEntry,
    JournalLine,
    TrialBalanceRecord,
)

router = APIRouter(prefix="/financial-data", tags=["Financial Data"])


def _serialize_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return default


@router.get("/summary", response_model=Dict[str, Any])
def get_financial_data_summary(
    organization_id: str = Query(default="default_org"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns record counts, reconciliation status, and latest import timestamps
    across all financial datasets and calculates all-time reconciliation rate.
    """
    # 1. Bank Statements
    bank_total = (
        db.query(func.count(BankTransaction.id))
        .join(BankAccount, BankTransaction.bank_account_id == BankAccount.id)
        .filter(BankAccount.organization_id == organization_id)
        .scalar()
        or 0
    )
    bank_reconciled = (
        db.query(func.count(BankTransaction.id))
        .join(BankAccount, BankTransaction.bank_account_id == BankAccount.id)
        .filter(
            BankAccount.organization_id == organization_id,
            BankTransaction.is_reconciled == True,
        )
        .scalar()
        or 0
    )
    bank_unreconciled = bank_total - bank_reconciled
    bank_latest = (
        db.query(func.max(BankTransaction.created_at))
        .join(BankAccount, BankTransaction.bank_account_id == BankAccount.id)
        .filter(BankAccount.organization_id == organization_id)
        .scalar()
    )

    # 2. General Ledger
    gl_total = (
        db.query(func.count(JournalLine.id))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.organization_id == organization_id)
        .scalar()
        or 0
    )
    gl_reconciled = (
        db.query(func.count(JournalLine.id))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(
            JournalEntry.organization_id == organization_id,
            JournalLine.is_reconciled == True,
        )
        .scalar()
        or 0
    )
    gl_unreconciled = gl_total - gl_reconciled
    gl_latest = (
        db.query(func.max(JournalLine.created_at))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.organization_id == organization_id)
        .scalar()
    )

    # 3. Trial Balance
    tb_total = (
        db.query(func.count(TrialBalanceRecord.id))
        .filter(TrialBalanceRecord.organization_id == organization_id)
        .scalar()
        or 0
    )
    tb_latest = (
        db.query(func.max(TrialBalanceRecord.created_at))
        .filter(TrialBalanceRecord.organization_id == organization_id)
        .scalar()
    )

    # 4. AP Invoices
    ap_total = (
        db.query(func.count(APInvoice.id))
        .filter(APInvoice.organization_id == organization_id)
        .scalar()
        or 0
    )
    ap_paid = (
        db.query(func.count(APInvoice.id))
        .filter(
            APInvoice.organization_id == organization_id,
            APInvoice.status == "PAID",
        )
        .scalar()
        or 0
    )
    ap_open = ap_total - ap_paid
    ap_latest = (
        db.query(func.max(APInvoice.created_at))
        .filter(APInvoice.organization_id == organization_id)
        .scalar()
    )

    # 5. Fixed Assets
    fa_total = (
        db.query(func.count(FixedAsset.id))
        .filter(FixedAsset.organization_id == organization_id)
        .scalar()
        or 0
    )
    fa_active = (
        db.query(func.count(FixedAsset.id))
        .filter(
            FixedAsset.organization_id == organization_id,
            FixedAsset.status == "ACTIVE",
        )
        .scalar()
        or 0
    )
    fa_latest = (
        db.query(func.max(FixedAsset.created_at))
        .filter(FixedAsset.organization_id == organization_id)
        .scalar()
    )

    # 6. Accruals (derived from journal lines in accrual accounts / descriptions or reconciliation results)
    accrual_total = (
        db.query(func.count(JournalLine.id))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .filter(
            JournalEntry.organization_id == organization_id,
            (
                Account.account_name.ilike("%accrual%")
                | JournalEntry.description.ilike("%accrual%")
                | JournalLine.description.ilike("%accrual%")
            ),
        )
        .scalar()
        or 0
    )
    accrual_latest = (
        db.query(func.max(JournalLine.created_at))
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .filter(
            JournalEntry.organization_id == organization_id,
            (
                Account.account_name.ilike("%accrual%")
                | JournalEntry.description.ilike("%accrual%")
                | JournalLine.description.ilike("%accrual%")
            ),
        )
        .scalar()
    )

    # 7. Depreciation (derived from Fixed Assets straight-line schedule)
    deprec_total = fa_total
    deprec_latest = fa_latest

    # All-Time Reconciliation Metric (Across GL and Bank records)
    total_recon_records = bank_total + gl_total
    reconciled_recon_records = bank_reconciled + gl_reconciled
    unreconciled_recon_records = bank_unreconciled + gl_unreconciled
    reconciled_percentage = (
        round((reconciled_recon_records / total_recon_records) * 100.0, 2)
        if total_recon_records > 0
        else 0.0
    )

    return {
        "all_time_reconciliation": {
            "total_records": total_recon_records,
            "reconciled_records": reconciled_recon_records,
            "unreconciled_records": unreconciled_recon_records,
            "reconciled_percentage": reconciled_percentage,
            "bank_total": bank_total,
            "bank_reconciled": bank_reconciled,
            "gl_total": gl_total,
            "gl_reconciled": gl_reconciled,
        },
        "data_types": {
            "bank_statements": {
                "id": "bank_statements",
                "display_name": "Bank Statements",
                "total_count": bank_total,
                "reconciled_count": bank_reconciled,
                "unreconciled_count": bank_unreconciled,
                "latest_import_date": _serialize_date(bank_latest),
                "has_reconciliation": True,
            },
            "general_ledger": {
                "id": "general_ledger",
                "display_name": "General Ledger",
                "total_count": gl_total,
                "reconciled_count": gl_reconciled,
                "unreconciled_count": gl_unreconciled,
                "latest_import_date": _serialize_date(gl_latest),
                "has_reconciliation": True,
            },
            "trial_balance": {
                "id": "trial_balance",
                "display_name": "Trial Balance",
                "total_count": tb_total,
                "reconciled_count": None,
                "unreconciled_count": None,
                "latest_import_date": _serialize_date(tb_latest),
                "has_reconciliation": False,
            },
            "ap_invoices": {
                "id": "ap_invoices",
                "display_name": "AP Invoices",
                "total_count": ap_total,
                "reconciled_count": ap_paid,
                "unreconciled_count": ap_open,
                "latest_import_date": _serialize_date(ap_latest),
                "has_reconciliation": True,
                "reconciled_label": "Paid",
                "unreconciled_label": "Open / Pending",
            },
            "fixed_assets": {
                "id": "fixed_assets",
                "display_name": "Fixed Assets",
                "total_count": fa_total,
                "reconciled_count": fa_active,
                "unreconciled_count": fa_total - fa_active,
                "latest_import_date": _serialize_date(fa_latest),
                "has_reconciliation": True,
                "reconciled_label": "Active",
                "unreconciled_label": "Disposed / Inactive",
            },
            "accruals": {
                "id": "accruals",
                "display_name": "Accruals",
                "total_count": accrual_total,
                "reconciled_count": None,
                "unreconciled_count": None,
                "latest_import_date": _serialize_date(accrual_latest),
                "has_reconciliation": False,
            },
            "depreciation": {
                "id": "depreciation",
                "display_name": "Depreciation Schedules",
                "total_count": deprec_total,
                "reconciled_count": None,
                "unreconciled_count": None,
                "latest_import_date": _serialize_date(deprec_latest),
                "has_reconciliation": False,
                "is_derived": True,
            },
        },
    }


@router.get("/{data_type}", response_model=Dict[str, Any])
def get_financial_data_preview(
    data_type: str,
    limit: int = Query(default=20, ge=1, le=100),
    organization_id: str = Query(default="default_org"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns latest preview rows and column metadata for a specific financial data type.
    """
    key = data_type.lower().strip()

    if key in ["bank_statements", "bank_transactions", "bank"]:
        rows = (
            db.query(BankTransaction, BankAccount)
            .join(BankAccount, BankTransaction.bank_account_id == BankAccount.id)
            .filter(BankAccount.organization_id == organization_id)
            .order_by(BankTransaction.booking_date.desc(), BankTransaction.created_at.desc())
            .limit(limit)
            .all()
        )
        records = [
            {
                "id": tx.id,
                "bank_name": acct.bank_name,
                "booking_date": _serialize_date(tx.booking_date),
                "value_date": _serialize_date(tx.value_date),
                "amount": _to_float(tx.amount),
                "currency_code": tx.currency_code,
                "description": tx.description or "-",
                "reference": tx.bank_reference or "-",
                "status": "Reconciled" if tx.is_reconciled else "Unreconciled",
                "is_reconciled": tx.is_reconciled,
            }
            for tx, acct in rows
        ]
        columns = [
            {"key": "booking_date", "label": "Date"},
            {"key": "bank_name", "label": "Bank Account"},
            {"key": "description", "label": "Description"},
            {"key": "reference", "label": "Reference"},
            {"key": "amount", "label": "Amount", "is_currency": True},
            {"key": "status", "label": "Reconciliation Status", "is_status": True},
        ]
        return {
            "data_type": "bank_statements",
            "display_name": "Bank Statements",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    elif key in ["general_ledger", "journal_lines", "gl"]:
        rows = (
            db.query(JournalLine, JournalEntry, Account)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .join(Account, JournalLine.account_id == Account.id)
            .filter(JournalEntry.organization_id == organization_id)
            .order_by(JournalEntry.entry_date.desc(), JournalLine.created_at.desc())
            .limit(limit)
            .all()
        )
        records = [
            {
                "id": line.id,
                "entry_date": _serialize_date(entry.entry_date),
                "account_code": acct.account_code or "-",
                "account_name": acct.account_name,
                "description": line.description or entry.description or "-",
                "reference": entry.reference or entry.external_entry_id or "-",
                "debit_amount": _to_float(line.debit_amount),
                "credit_amount": _to_float(line.credit_amount),
                "net_amount": _to_float(line.debit_amount) - _to_float(line.credit_amount),
                "currency_code": entry.currency_code,
                "status": "Reconciled" if line.is_reconciled else "Unreconciled",
                "is_reconciled": line.is_reconciled,
            }
            for line, entry, acct in rows
        ]
        columns = [
            {"key": "entry_date", "label": "Entry Date"},
            {"key": "account_code", "label": "Account Code"},
            {"key": "account_name", "label": "Account Name"},
            {"key": "description", "label": "Description"},
            {"key": "debit_amount", "label": "Debit", "is_currency": True},
            {"key": "credit_amount", "label": "Credit", "is_currency": True},
            {"key": "status", "label": "Status", "is_status": True},
        ]
        return {
            "data_type": "general_ledger",
            "display_name": "General Ledger",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    elif key in ["trial_balance", "tb"]:
        rows = (
            db.query(TrialBalanceRecord, Account)
            .join(Account, TrialBalanceRecord.account_id == Account.id)
            .filter(TrialBalanceRecord.organization_id == organization_id)
            .order_by(TrialBalanceRecord.fiscal_period.desc(), Account.account_name.asc())
            .limit(limit)
            .all()
        )
        records = [
            {
                "id": tb.id,
                "fiscal_period": tb.fiscal_period,
                "account_code": acct.account_code or "-",
                "account_name": acct.account_name,
                "opening_balance": _to_float(tb.opening_balance),
                "period_debit": _to_float(tb.period_debit),
                "period_credit": _to_float(tb.period_credit),
                "closing_balance": _to_float(tb.closing_balance),
                "currency_code": tb.currency_code,
            }
            for tb, acct in rows
        ]
        columns = [
            {"key": "fiscal_period", "label": "Period"},
            {"key": "account_code", "label": "Account Code"},
            {"key": "account_name", "label": "Account Name"},
            {"key": "opening_balance", "label": "Opening Balance", "is_currency": True},
            {"key": "period_debit", "label": "Period Debit", "is_currency": True},
            {"key": "period_credit", "label": "Period Credit", "is_currency": True},
            {"key": "closing_balance", "label": "Closing Balance", "is_currency": True},
        ]
        return {
            "data_type": "trial_balance",
            "display_name": "Trial Balance",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    elif key in ["ap_invoices", "ap", "invoices"]:
        rows = (
            db.query(APInvoice)
            .filter(APInvoice.organization_id == organization_id)
            .order_by(APInvoice.invoice_date.desc(), APInvoice.created_at.desc())
            .limit(limit)
            .all()
        )
        records = [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "invoice_date": _serialize_date(inv.invoice_date),
                "due_date": _serialize_date(inv.due_date),
                "total_amount": _to_float(inv.total_amount),
                "paid_amount": _to_float(inv.paid_amount),
                "outstanding_amount": _to_float(inv.outstanding_amount),
                "currency_code": inv.currency_code,
                "status": inv.status,
            }
            for inv in rows
        ]
        columns = [
            {"key": "invoice_number", "label": "Invoice #"},
            {"key": "vendor_name", "label": "Vendor"},
            {"key": "invoice_date", "label": "Invoice Date"},
            {"key": "due_date", "label": "Due Date"},
            {"key": "total_amount", "label": "Total Amount", "is_currency": True},
            {"key": "outstanding_amount", "label": "Outstanding", "is_currency": True},
            {"key": "status", "label": "Payment Status", "is_status": True},
        ]
        return {
            "data_type": "ap_invoices",
            "display_name": "AP Invoices",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    elif key in ["fixed_assets", "assets"]:
        rows = (
            db.query(FixedAsset)
            .filter(FixedAsset.organization_id == organization_id)
            .order_by(FixedAsset.acquisition_date.desc(), FixedAsset.created_at.desc())
            .limit(limit)
            .all()
        )
        records = [
            {
                "id": fa.id,
                "asset_code": fa.asset_code or "-",
                "asset_name": fa.asset_name,
                "category": fa.category.replace("_", " ").title(),
                "acquisition_date": _serialize_date(fa.acquisition_date),
                "acquisition_cost": _to_float(fa.acquisition_cost),
                "salvage_value": _to_float(fa.salvage_value),
                "useful_life_months": fa.useful_life_months or 0,
                "accumulated_depreciation": _to_float(fa.accumulated_depreciation),
                "book_value": _to_float(fa.book_value),
                "currency_code": fa.currency_code,
                "status": fa.status,
            }
            for fa in rows
        ]
        columns = [
            {"key": "asset_code", "label": "Asset Code"},
            {"key": "asset_name", "label": "Asset Name"},
            {"key": "category", "label": "Category"},
            {"key": "acquisition_date", "label": "Acquisition Date"},
            {"key": "acquisition_cost", "label": "Cost", "is_currency": True},
            {"key": "accumulated_depreciation", "label": "Accum. Deprec.", "is_currency": True},
            {"key": "book_value", "label": "Book Value", "is_currency": True},
            {"key": "status", "label": "Status", "is_status": True},
        ]
        return {
            "data_type": "fixed_assets",
            "display_name": "Fixed Assets",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    elif key in ["accruals", "accrual"]:
        rows = (
            db.query(JournalLine, JournalEntry, Account)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .join(Account, JournalLine.account_id == Account.id)
            .filter(
                JournalEntry.organization_id == organization_id,
                (
                    Account.account_name.ilike("%accrual%")
                    | JournalEntry.description.ilike("%accrual%")
                    | JournalLine.description.ilike("%accrual%")
                ),
            )
            .order_by(JournalEntry.entry_date.desc())
            .limit(limit)
            .all()
        )
        records = [
            {
                "id": line.id,
                "entry_date": _serialize_date(entry.entry_date),
                "account_name": acct.account_name,
                "account_code": acct.account_code or "-",
                "description": line.description or entry.description or "Accrual Entry",
                "amount": _to_float(line.debit_amount if line.debit_amount > 0 else line.credit_amount),
                "currency_code": entry.currency_code,
                "fiscal_period": entry.fiscal_period or "-",
            }
            for line, entry, acct in rows
        ]
        columns = [
            {"key": "entry_date", "label": "Date"},
            {"key": "fiscal_period", "label": "Period"},
            {"key": "account_name", "label": "Accrual Account"},
            {"key": "description", "label": "Description"},
            {"key": "amount", "label": "Amount", "is_currency": True},
        ]
        return {
            "data_type": "accruals",
            "display_name": "Accruals",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    elif key in ["depreciation", "deprec", "depreciation_schedules"]:
        # Derived from FixedAsset straight-line schedule
        rows = (
            db.query(FixedAsset)
            .filter(FixedAsset.organization_id == organization_id)
            .order_by(FixedAsset.acquisition_date.desc(), FixedAsset.created_at.desc())
            .limit(limit)
            .all()
        )
        records = []
        for fa in rows:
            cost = _to_float(fa.acquisition_cost)
            salvage = _to_float(fa.salvage_value)
            life_months = fa.useful_life_months or 36
            monthly_deprec = round((cost - salvage) / life_months, 2) if life_months > 0 and cost >= salvage else 0.0
            records.append({
                "id": fa.id,
                "asset_code": fa.asset_code or "-",
                "asset_name": fa.asset_name,
                "category": fa.category.replace("_", " ").title(),
                "acquisition_cost": cost,
                "useful_life_months": life_months,
                "monthly_depreciation": monthly_deprec,
                "accumulated_depreciation": _to_float(fa.accumulated_depreciation),
                "current_book_value": _to_float(fa.book_value),
                "currency_code": fa.currency_code,
                "status": fa.status,
            })

        columns = [
            {"key": "asset_name", "label": "Asset Name"},
            {"key": "category", "label": "Category"},
            {"key": "acquisition_cost", "label": "Acquisition Cost", "is_currency": True},
            {"key": "useful_life_months", "label": "Useful Life (Mo)"},
            {"key": "monthly_depreciation", "label": "Monthly Deprec.", "is_currency": True},
            {"key": "accumulated_depreciation", "label": "Accum. Deprec.", "is_currency": True},
            {"key": "current_book_value", "label": "Net Book Value", "is_currency": True},
        ]
        return {
            "data_type": "depreciation",
            "display_name": "Depreciation Schedules",
            "columns": columns,
            "records": records,
            "count": len(records),
        }

    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Financial data type '{data_type}' not recognized. Supported types: bank_statements, general_ledger, trial_balance, ap_invoices, fixed_assets, accruals, depreciation.",
        )
