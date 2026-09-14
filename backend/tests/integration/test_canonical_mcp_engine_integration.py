"""Seeded canonical records feed the existing engine interfaces through MCP."""
import asyncio
from datetime import datetime

from app.database.models import Account
from app.financial_engine import (
    APEngine, AccrualEngine, DepreciationEngine, ExceptionGenerator,
    ReconciliationEngine, TrialBalanceEngine,
)
from app.mcp.tools import FinancialMCPTools
from tests.canonical_fixtures import (
    ap_invoice_record, financial_record, fixed_asset_record, trial_balance_record,
)
from tests.mcp.test_canonical_mcp import test_session_factory  # Shared isolated canonical DB fixture.


def test_canonical_reconciliation_and_accrual(test_session_factory):
    with test_session_factory.begin() as session:
        for source in ("GL", "BANK"):
            record = financial_record(session, id=source, source=source, account_code="1000",
                                      amount=1500, reference="REF1", transaction_date=datetime(2026, 1, 15))
            if source == "GL":
                record.journal_entry.fiscal_period = "2026-01"
                record.dimensions_json = {"Is Bank Reconciliated": True}
        prior = financial_record(session, id="prior", source="GL", account_code="1000", amount=1000)
        prior.journal_entry.fiscal_period = "2025-12"
    tools = FinancialMCPTools(test_session_factory)
    current = asyncio.run(tools.query_gl_transactions("1000", fiscal_period="2026-01"))
    bank = asyncio.run(tools.query_bank_transactions("1000"))
    reconciliation = ReconciliationEngine().reconcile(current, bank)
    assert len(reconciliation["matched"]) == 1
    assert reconciliation["unmatched_gl"] == reconciliation["unmatched_bank"] == []
    assert current[0]["is_reconciled"] is False
    baseline_rows = asyncio.run(tools.query_gl_transactions("1000", fiscal_period="2025-12"))
    baseline = {"1000": sum(record["amount"] for record in baseline_rows)}
    accrual = AccrualEngine().validate_accruals(current, baseline)
    assert accrual["net_variance"] == 500
    assert accrual["status"] == "ANOMALIES_DETECTED"
    assert ExceptionGenerator().from_accruals(accrual, "2026-01")[0].amount_variance == 500


def test_canonical_depreciation_and_ap(test_session_factory):
    with test_session_factory.begin() as session:
        fixed_asset_record(session, acquisition_cost=1200, useful_life_months=12)
        ap_invoice_record(session, total_amount=1200)  # Canonical invoice total disagrees with 1000 + 160.
        posting = financial_record(session, id="dep", source="GL", account_code="6000", amount=100)
        posting.journal_entry.fiscal_period = "2026-01"
        asset = session.query(Account).filter_by(account_code="6000").one()
        from app.database.models import FixedAsset
        session.get(FixedAsset, "fa_001").deprec_expense_account_id = asset.id
    tools = FinancialMCPTools(test_session_factory)
    assets = asyncio.run(tools.query_fixed_assets())
    accounts = {row["id"]: row["account_code"] for row in asyncio.run(tools.query_chart_of_accounts())}
    # The canonical expense-account mapping identifies the posted amount for this asset.
    posted = {}
    for asset in assets:
        entries = asyncio.run(tools.query_gl_transactions(accounts[asset["deprec_expense_account_id"]], fiscal_period="2026-01"))
        posted[asset["id"]] = sum(entry["amount"] for entry in entries)
    depreciation = DepreciationEngine().validate_depreciation_schedule(assets, posted)
    assert depreciation["total_calculated_depreciation"] == 100
    assert depreciation["net_variance"] == 0
    assert depreciation["status"] == "VALID"
    ap = APEngine().validate_ap_invoices(asyncio.run(tools.query_ap_invoices()), as_of_date="2026-01-31")
    assert len(ap["calculation_errors"]) == 1
    exceptions = ExceptionGenerator().from_ap(ap, "2026-01")
    assert any(abs(exception.amount_variance) == 40 for exception in exceptions)


def test_canonical_trial_balance_to_exceptions(test_session_factory):
    with test_session_factory.begin() as session:
        trial_balance_record(session, id="debit", account_code="1000", opening_balance=0,
                             period_debit="100.0001", period_credit=0, closing_balance="100.0001")
        credit = trial_balance_record(session, id="credit", account_code="2000", opening_balance=0,
                                      period_debit=0, period_credit="100.0001", closing_balance="100.0001")
        credit.account.normal_balance = "CREDIT"
        credit.account.account_type = "LIABILITY"
        trial_balance_record(session, id="different_period", account_code="1000", fiscal_period="2025-12")
    tools = FinancialMCPTools(test_session_factory)
    records = asyncio.run(tools.query_trial_balance(fiscal_period="2026-01"))
    report = TrialBalanceEngine().validate_trial_balance(records)
    assert report["status"] == "BALANCED"
    assert report["total_debits"] == report["total_credits"] == "100.0001"
    assert ExceptionGenerator().from_trial_balance(report) == []
    with test_session_factory.begin() as session:
        from app.database.models import TrialBalanceRecord
        session.get(TrialBalanceRecord, "credit").closing_balance = "120.0001"
    records = asyncio.run(tools.query_trial_balance(fiscal_period="2026-01"))
    report = TrialBalanceEngine().validate_trial_balance(records)
    exceptions = ExceptionGenerator().generate_exceptions(report, period="2026-01", category="TRIAL_BALANCE")
    assert len(exceptions) == 1
    assert exceptions[0].amount_variance == 20
    assert exceptions[0].metadata["id"] == "credit"
    assert asyncio.run(tools.get_record_lineage("TRIAL_BALANCE", exceptions[0].metadata["id"]))["found"] is True
