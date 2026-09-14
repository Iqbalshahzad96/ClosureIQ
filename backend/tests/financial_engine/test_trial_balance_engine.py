"""Deterministic trial balance controls, independent of source formats."""
import json
from decimal import Decimal

import pytest

from app.financial_engine import ExceptionGenerator, TrialBalanceEngine


def row(**changes):
    return dict(account_code="1000", opening_balance="100", period_debit="20",
                period_credit="10", closing_balance="110", **changes)


@pytest.mark.parametrize("normal,account_type,closing", [
    ("DEBIT", "ASSET", "110"), ("CREDIT", "LIABILITY", "90"),
    ("CREDIT", "ASSET", "90"), ("DEBIT", "LIABILITY", "110"),
])
def test_continuity_uses_canonical_normal_balance(normal, account_type, closing):
    record = row(normal_balance=normal, account_type=account_type)
    record["closing_balance"] = closing
    result = TrialBalanceEngine().validate_trial_balance([record])
    assert result["continuity_errors"] == []
    assert result["valid_rows"][0]["calculated_closing"] == closing


def test_balanced_and_out_of_balance():
    debit = row()
    credit = dict(debit, account_code="2000", period_debit="10", period_credit="20",
                  normal_balance="CREDIT")
    result = TrialBalanceEngine().validate_trial_balance([debit, credit])
    assert result["status"] == "BALANCED"
    assert result["total_debits"] == result["total_credits"] == "30"
    assert TrialBalanceEngine().validate_trial_balance([debit])["is_balanced"] is False


@pytest.mark.parametrize("difference,balanced", [("0.0100", True), ("0.0101", False)])
def test_tolerance_is_applied_before_rounding(difference, balanced):
    record = dict(row(), period_debit=difference, period_credit="0",
                  opening_balance="0", closing_balance=difference)
    result = TrialBalanceEngine().validate_trial_balance([record])
    assert result["is_balanced"] is balanced
    assert result["debit_credit_difference"] == difference


def test_aggregation_preserves_precision_and_configured_tolerance():
    lines = [dict(account_code="1000", debit_amount="9999999999999.0001"),
             dict(account_code="1000", debit_amount="0.0002"),
             dict(account_code="2000", credit_amount="9999999999999.0000")]
    result = TrialBalanceEngine(tolerance="0.0002").aggregate_journal_lines(lines)
    assert result["grand_debit_total"] == "9999999999999.0003"
    assert result["grand_net_balance"] == "0.0003"
    assert result["is_balanced"] is False
    assert result["account_summaries"][0]["line_count"] == 2
    json.dumps(result)


def test_material_continuity_exception_keeps_canonical_evidence():
    record = dict(row(id="tb1", import_batch_id="batch1"), closing_balance="2110")
    result = TrialBalanceEngine().validate_trial_balance([record])
    exceptions = ExceptionGenerator().generate_exceptions(result, category="TRIAL_BALANCE", period="2026-01")
    assert len(exceptions) == 2
    continuity = exceptions[1]
    assert continuity.severity == "HIGH"
    assert continuity.amount_variance == 2000
    assert continuity.period == "2026-01"
    assert continuity.metadata["id"] == "tb1"
    assert continuity.metadata["import_batch_id"] == "batch1"
    assert Decimal(continuity.metadata["variance"]) == 2000
    json.dumps([exc.to_dict() for exc in exceptions])


@pytest.mark.parametrize("key,values", [("currency_code", ["KES", "USD"]),
                                        ("fiscal_period", ["2026-01", "2026-02"])])
def test_mixed_scopes_cannot_cancel(key, values):
    records = [dict(row(), **{key: value}) for value in values]
    for method in ("validate_trial_balance", "aggregate_journal_lines"):
        with pytest.raises(ValueError, match=key):
            getattr(TrialBalanceEngine(), method)(records)


def test_exact_mcp_amounts_override_legacy_float_fields():
    record = dict(row(), exact_amounts=dict(opening_balance="9999999999999.0001",
                  period_debit="0.0002", period_credit="0", closing_balance="9999999999999.0003"))
    assert TrialBalanceEngine().validate_trial_balance([record])["continuity_errors"] == []


def test_multiple_snapshots_are_not_double_counted():
    with pytest.raises(ValueError, match="one trial balance snapshot"):
        TrialBalanceEngine().validate_trial_balance([row(), row()])


def test_empty_input_is_not_a_completed_trial_balance():
    assert TrialBalanceEngine().validate_trial_balance([])["status"] == "NO_DATA"
