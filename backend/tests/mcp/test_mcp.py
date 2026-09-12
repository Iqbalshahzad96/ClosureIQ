"""
MCP Controlled Data Access Layer Tests

Uses in-memory SQLite with StaticPool so the same connection is shared
across all sessions within a test. Seeds real rows and asserts actual
query results, ISO-8601 serialization, and JSON serializability.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Import Base and models from the application.
# Models register themselves on Base when imported.
from app.database.database import Base
from app.database.models import ExceptionRecord
from tests.canonical_fixtures import financial_record
from app.mcp.tools import FinancialMCPTools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_session_factory():
    """Create an in-memory SQLite engine with StaticPool, create all tables,
    and return a session factory bound to it."""
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
    """Return a FinancialMCPTools instance backed by the test DB."""
    return FinancialMCPTools(session_factory=test_session_factory)


@pytest.fixture()
def seeded_session_factory(test_session_factory):
    """Seed the test DB with sample GL, BANK, and exception records.

    GL rows for account 1010 (3 rows) and 2020 (1 row).
    BANK rows for account 1010 (2 rows) and 2020 (1 row).
    One exception record.
    """
    session = test_session_factory()
    try:
        # GL transactions for account 1010
        session.add_all([
            financial_record(session,
                id="gl_001", source="GL", account_code="1010",
                transaction_date=datetime(2026, 1, 15, 10, 0, 0),
                amount=1000.00, description="Invoice A", reference="INV-001",
                is_reconciled=False,
            ),
            financial_record(session,
                id="gl_002", source="GL", account_code="1010",
                transaction_date=datetime(2026, 2, 20, 14, 30, 0),
                amount=2500.50, description="Invoice B", reference="INV-002",
                is_reconciled=True,
            ),
            financial_record(session,
                id="gl_003", source="GL", account_code="1010",
                transaction_date=datetime(2026, 3, 5, 9, 0, 0),
                amount=-500.00, description="Credit note", reference="CN-001",
                is_reconciled=False,
            ),
        ])

        # GL transaction for a different account
        session.add(
            financial_record(session,
                id="gl_004", source="GL", account_code="2020",
                transaction_date=datetime(2026, 1, 10, 8, 0, 0),
                amount=750.00, description="Other account", reference="OTH-001",
                is_reconciled=False,
            )
        )

        # BANK transactions for account 1010
        session.add_all([
            financial_record(session,
                id="bank_001", source="BANK", account_code="1010",
                transaction_date=datetime(2026, 1, 16, 12, 0, 0),
                amount=1000.00, description="Deposit A", reference="DEP-001",
                is_reconciled=False,
            ),
            financial_record(session,
                id="bank_002", source="BANK", account_code="1010",
                transaction_date=datetime(2026, 2, 21, 11, 0, 0),
                amount=2500.50, description="Deposit B", reference="DEP-002",
                is_reconciled=True,
            ),
        ])

        # BANK transaction for a different account (2020)
        session.add(
            financial_record(session,
                id="bank_003", source="BANK", account_code="2020",
                transaction_date=datetime(2026, 1, 17, 9, 30, 0),
                amount=750.00, description="Deposit C", reference="DEP-003",
                is_reconciled=False,
            )
        )

        # Exception record
        session.add(
            ExceptionRecord(
                id="exc_100", period="2026-Q1", category="UNRECONCILED",
                severity="HIGH", amount_variance=1500.00,
                description="Unmatched GL entry", status="OPEN",
                created_at=datetime(2026, 3, 10, 16, 0, 0),
            )
        )

        session.commit()
    finally:
        session.close()

    return test_session_factory


@pytest.fixture()
def seeded_tools(seeded_session_factory):
    """Return a FinancialMCPTools instance backed by the seeded test DB."""
    return FinancialMCPTools(session_factory=seeded_session_factory)


# ---------------------------------------------------------------------------
# GL transaction tests
# ---------------------------------------------------------------------------


def test_gl_transactions_filters_by_source_and_account(seeded_tools):
    """Only GL rows for the requested account are returned."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010"))
    assert len(result) == 3
    assert all(r["source"] == "GL" for r in result)
    assert all(r["account_code"] == "1010" for r in result)


