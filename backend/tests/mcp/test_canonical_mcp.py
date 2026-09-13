"""
Canonical MCP Controlled Data Access Tests for Fixed Assets, AP Invoices, Trial Balance, and Exceptions.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import Base
from app.database.models import ExceptionRecord
from tests.canonical_fixtures import (
    ap_invoice_record,
    fixed_asset_record,
    trial_balance_record,
)
from app.mcp.tools import FinancialMCPTools


@pytest.fixture()
def test_session_factory():
    """In-memory SQLite session factory."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def tools(test_session_factory):
    return FinancialMCPTools(session_factory=test_session_factory)


@pytest.fixture()
def seeded_tools(test_session_factory):
    session = test_session_factory()
    try:
        # Fixed assets
        fixed_asset_record(
            session,
            id="fa_1",
            asset_code="FA-100",
            asset_name="Delivery Truck",
            category="VEHICLES",
            acquisition_cost=50000.0,
            salvage_value=5000.0,
            useful_life_months=60,
            status="ACTIVE",
        )
        fixed_asset_record(
            session,
            id="fa_2",
            asset_code="FA-200",
            asset_name="Office Laptop",
            category="COMPUTERS",
            acquisition_cost=2000.0,
            salvage_value=0.0,
            useful_life_months=24,
            status="DISPOSED",
        )

        # AP Invoices
        ap_invoice_record(
            session,
            id="inv_1",
            vendor_name="Acme Corp",
            invoice_number="INV-001",
            subtotal_amount=1000.0,
            tax_amount=160.0,
            total_amount=1160.0,
            status="OPEN",
        )
        ap_invoice_record(
            session,
            id="inv_2",
            vendor_name="Beta Logistics",
            invoice_number="INV-002",
            subtotal_amount=3000.0,
            tax_amount=0.0,
            total_amount=3000.0,
            status="PAID",
        )

        # Trial Balance
        trial_balance_record(
            session,
            id="tb_1",
            account_code="1010",
            account_name="Cash",
            fiscal_period="2026-01",
            closing_balance=15000.0,
        )
        trial_balance_record(
            session,
            id="tb_2",
            account_code="2010",
            account_name="Accounts Payable",
            fiscal_period="2026-01",
            closing_balance=-4160.0,
        )

        # Exceptions
        session.add(
            ExceptionRecord(
                id="exc_001",
                period="2026-01",
                category="AP_REVIEW",
                severity="HIGH",
                amount_variance=1160.0,
                description="Duplicate invoice detected",
                status="OPEN",
            )
        )
        session.commit()
    finally:
        session.close()

    return FinancialMCPTools(session_factory=test_session_factory)


def test_query_fixed_assets(seeded_tools):
    assets = asyncio.run(seeded_tools.query_fixed_assets(limit=10))
    assert len(assets) == 2
    names = [a["asset_name"] for a in assets]
    assert "Delivery Truck" in names
    assert "Office Laptop" in names

    # Filter by category
    vehicles = asyncio.run(seeded_tools.query_fixed_assets(category="VEHICLES"))
    assert len(vehicles) == 1
    assert vehicles[0]["asset_code"] == "FA-100"

    # Filter by status
    active = asyncio.run(seeded_tools.query_fixed_assets(status="ACTIVE"))
    assert len(active) == 1
    assert active[0]["status"] == "ACTIVE"


def test_query_ap_invoices(seeded_tools):
    invoices = asyncio.run(seeded_tools.query_ap_invoices(limit=10))
    assert len(invoices) == 2

    # Filter by vendor
    acme = asyncio.run(seeded_tools.query_ap_invoices(vendor_name="Acme"))
    assert len(acme) == 1
    assert acme[0]["invoice_number"] == "INV-001"

    # Filter by status
    paid = asyncio.run(seeded_tools.query_ap_invoices(status="PAID"))
    assert len(paid) == 1
    assert paid[0]["vendor_name"] == "Beta Logistics"


def test_query_trial_balance(seeded_tools):
    tb = asyncio.run(seeded_tools.query_trial_balance(fiscal_period="2026-01"))
    assert len(tb) == 2
    codes = [r["account_code"] for r in tb]
    assert "1010" in codes
    assert "2010" in codes

    # Filter by account code
    cash_tb = asyncio.run(seeded_tools.query_trial_balance(account_code="1010"))
    assert len(cash_tb) == 1
    assert cash_tb[0]["closing_balance"] == 15000.0


def test_query_exceptions(seeded_tools):
    exceptions = asyncio.run(seeded_tools.query_exceptions(category="AP_REVIEW"))
    assert len(exceptions) == 1
    assert exceptions[0]["id"] == "exc_001"
    assert exceptions[0]["severity"] == "HIGH"


def test_mcp_limit_validation(seeded_tools):
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_fixed_assets(limit=0))

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_ap_invoices(limit=150))
