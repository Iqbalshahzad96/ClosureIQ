"""
Deterministic AP Engine and Duplicate Detection Tests
"""

from __future__ import annotations

from datetime import datetime
import pytest

from app.financial_engine.ap import APEngine
from app.financial_engine.exceptions import ExceptionGenerator


def test_ap_engine_empty_inputs():
    """Empty invoice list should return clean zeroed summary without errors."""
    engine = APEngine(tolerance=0.01)
    result = engine.validate_ap_invoices([])

    assert result["total_invoices"] == 0
    assert result["valid_invoices_count"] == 0
    assert result["duplicates_count"] == 0
    assert result["calculation_errors_count"] == 0
    assert result["payment_discrepancies_count"] == 0
    assert result["overdue_invoices_count"] == 0
    assert result["total_amount"] == 0.0
    assert result["status"] == "CLEAN"


def test_ap_engine_clean_valid_invoices():
    """Valid invoices without calculation errors or duplicates should pass cleanly."""
    engine = APEngine(tolerance=0.01)
    invoices = [
        {
            "id": "inv_1",
            "vendor_name": "Supplier A",
            "invoice_number": "INV-001",
            "invoice_date": "2026-01-10",
            "due_date": "2026-02-10",
            "subtotal_amount": 1000.00,
            "tax_amount": 160.00,
            "total_amount": 1160.00,
            "paid_amount": 1160.00,
            "outstanding_amount": 0.00,
            "status": "PAID",
        },
        {
            "id": "inv_2",
            "vendor_name": "Supplier B",
            "invoice_number": "INV-002",
            "invoice_date": "2026-01-15",
            "due_date": "2026-02-15",
            "subtotal_amount": 500.00,
            "tax_amount": 80.00,
            "total_amount": 580.00,
            "paid_amount": 0.00,
            "outstanding_amount": 580.00,
            "status": "OPEN",
        },
    ]

    result = engine.validate_ap_invoices(invoices, as_of_date="2026-01-20")

    assert result["total_invoices"] == 2
    assert result["valid_invoices_count"] == 2
    assert result["duplicates_count"] == 0
    assert result["calculation_errors_count"] == 0
    assert result["status"] == "CLEAN"


def test_ap_engine_exact_duplicate_invoice_number():
    """Exact duplicate invoice number for the same vendor should be flagged."""
    engine = APEngine(tolerance=0.01)
    invoices = [
        {
            "id": "inv_1",
            "vendor_name": "Acme Corp",
            "invoice_number": "INV-999",
            "subtotal_amount": 1000.00,
            "tax_amount": 160.00,
            "total_amount": 1160.00,
        },
        {
            "id": "inv_2",
            "vendor_name": "Acme Corp",
            "invoice_number": "INV-999",
            "subtotal_amount": 1000.00,
            "tax_amount": 160.00,
            "total_amount": 1160.00,
        },
    ]

    result = engine.validate_ap_invoices(invoices)

    assert result["duplicates_count"] == 1
    assert result["duplicates"][0]["type"] == "EXACT_DUPLICATE_INVOICE_NUMBER"
    assert result["status"] == "DISCREPANCIES_DETECTED"


def test_ap_engine_suspect_duplicate_billing():
    """Same vendor, amount, and date with different invoice numbers is flagged as suspect duplicate."""
    engine = APEngine(tolerance=0.01)
    invoices = [
        {
            "id": "inv_1",
            "vendor_name": "Vendor XYZ",
            "invoice_number": "INV-001",
            "invoice_date": "2026-01-10",
            "subtotal_amount": 2500.00,
            "tax_amount": 0.00,
            "total_amount": 2500.00,
        },
        {
            "id": "inv_2",
            "vendor_name": "Vendor XYZ",
            "invoice_number": "INV-002",
            "invoice_date": "2026-01-10",
            "subtotal_amount": 2500.00,
            "tax_amount": 0.00,
            "total_amount": 2500.00,
        },
    ]

    result = engine.validate_ap_invoices(invoices)

    assert result["duplicates_count"] == 1
    assert result["duplicates"][0]["type"] == "SUSPECT_DUPLICATE_BILLING"


def test_ap_engine_calculation_mismatch():
    """Subtotal + Tax != Total should be flagged."""
    engine = APEngine(tolerance=0.01)
    invoices = [
        {
            "id": "inv_err",
            "vendor_name": "Vendor Calc",
            "invoice_number": "INV-MATH",
            "subtotal_amount": 1000.00,
            "tax_amount": 160.00,
            "total_amount": 1200.00,  # Should be 1160.00
        }
    ]

    result = engine.validate_ap_invoices(invoices)

    assert result["calculation_errors_count"] == 1
    assert result["calculation_errors"][0]["type"] == "SUBTOTAL_TAX_SUM_MISMATCH"
    assert result["calculation_errors"][0]["variance_amount"] == 40.00
    assert result["status"] == "DISCREPANCIES_DETECTED"


def test_ap_engine_payment_discrepancies():
    """Overpayment and balance mismatches should be flagged."""
    engine = APEngine(tolerance=0.01)
    invoices = [
        {
            "id": "inv_over",
            "vendor_name": "Vendor Pmt",
            "invoice_number": "INV-OVER",
            "subtotal_amount": 100.00,
            "tax_amount": 0.00,
            "total_amount": 100.00,
            "paid_amount": 150.00,  # Overpaid by 50.00
            "outstanding_amount": 0.00,
        }
    ]

    result = engine.validate_ap_invoices(invoices)

    assert result["payment_discrepancies_count"] == 1
    assert result["payment_discrepancies"][0]["type"] == "OVERPAYMENT_DETECTED"


def test_ap_engine_exception_generation():
    """APEngine outputs should convert cleanly to structured FinancialExceptions."""
    engine = APEngine(tolerance=0.01)
    generator = ExceptionGenerator()

    invoices = [
        {
            "id": "inv_dup1",
            "vendor_name": "Vendor A",
            "invoice_number": "INV-DUP",
            "subtotal_amount": 1500.00,
            "tax_amount": 0.00,
            "total_amount": 1500.00,
        },
        {
            "id": "inv_dup2",
            "vendor_name": "Vendor A",
            "invoice_number": "INV-DUP",
            "subtotal_amount": 1500.00,
            "tax_amount": 0.00,
            "total_amount": 1500.00,
        },
    ]

    ap_report = engine.validate_ap_invoices(invoices)
    exceptions = generator.generate_exceptions(ap_report, period="2026-01", category="AP_REVIEW")

    assert len(exceptions) == 1
    exc = exceptions[0]
    assert exc.category == "AP_REVIEW"
    assert exc.severity == "HIGH"
    assert exc.amount_variance == 1500.00
    assert "Duplicate invoice number" in exc.description
