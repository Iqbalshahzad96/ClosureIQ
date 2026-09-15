"""
Controlled Synthetic Reconciliation Demo Data Seeder.

Provides a deterministic, idempotent demo-data seeding path for presentation use.
Populates canonical Account, BankAccount, JournalEntry/Line, and BankTransaction
records under organization 'default_org' for account DEMO-BANK-1010 and period 2025-12.

Guarantees:
- Idempotent: repeated runs update/preserve records without duplication.
- Isolated: does not modify or rewrite original Enquest raw files.
- Deterministic: 4 exact matches, 1 deliberate GL exception, 1 deliberate Bank exception.
- Zero external LLM calls.
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy.orm import Session

from app.database.models import (
    Account,
    BankAccount,
    BankTransaction,
    ImportBatch,
    JournalEntry,
    JournalLine,
    SourceSystem,
    TrialBalanceRecord,
)

DEMO_ACCOUNT_CODE = "DEMO-BANK-1010"
DEMO_PERIOD = "2025-12"
DEMO_ORG_ID = "default_org"
DEMO_CURRENCY = "KES"


def seed_demo_reconciliation_data(db: Session) -> Dict[str, int]:
    """Seed presentation-ready deterministic reconciliation data.

    Returns:
        Dict with counts of seeded entities.
    """
    # 1. Feeder Source System & Batch
    src = db.get(SourceSystem, "src-demo-recon")
    if not src:
        src = SourceSystem(
            id="src-demo-recon",
            organization_id=DEMO_ORG_ID,
            adapter_key="demo_seeder",
            source_type="MANUAL",
            display_name="Demo Reconciliation Data Seeder",
            is_active=True,
        )
        db.add(src)
        db.flush()

    batch = db.get(ImportBatch, "batch-demo-recon-2025-12")
    if not batch:
        batch = ImportBatch(
            id="batch-demo-recon-2025-12",
            source_system_id=src.id,
            organization_id=DEMO_ORG_ID,
            period_start=datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc),
            period_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            status="COMPLETED",
            file_count=2,
            total_rows=10,
            valid_rows=10,
            error_rows=0,
        )
        db.add(batch)
        db.flush()

    # 2. Canonical GL Account (DEMO-BANK-1010)
    account = db.get(Account, "acc-demo-bank-1010")
    if not account:
        account = Account(
            id="acc-demo-bank-1010",
            organization_id=DEMO_ORG_ID,
            account_code=DEMO_ACCOUNT_CODE,
            account_name="Demo KES Operating Bank Account",
            normalized_name="demo kes operating bank account",
            account_type="ASSET",
            normal_balance="DEBIT",
            currency_code=DEMO_CURRENCY,
            is_active=True,
        )
        db.add(account)
        db.flush()

    # 3. Canonical Bank Account
    bank_account = db.get(BankAccount, "bank-demo-1010")
    if not bank_account:
        bank_account = BankAccount(
            id="bank-demo-1010",
            organization_id=DEMO_ORG_ID,
            bank_name="Demo Commercial Bank (KES)",
            account_number_masked="******1010",
            account_name="Operating Account - KES",
            currency_code=DEMO_CURRENCY,
            linked_gl_account_id=account.id,
            is_active=True,
        )
        db.add(bank_account)
        db.flush()

    # 4. Canonical Journal Entries and Lines (GL transactions)
    # 4 matches + 1 deliberate GL-only exception
    gl_fixtures = [
        {
            "entry_id": "je-demo-001",
            "line_id": "jl-demo-001",
            "date": datetime(2025, 12, 5, 9, 0, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-001",
            "debit": Decimal("50000.0000"),
            "credit": Decimal("0.0000"),
            "desc": "Customer Invoice Payment - Alpha Ltd",
        },
        {
            "entry_id": "je-demo-002",
            "line_id": "jl-demo-002",
            "date": datetime(2025, 12, 10, 11, 30, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-002",
            "debit": Decimal("0.0000"),
            "credit": Decimal("12500.0000"),
            "desc": "Office Supplies Settlement - Beta Supplies",
        },
        {
            "entry_id": "je-demo-003",
            "line_id": "jl-demo-003",
            "date": datetime(2025, 12, 15, 14, 15, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-003",
            "debit": Decimal("34200.0000"),
            "credit": Decimal("0.0000"),
            "desc": "Client Retainer Advance - Gamma Corp",
        },
        {
            "entry_id": "je-demo-004",
            "line_id": "jl-demo-004",
            "date": datetime(2025, 12, 18, 16, 45, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-004",
            "debit": Decimal("0.0000"),
            "credit": Decimal("8750.0000"),
            "desc": "Utility Expense - Nairobi Power",
        },
        {
            "entry_id": "je-demo-005",
            "line_id": "jl-demo-005",
            "date": datetime(2025, 12, 20, 10, 0, 0, tzinfo=timezone.utc),
            "ref": "DEMO-GL-ONLY",
            "debit": Decimal("15000.0000"),
            "credit": Decimal("0.0000"),
            "desc": "Uncredited Cash Deposit - Branch Counter",
        },
    ]

    for item in gl_fixtures:
        je = db.get(JournalEntry, item["entry_id"])
        if not je:
            je = JournalEntry(
                id=item["entry_id"],
                organization_id=DEMO_ORG_ID,
                import_batch_id=batch.id,
                entry_number=item["ref"],
                entry_type="BANK_JOURNAL",
                entry_date=item["date"],
                posting_date=item["date"],
                fiscal_period=DEMO_PERIOD,
                reference=item["ref"],
                description=item["desc"],
                currency_code=DEMO_CURRENCY,
                status="POSTED",
            )
            db.add(je)
            db.flush()

        jl = db.get(JournalLine, item["line_id"])
        if not jl:
            jl = JournalLine(
                id=item["line_id"],
                journal_entry_id=je.id,
                account_id=account.id,
                line_number=1,
                description=item["desc"],
                debit_amount=item["debit"],
                credit_amount=item["credit"],
                base_debit_amount=item["debit"],
                base_credit_amount=item["credit"],
                is_reconciled=False,
                source_row_identifier=f"demo_gl:{item['ref']}",
            )
            db.add(jl)

    # 5. Canonical Bank Transactions
    # 4 matches + 1 deliberate Bank-only fee exception
    bank_fixtures = [
        {
            "id": "bt-demo-001",
            "date": datetime(2025, 12, 5, 10, 30, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-001",
            "amount": Decimal("50000.0000"),
            "desc": "EFT INW - Alpha Ltd",
        },
        {
            "id": "bt-demo-002",
            "date": datetime(2025, 12, 10, 12, 0, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-002",
            "amount": Decimal("-12500.0000"),
            "desc": "EFT OUT - Beta Supplies",
        },
        {
            "id": "bt-demo-003",
            "date": datetime(2025, 12, 15, 15, 0, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-003",
            "amount": Decimal("34200.0000"),
            "desc": "DIRECT DEP - Gamma Corp",
        },
        {
            "id": "bt-demo-004",
            "date": datetime(2025, 12, 18, 17, 10, 0, tzinfo=timezone.utc),
            "ref": "DEMO-TX-004",
            "amount": Decimal("-8750.0000"),
            "desc": "STANDING ORDER - Nairobi Power",
        },
        {
            "id": "bt-demo-005",
            "date": datetime(2025, 12, 22, 8, 0, 0, tzinfo=timezone.utc),
            "ref": "DEMO-BANK-FEE",
            "amount": Decimal("-2500.0000"),
            "desc": "MONTHLY ACCOUNT MAINTENANCE FEE & CHARGES",
        },
    ]

    for item in bank_fixtures:
        bt = db.get(BankTransaction, item["id"])
        if not bt:
            bt = BankTransaction(
                id=item["id"],
                bank_account_id=bank_account.id,
                import_batch_id=batch.id,
                external_transaction_id=item["ref"],
                booking_date=item["date"],
                value_date=item["date"],
                amount=item["amount"],
                currency_code=DEMO_CURRENCY,
                bank_reference=item["ref"],
                description=item["desc"],
                is_reconciled=False,
                source_row_identifier=f"demo_bank:{item['ref']}",
            )
            db.add(bt)

    # 6. Trial Balance Record for DEMO-BANK-1010 in 2025-12
    tb = db.get(TrialBalanceRecord, "tb-demo-2025-12")
    if not tb:
        tb = TrialBalanceRecord(
            id="tb-demo-2025-12",
            organization_id=DEMO_ORG_ID,
            account_id=account.id,
            import_batch_id=batch.id,
            fiscal_period=DEMO_PERIOD,
            period_start=datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc),
            period_end=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
            opening_balance=Decimal("0.0000"),
            period_debit=Decimal("99200.0000"),
            period_credit=Decimal("21250.0000"),
            closing_balance=Decimal("77950.0000"),
            currency_code=DEMO_CURRENCY,
        )
        db.add(tb)

    db.flush()
    return {
        "accounts": 1,
        "bank_accounts": 1,
        "journal_lines": len(gl_fixtures),
        "bank_transactions": len(bank_fixtures),
        "trial_balance_records": 1,
    }


def main():
    """CLI entrypoint for standalone seeding."""
    from app.database.database import get_db_context
    with get_db_context() as session:
        counts = seed_demo_reconciliation_data(session)
        session.commit()
        print(f"Successfully seeded demo reconciliation data for {DEMO_ACCOUNT_CODE} (Period: {DEMO_PERIOD}):")
        for k, v in counts.items():
            print(f"  - {k}: {v}")


if __name__ == "__main__":
    main()