def test_gl_transactions_excludes_other_accounts(seeded_tools):
    """GL rows for a different account are not included."""
    result = asyncio.run(seeded_tools.query_gl_transactions("2020"))
    assert len(result) == 1
    assert result[0]["id"] == "gl_004"


def test_gl_transactions_respects_limit(seeded_tools):
    """Limit caps the number of returned rows."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010", limit=2))
    assert len(result) == 2


def test_gl_transactions_ordered_by_date_desc(seeded_tools):
    """Results are ordered by transaction_date descending."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010"))
    dates = [r["transaction_date"] for r in result]
    assert dates == sorted(dates, reverse=True)


def test_gl_transactions_empty_for_unknown_account(tools):
    """An account with no rows returns an empty list."""
    result = asyncio.run(tools.query_gl_transactions("9999"))
    assert result == []


# ---------------------------------------------------------------------------
# GL limit validation
# ---------------------------------------------------------------------------


def test_gl_limit_1_succeeds(seeded_tools):
    """limit=1 is the minimum valid value and should succeed."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010", limit=1))
    assert len(result) == 1


def test_gl_limit_100_succeeds(seeded_tools):
    """limit=100 is the maximum valid value and should succeed."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010", limit=100))
    assert len(result) == 3  # only 3 GL rows seeded for 1010


def test_gl_limit_0_raises_value_error(seeded_tools):
    """limit=0 is below minimum and must raise ValueError."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_gl_transactions("1010", limit=0))


def test_gl_limit_negative_raises_value_error(seeded_tools):
    """limit=-1 is below minimum and must raise ValueError."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_gl_transactions("1010", limit=-1))


def test_gl_limit_101_raises_value_error(seeded_tools):
    """limit=101 exceeds maximum and must raise ValueError."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_gl_transactions("1010", limit=101))


# ---------------------------------------------------------------------------
# BANK transaction tests
# ---------------------------------------------------------------------------


def test_bank_transactions_filters_by_source_and_account(seeded_tools):
    """Only BANK rows for the requested account are returned."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010"))
    assert len(result) == 2
    assert all(r["source"] == "BANK" for r in result)
    assert all(r["account_code"] == "1010" for r in result)


def test_bank_transactions_excludes_gl_rows(seeded_tools):
    """GL rows are never returned by the bank tool."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010"))
    assert all(r["source"] == "BANK" for r in result)


def test_bank_transactions_excludes_other_accounts(seeded_tools):
    """BANK rows for a different account are not included."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010"))
    ids = {r["id"] for r in result}
    assert "bank_003" not in ids  # bank_003 belongs to account 2020


def test_bank_transactions_ordered_by_date_desc(seeded_tools):
    """BANK results are ordered by transaction_date descending."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010"))
    dates = [r["transaction_date"] for r in result]
    assert dates == sorted(dates, reverse=True)


def test_bank_transactions_respects_limit(seeded_tools):
    """Limit caps the number of returned BANK rows."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010", limit=1))
    assert len(result) == 1


# ---------------------------------------------------------------------------
# BANK limit validation
# ---------------------------------------------------------------------------


def test_bank_limit_1_succeeds(seeded_tools):
    """limit=1 is the minimum valid value for BANK and should succeed."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010", limit=1))
    assert len(result) == 1


def test_bank_limit_100_succeeds(seeded_tools):
    """limit=100 is the maximum valid value for BANK and should succeed."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010", limit=100))
    assert len(result) == 2  # only 2 BANK rows seeded for 1010


