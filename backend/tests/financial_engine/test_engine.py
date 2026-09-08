"""
Deterministic Financial Engine Test Suite

Comprehensive tests for GL-to-Bank Reconciliation, Accrual Validation,
Fixed Asset Depreciation Schedules, and Exception Generation.
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime

from app.financial_engine.reconciliation import ReconciliationEngine
from app.financial_engine.accrual import AccrualEngine
from app.financial_engine.depreciation import DepreciationEngine
from app.financial_engine.exceptions import ExceptionGenerator, FinancialException


# ===========================================================================
# 1. Reconciliation Engine Tests
# ===========================================================================

def test_reconciliation_empty_inputs():
    """Empty inputs should return clean zeroed summary without errors."""
    engine = ReconciliationEngine(tolerance=0.01)
    result = engine.reconcile(gl_transactions=[], bank_transactions=[])

    assert result["total_gl"] == 0
    assert result["total_bank"] == 0
    assert result["matched_count"] == 0
    assert result["unmatched_gl_count"] == 0
    assert result["unmatched_bank_count"] == 0
    assert result["net_variance"] == 0.0
    assert result["reconciliation_rate"] == 100.0
    assert result["status"] == "RECONCILED"


def test_reconciliation_exact_reference_and_amount_match():
    """Exact reference and amount matches should pair successfully."""
    engine = ReconciliationEngine(tolerance=0.01)

    gl_txs = [
        {"id": "gl_1", "reference": "INV-1001", "amount": 1500.00, "transaction_date": "2026-01-15T10:00:00"},
        {"id": "gl_2", "reference": "INV-1002", "amount": 2300.50, "transaction_date": "2026-01-16T12:00:00"},
    ]
    bank_txs = [
        {"id": "bk_1", "reference": "INV-1001", "amount": 1500.00, "transaction_date": "2026-01-15T15:00:00"},
        {"id": "bk_2", "reference": "INV-1002", "amount": 2300.50, "transaction_date": "2026-01-17T09:00:00"},
    ]

    result = engine.reconcile(gl_txs, bank_txs)

    assert result["matched_count"] == 2
    assert result["unmatched_gl_count"] == 0
    assert result["unmatched_bank_count"] == 0
    assert result["net_variance"] == 0.0
    assert result["reconciliation_rate"] == 100.0
    assert result["status"] == "RECONCILED"
    assert result["matched"][0]["match_type"] == "EXACT_REFERENCE_AND_AMOUNT"


def test_reconciliation_tolerance_boundary():
    """Matching within tolerance should succeed; exceeding tolerance should fail."""
    engine = ReconciliationEngine(tolerance=0.01)

    # Within tolerance ($0.008 diff <= $0.01)
    gl_within = [{"id": "gl_1", "reference": "REF-A", "amount": 100.000}]
    bk_within = [{"id": "bk_1", "reference": "REF-A", "amount": 100.008}]
    res_within = engine.reconcile(gl_within, bk_within)
    assert res_within["matched_count"] == 1

    # Exceeding tolerance ($0.05 diff > $0.01)
    gl_exceed = [{"id": "gl_2", "reference": "REF-B", "amount": 100.00}]
    bk_exceed = [{"id": "bk_2", "reference": "REF-B", "amount": 100.05}]
    res_exceed = engine.reconcile(gl_exceed, bk_exceed)
    assert res_exceed["matched_count"] == 0
    assert res_exceed["unmatched_gl_count"] == 1
    assert res_exceed["unmatched_bank_count"] == 1
    assert res_exceed["status"] == "UNRESOLVED_DISCREPANCIES"


def test_reconciliation_date_window_fallback_match():
    """When reference is missing or differs, matches on exact amount within date window."""
    engine = ReconciliationEngine(tolerance=0.01, date_window_days=3)

    gl_txs = [
        {"id": "gl_1", "reference": "", "amount": 450.00, "transaction_date": "2026-01-10T10:00:00"},
    ]
    bank_txs = [
        {"id": "bk_1", "reference": "WIRE-450", "amount": 450.00, "transaction_date": "2026-01-12T14:00:00"},
    ]

    result = engine.reconcile(gl_txs, bank_txs)
    assert result["matched_count"] == 1
    assert result["matched"][0]["match_type"] == "AMOUNT_AND_DATE_WINDOW"


def test_reconciliation_date_window_exceeded():
    """Fallback matching should not match if dates are beyond configured date window."""
    engine = ReconciliationEngine(tolerance=0.01, date_window_days=2)

    gl_txs = [
        {"id": "gl_1", "reference": "", "amount": 450.00, "transaction_date": "2026-01-01T10:00:00"},
    ]
    bank_txs = [
        {"id": "bk_1", "reference": "", "amount": 450.00, "transaction_date": "2026-01-10T14:00:00"},
    ]

    result = engine.reconcile(gl_txs, bank_txs)
    assert result["matched_count"] == 0
    assert result["unmatched_gl_count"] == 1
    assert result["unmatched_bank_count"] == 1


def test_reconciliation_one_to_one_constraint():
    """Ensure a single bank transaction is not matched multiple times to duplicate GL entries."""
    engine = ReconciliationEngine(tolerance=0.01)

    gl_txs = [
        {"id": "gl_1", "reference": "DUP-REF", "amount": 200.00},
        {"id": "gl_2", "reference": "DUP-REF", "amount": 200.00},
    ]
    bank_txs = [
        {"id": "bk_1", "reference": "DUP-REF", "amount": 200.00},
    ]

    result = engine.reconcile(gl_txs, bank_txs)
    assert result["matched_count"] == 1
    assert result["unmatched_gl_count"] == 1
    assert result["unmatched_bank_count"] == 0


# ===========================================================================
# 2. Accrual Engine Tests
# ===========================================================================

def test_accrual_normal_within_threshold():
    """Accruals within 10% threshold should pass as valid without anomalies."""
    engine = AccrualEngine(variance_threshold_pct=0.10, material_amount_threshold=50.0)

    accruals = [
        {"vendor": "AWS Cloud", "account_code": "6100", "amount": 5100.00},
    ]
    baseline = {
        "AWS Cloud": 5000.00,  # 2% variance
    }

    result = engine.validate_accruals(accruals, baseline)
    assert result["status"] == "CLEAN"
    assert result["valid_accruals_count"] == 1
    assert result["anomalies_count"] == 0


def test_accrual_material_variance_anomaly():
    """Accruals exceeding 10% variance and $50 material threshold should flag an anomaly."""
    engine = AccrualEngine(variance_threshold_pct=0.10, material_amount_threshold=50.0)

    accruals = [
        {"vendor": "Legal Counsel", "account_code": "6200", "amount": 12000.00},
    ]
    baseline = {
        "Legal Counsel": 8000.00,  # 50% variance ($4,000 diff)
    }

    result = engine.validate_accruals(accruals, baseline)
    assert result["status"] == "ANOMALIES_DETECTED"
    assert result["anomalies_count"] == 1
    assert result["anomalies"][0]["type"] == "MATERIAL_VARIANCE"
    assert result["anomalies"][0]["variance_amount"] == 4000.00
    assert result["anomalies"][0]["variance_pct"] == 50.0


def test_accrual_immaterial_variance_ignored():
    """Variances exceeding % threshold but below dollar threshold should be considered valid."""
    engine = AccrualEngine(variance_threshold_pct=0.10, material_amount_threshold=50.0)

    accruals = [
        {"vendor": "Office Snacks", "account_code": "6300", "amount": 15.00},
    ]
    baseline = {
        "Office Snacks": 10.00,  # 50% variance, but only $5 difference
    }

    result = engine.validate_accruals(accruals, baseline)
    assert result["status"] == "CLEAN"
    assert result["valid_accruals_count"] == 1


def test_accrual_missing_recurring_anomaly():
    """Missing expected recurring accrual should be flagged."""
    engine = AccrualEngine(material_amount_threshold=50.0)

    accruals = []  # No accrual posted
    baseline = {
        "Audit Fee": {"amount": 3500.00, "is_recurring": True},
    }

    result = engine.validate_accruals(accruals, baseline)
    assert result["status"] == "ANOMALIES_DETECTED"
    assert result["anomalies_count"] == 1
    assert result["anomalies"][0]["type"] == "MISSING_ACCRUAL"
    assert result["anomalies"][0]["expected_amount"] == 3500.00


def test_accrual_negative_or_zero_amount():
    """Zero or negative accrual amount should be flagged as invalid."""
    engine = AccrualEngine()

    accruals = [
        {"vendor": "Vendor X", "account_code": "6400", "amount": -100.00},
    ]
    baseline = {}

    result = engine.validate_accruals(accruals, baseline)
    assert result["status"] == "ANOMALIES_DETECTED"
    assert result["anomalies"][0]["type"] == "INVALID_AMOUNT"


# ===========================================================================
# 3. Depreciation Engine Tests
# ===========================================================================

def test_depreciation_straight_line_formula():
    """Verify straight-line formula: (Cost - Salvage) / Useful_Life."""
    # $12,000 cost, $0 salvage, 36 months = $333.33/mo
    calc1 = DepreciationEngine.calculate_straight_line_monthly(12000, 0, 36)
    assert calc1 == 333.33

    # $20,000 cost, $2,000 salvage, 60 months = $300.00/mo
    calc2 = DepreciationEngine.calculate_straight_line_monthly(20000, 2000, 60)
    assert calc2 == 300.00


def test_depreciation_invalid_parameters():
    """Useful life <= 0 or cost < salvage value must raise ValueError."""
    with pytest.raises(ValueError):
        DepreciationEngine.calculate_straight_line_monthly(10000, 0, 0)

    with pytest.raises(ValueError):
        DepreciationEngine.calculate_straight_line_monthly(1000, 2000, 12)


def test_depreciation_schedule_exact_posted_match():
    """Posted depreciation matching schedule should result in VALID status."""
    engine = DepreciationEngine(tolerance=0.01)

    assets = [
        {
            "asset_id": "AST-001",
            "asset_name": "Server Cluster",
            "cost": 36000.00,
            "salvage_value": 0.0,
            "useful_life_months": 36,
            "accumulated_depreciation_prior": 10000.00,
        }
    ]
    # Expected: 36000 / 36 = 1000.00
    posted = {"AST-001": 1000.00}

    result = engine.validate_depreciation_schedule(assets, posted)
    assert result["status"] == "VALID"
    assert len(result["discrepancies"]) == 0
    assert result["total_calculated_depreciation"] == 1000.00
    assert result["total_posted_depreciation"] == 1000.00
    assert result["net_variance"] == 0.0


def test_depreciation_unposted_and_overposted_discrepancies():
    """Detect unposted entries and over-posted variances."""
    engine = DepreciationEngine(tolerance=0.01)

    assets = [
        {"asset_id": "AST-001", "asset_name": "Laptop Fleet", "cost": 12000.00, "useful_life_months": 24}, # Exp: 500.00
        {"asset_id": "AST-002", "asset_name": "Office Desks", "cost": 6000.00, "useful_life_months": 60},  # Exp: 100.00
    ]
    posted = {
        "AST-001": 0.0,     # Unposted
        "AST-002": 250.00,  # Over-posted by $150
    }

    result = engine.validate_depreciation_schedule(assets, posted)
    assert result["status"] == "DISCREPANCIES_FOUND"
    assert len(result["discrepancies"]) == 2

    unposted = next(d for d in result["discrepancies"] if d["asset_id"] == "AST-001")
    assert unposted["reason"] == "UNPOSTED_DEPRECIATION"

    overposted = next(d for d in result["discrepancies"] if d["asset_id"] == "AST-002")
    assert overposted["reason"] == "OVER_POSTED"
    assert overposted["variance"] == 150.00


def test_depreciation_fully_depreciated_edge_case():
    """Ensure fully depreciated assets flag a discrepancy if GL entries continue to post."""
    engine = DepreciationEngine(tolerance=0.01)

    assets = [
        {
            "asset_id": "AST-OLD",
            "asset_name": "Old Truck",
            "cost": 10000.00,
            "salvage_value": 0.0,
            "useful_life_months": 36,
            "accumulated_depreciation_prior": 10000.00,  # Fully depreciated
        }
    ]
    posted = {"AST-OLD": 277.78}

    result = engine.validate_depreciation_schedule(assets, posted)
    assert result["status"] == "DISCREPANCIES_FOUND"
    assert result["discrepancies"][0]["reason"] == "FULLY_DEPRECIATED_STILL_POSTING"


# ===========================================================================
# 4. Exception Generator & Severity Tests
# ===========================================================================

def test_exception_generator_severity_grading():
    """Verify deterministic severity assignment based on dollar thresholds."""
    gen = ExceptionGenerator(high_severity_threshold=1000.0, medium_severity_threshold=50.0)

    assert gen.determine_severity(1500.00) == "HIGH"
    assert gen.determine_severity(-2500.00) == "HIGH"
    assert gen.determine_severity(500.00) == "MEDIUM"
    assert gen.determine_severity(50.00) == "MEDIUM"
    assert gen.determine_severity(25.00) == "LOW"


def test_exception_generator_from_reconciliation():
    """Convert unmatched reconciliation items into FinancialException models."""
    rec_engine = ReconciliationEngine()
    gl_txs = [{"id": "gl_unmatched", "reference": "UNMATCH-1", "amount": 3500.00, "account_code": "1010"}]
    bank_txs = [{"id": "bk_unmatched", "reference": "UNMATCH-2", "amount": 80.00, "account_code": "1010"}]

    rec_result = rec_engine.reconcile(gl_txs, bank_txs)

    generator = ExceptionGenerator()
    exceptions = generator.generate_exceptions(rec_result, period="2026-01")

    assert len(exceptions) == 2
    assert all(isinstance(e, FinancialException) for e in exceptions)

    # GL exception should be HIGH severity ($3,500 >= $1,000)
    gl_exc = next(e for e in exceptions if e.metadata["source"] == "GL")
    assert gl_exc.category == "RECONCILIATION"
    assert gl_exc.severity == "HIGH"
    assert gl_exc.amount_variance == 3500.00

    # Bank exception should be MEDIUM severity ($80 >= $50)
    bk_exc = next(e for e in exceptions if e.metadata["source"] == "BANK")
    assert bk_exc.severity == "MEDIUM"
    assert bk_exc.amount_variance == 80.00


def test_exception_json_serializability():
    """Ensure FinancialException.to_dict() produces valid JSON without serialization errors."""
    exc = FinancialException(
        id="exc_test_001",
        period="2026-01",
        category="ACCRUAL",
        severity="HIGH",
        amount_variance=4500.00,
        description="Material accrual variance for AWS Cloud",
        metadata={"vendor": "AWS Cloud", "expected": 10000.00, "actual": 14500.00},
    )

    d = exc.to_dict()
    assert isinstance(d, dict)
    # Ensure json.dumps succeeds
    json_str = json.dumps(d)
    assert "exc_test_001" in json_str
    assert "AWS Cloud" in json_str
