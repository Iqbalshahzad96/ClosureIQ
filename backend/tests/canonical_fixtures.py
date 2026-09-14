from decimal import Decimal
from datetime import datetime
from app.database.models import (
    Account,
    BankAccount,
    BankTransaction,
    JournalEntry,
    JournalLine,
    FixedAsset,
    APInvoice,
    TrialBalanceRecord,
    ReconciliationRun,
    ReconciliationResult,
    ExceptionRecord,
)


def financial_record(
    session,
    *,
    id,
    source,
    account_code,
    amount,
    transaction_date=None,
    description=None,
    reference=None,
    is_reconciled=False,
):
    account = session.query(Account).filter_by(account_code=account_code, organization_id="default_org").first()
    if account is None:
        account = Account(
            account_code=account_code,
            account_name=account_code,
            normalized_name=account_code,
            account_type="ASSET",
            currency_code="KES",
        )
        session.add(account)
        session.flush()
    value = Decimal(str(amount))
    if source == "GL":
        entry = JournalEntry(
            id="entry_" + id,
            entry_date=transaction_date,
            reference=reference,
            description=description,
            currency_code="KES",
        )
        session.add(entry)
        session.flush()
        line = JournalLine(
            id=id,
            journal_entry_id=entry.id,
            account_id=account.id,
            debit_amount=max(value, Decimal(0)),
            credit_amount=max(-value, Decimal(0)),
            description=description,
            is_reconciled=is_reconciled,
        )
        session.add(line)
        session.flush()
        return line
    bank = session.query(BankAccount).filter_by(linked_gl_account_id=account.id).first()
    if bank is None:
        bank = BankAccount(
            linked_gl_account_id=account.id,
            bank_name="Demo",
            account_number_masked="***",
            account_name=account_code,
            currency_code="KES",
        )
        session.add(bank)
        session.flush()
    tx = BankTransaction(
        id=id,
        bank_account_id=bank.id,
        booking_date=transaction_date,
        amount=value,
        bank_reference=reference,
        description=description,
        is_reconciled=is_reconciled,
    )
    session.add(tx)
    session.flush()
    return tx


def fixed_asset_record(
    session,
    *,
    id="fa_001",
    asset_code="FA-1001",
    asset_name="Dell Server",
    category="COMPUTERS",
    acquisition_date=None,
    in_service_date=None,
    acquisition_cost=12000.00,
    salvage_value=0.0,
    useful_life_months=36,
    depreciation_method="STRAIGHT_LINE",
    accumulated_depreciation=0.0,
    book_value=None,
    currency_code="KES",
    status="ACTIVE",
):
    cost_dec = Decimal(str(acquisition_cost))
    salvage_dec = Decimal(str(salvage_value))
    accum_dec = Decimal(str(accumulated_depreciation))
    bv_dec = Decimal(str(book_value)) if book_value is not None else (cost_dec - accum_dec)
    asset = FixedAsset(
        id=id,
        organization_id="default_org",
        asset_code=asset_code,
        asset_name=asset_name,
        category=category,
        acquisition_date=acquisition_date or datetime(2025, 1, 1),
        in_service_date=in_service_date or datetime(2025, 1, 1),
        acquisition_cost=cost_dec,
        salvage_value=salvage_dec,
        useful_life_months=useful_life_months,
        depreciation_method=depreciation_method,
        accumulated_depreciation=accum_dec,
        book_value=bv_dec,
        currency_code=currency_code,
        status=status,
    )
    session.add(asset)
    session.flush()
    return asset


def ap_invoice_record(
    session,
    *,
    id="inv_001",
    vendor_name="Acme Corp",
    vendor_code="VEND-001",
    invoice_number="INV-2026-001",
    invoice_date=None,
    due_date=None,
    subtotal_amount=1000.0,
    tax_amount=160.0,
    total_amount=1160.0,
    paid_amount=0.0,
    outstanding_amount=None,
    currency_code="KES",
    status="OPEN",
    description="Office supplies",
):
    tot_dec = Decimal(str(total_amount))
    paid_dec = Decimal(str(paid_amount))
    out_dec = Decimal(str(outstanding_amount)) if outstanding_amount is not None else (tot_dec - paid_dec)
    inv = APInvoice(
        id=id,
        organization_id="default_org",
        vendor_name=vendor_name,
        vendor_code=vendor_code,
        invoice_number=invoice_number,
        invoice_date=invoice_date or datetime(2026, 1, 10),
        due_date=due_date or datetime(2026, 2, 10),
        subtotal_amount=Decimal(str(subtotal_amount)),
        tax_amount=Decimal(str(tax_amount)),
        total_amount=tot_dec,
        paid_amount=paid_dec,
        outstanding_amount=out_dec,
        currency_code=currency_code,
        status=status,
        description=description,
    )
    session.add(inv)
    session.flush()
    return inv


def trial_balance_record(
    session,
    *,
    id="tb_001",
    account_code="1010",
    account_name="Cash & Bank",
    fiscal_period="2026-01",
    opening_balance=5000.0,
    period_debit=1500.0,
    period_credit=500.0,
    closing_balance=6000.0,
    currency_code="KES",
):
    account = session.query(Account).filter_by(account_code=account_code, organization_id="default_org").first()
    if account is None:
        account = Account(
            account_code=account_code,
            account_name=account_name,
            normalized_name=account_name,
            account_type="ASSET",
            currency_code=currency_code,
        )
        session.add(account)
        session.flush()
    tb = TrialBalanceRecord(
        id=id,
        organization_id="default_org",
        account_id=account.id,
        fiscal_period=fiscal_period,
        opening_balance=Decimal(str(opening_balance)),
        period_debit=Decimal(str(period_debit)),
        period_credit=Decimal(str(period_credit)),
        closing_balance=Decimal(str(closing_balance)),
        currency_code=currency_code,
    )
    session.add(tb)
    session.flush()
    return tb