def test_bank_limit_0_raises_value_error(seeded_tools):
    """limit=0 is below minimum for BANK and must raise ValueError."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_bank_transactions("1010", limit=0))


def test_bank_limit_negative_raises_value_error(seeded_tools):
    """limit=-1 is below minimum for BANK and must raise ValueError."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_bank_transactions("1010", limit=-1))


def test_bank_limit_101_raises_value_error(seeded_tools):
    """limit=101 exceeds maximum for BANK and must raise ValueError."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        asyncio.run(seeded_tools.query_bank_transactions("1010", limit=101))


# ---------------------------------------------------------------------------
# Exception detail tests
# ---------------------------------------------------------------------------


def test_exception_details_found(seeded_tools):
    """An existing exception returns all fields and found=True."""
    result = asyncio.run(seeded_tools.get_exception_details("exc_100"))
    assert result["found"] is True
    assert result["exception_id"] == "exc_100"
    assert result["period"] == "2026-Q1"
    assert result["category"] == "UNRECONCILED"
    assert result["severity"] == "HIGH"
    assert result["amount_variance"] == 1500.00
    assert result["description"] == "Unmatched GL entry"
    assert result["status"] == "OPEN"
    assert "created_at" in result


def test_exception_details_not_found(tools):
    """A missing exception returns found=False."""
    result = asyncio.run(tools.get_exception_details("nonexistent"))
    assert result["found"] is False
    assert result["exception_id"] == "nonexistent"


# ---------------------------------------------------------------------------
# ISO-8601 serialization and JSON safety
# ---------------------------------------------------------------------------


def test_transaction_dates_are_iso_strings(seeded_tools):
    """transaction_date values are ISO-8601 strings, not datetime objects."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010"))
    for row in result:
        dt_str = row["transaction_date"]
        assert isinstance(dt_str, str)
        # Must parse back without error
        datetime.fromisoformat(dt_str)


def test_exception_created_at_is_iso_string(seeded_tools):
    """created_at on exceptions is an ISO-8601 string."""
    result = asyncio.run(seeded_tools.get_exception_details("exc_100"))
    assert isinstance(result["created_at"], str)
    datetime.fromisoformat(result["created_at"])


def test_gl_result_is_json_serializable(seeded_tools):
    """The entire GL result can be passed through json.dumps without error."""
    result = asyncio.run(seeded_tools.query_gl_transactions("1010"))
    serialized = json.dumps(result)
    assert isinstance(serialized, str)


def test_bank_result_is_json_serializable(seeded_tools):
    """The entire BANK result can be passed through json.dumps without error."""
    result = asyncio.run(seeded_tools.query_bank_transactions("1010"))
    serialized = json.dumps(result)
    assert isinstance(serialized, str)


def test_exception_result_is_json_serializable(seeded_tools):
    """The exception result can be passed through json.dumps without error."""
    result = asyncio.run(seeded_tools.get_exception_details("exc_100"))
    serialized = json.dumps(result)
    assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# get_account_balance — blocked
# ---------------------------------------------------------------------------


def test_get_account_balance_raises_not_implemented(tools):
    """get_account_balance must raise NotImplementedError until the
    period-to-date-range contract is resolved."""
    with pytest.raises(NotImplementedError, match="period"):
        asyncio.run(tools.get_account_balance("1010", "2026-Q1"))


# ---------------------------------------------------------------------------
# MCPServer tool registration (public SDK v2.1.1 API)
# ---------------------------------------------------------------------------


def test_mcp_server_registers_exactly_three_tools():
    """The MCPServer instance exposes exactly the 3 implemented tools.
    get_account_balance must NOT be registered.
    Uses the public ``await mcp.list_tools()`` API from MCP SDK v2.1.1."""
    from app.mcp.server import mcp

    async def _list():
        tools = await mcp.list_tools()
        return {t.name for t in tools}

    registered = asyncio.run(_list())
    expected = {"query_gl_transactions", "query_bank_transactions", "get_exception_details"}
    assert registered == expected, (
        f"Expected tools {expected}, but got {registered}"
    )