"""Period-only runs select all eligible data and exclude other periods."""
import asyncio
from datetime import datetime

import pytest

from tests.integration.test_canonical_workflow_integration import db_session_factory, workflow_service
from tests.canonical_fixtures import financial_record, fixed_asset_record, ap_invoice_record
from app.database.models import Account, JournalEntry
from app.api.routes.reconciliation import AccrualRunRequest
from app.financial_engine.periods import period_bounds


def test_period_only_accrual_request():
    assert AccrualRunRequest(period="2026-01").account_code is None


def test_all_accrual_accounts_and_pages(workflow_service, db_session_factory):
    with db_session_factory() as db:
        for code in ("2100", "2200"):
            for index in range(3):
                financial_record(db, id=f"{code}_{index}", source="GL", account_code=code,
                    amount=100, transaction_date=datetime(2026, 1, 15))
            db.query(Account).filter_by(account_code=code).one().account_name = "Accrued expenses"
        for name, date, status, code in (
            ("old", datetime(2025, 12, 15), "POSTED", "2100"),
            ("draft", datetime(2026, 1, 15), "DRAFT", "2100"),
            ("cash", datetime(2026, 1, 15), "POSTED", "1010"),
        ):
            financial_record(db, id=name, source="GL", account_code=code, amount=100, transaction_date=date)
            db.get(JournalEntry, "entry_" + name).status = status
        db.commit()
    result = asyncio.run(workflow_service.deps.fetch_data("accrual", {"period": "2026-01", "limit": 2}))
    assert len(result["accrual_entries"]) == 6
    assert {r["account_code"] for r in result["accrual_entries"]} == {"2100", "2200"}


def test_assets_and_invoices_follow_period(workflow_service, db_session_factory):
    with db_session_factory() as db:
        fixed_asset_record(db, id="active")
        fixed_asset_record(db, id="future", in_service_date=datetime(2026, 2, 1))
        fixed_asset_record(db, id="disposed", status="DISPOSED")
        for index in range(3):
            ap_invoice_record(db, id=f"jan{index}", invoice_date=datetime(2026, 1, 31))
        ap_invoice_record(db, id="feb", invoice_date=datetime(2026, 2, 1))
        db.commit()
    assets = asyncio.run(workflow_service.deps.fetch_data("depreciation", {"period": "2026-01", "limit": 2}))
    assert [r["id"] for r in assets["asset_records"]] == ["active"]
    invoices = asyncio.run(workflow_service.deps.fetch_data("ap_review", {"period": "2026-01", "limit": 2}))
    assert {r["id"] for r in invoices["invoices"]} == {"jan0", "jan1", "jan2"}
    assert invoices["as_of_date"] == "2026-01-31"


def test_bank_and_gl_follow_period(workflow_service, db_session_factory):
    with db_session_factory() as db:
        for code in ("1010", "1020"):
            for source in ("GL", "BANK"):
                for month in (1, 2):
                    financial_record(db, id=f"{code}_{source}_{month}", source=source,
                        account_code=code, amount=100, transaction_date=datetime(2026, month, 15))
        db.commit()
    result = asyncio.run(workflow_service.deps.fetch_data("reconciliation", {"period": "2026-01", "limit": 1}))
    assert len(result["accounts_data"]) == 2
    for account in result["accounts_data"]:
        assert len(account["gl_transactions"]) == len(account["bank_transactions"]) == 1
        assert account["bank_transactions"][0]["transaction_date"].startswith("2026-01")


def test_year_preview_counts_gl_with_quarter_fiscal_period(workflow_service, db_session_factory):
    with db_session_factory() as db:
        financial_record(db, id="gl_quarter", source="GL", account_code="1010",
            amount=100, transaction_date=datetime(2025, 3, 15))
        db.get(JournalEntry, "entry_gl_quarter").fiscal_period = "2025-Q1"
        financial_record(db, id="gl_date_fallback", source="GL", account_code="1010",
            amount=200, transaction_date=datetime(2025, 9, 15))
        db.get(JournalEntry, "entry_gl_date_fallback").fiscal_period = "FY25"
        financial_record(db, id="bank_2025", source="BANK", account_code="1010",
            amount=100, transaction_date=datetime(2025, 3, 16))
        financial_record(db, id="gl_other_year", source="GL", account_code="1010",
            amount=300, transaction_date=datetime(2024, 12, 31))
        account = db.query(Account).filter_by(account_code="1010").one()
        account.currency_code = "USD"
        account.account_code = None
        db.commit()

    preview = asyncio.run(workflow_service.get_reconciliation_preview("2025"))
    result = asyncio.run(workflow_service.deps.fetch_data("reconciliation", {"period": "2025", "limit": 1}))

    assert preview["total_gl_transactions"] == 2
    assert preview["total_bank_transactions"] == 1
    assert len(result["accounts_data"]) == 1
    assert len(result["accounts_data"][0]["gl_transactions"]) == 2
    assert len(result["accounts_data"][0]["bank_transactions"]) == 1


@pytest.mark.parametrize("workflow", ["accrual", "depreciation", "ap_review"])
def test_empty_period_has_clear_error(workflow_service, workflow):
    with pytest.raises(ValueError, match="No eligible"):
        asyncio.run(workflow_service.deps.fetch_data(workflow, {"period": "2026-01"}))


def test_calendar_boundaries():
    assert period_bounds("2026-Q4") == (datetime(2026, 10, 1), datetime(2027, 1, 1))
    assert period_bounds("2026") == (datetime(2026, 1, 1), datetime(2027, 1, 1))
    with pytest.raises(ValueError):
        period_bounds("2026-13")
