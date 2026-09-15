"""
Tests for Controlled Synthetic Reconciliation Demo Data.
Verifies idempotency, MCP queries for GL and Bank records on DEMO-BANK-1010,
deterministic matching with deliberate exceptions in period 2025-12,
and guarantees that no original Enquest files/data are modified.
"""

from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import Base
from app.database.models import Account, BankAccount, BankTransaction, JournalEntry, JournalLine, TrialBalanceRecord
from app.database.demo_seed import seed_demo_reconciliation_data, DEMO_ACCOUNT_CODE, DEMO_PERIOD
from app.financial_engine.reconciliation import ReconciliationEngine
from app.mcp.tools import FinancialMCPTools


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session, factory
    session.close()
    engine.dispose()


def test_demo_seed_is_idempotent(test_db):
    """Running seed_demo_reconciliation_data repeatedly must not duplicate records."""
    session, _ = test_db

    # First run
    counts_first = seed_demo_reconciliation_data(session)
    session.commit()

    gl_lines_first = session.query(JournalLine).count()
    bank_tx_first = session.query(BankTransaction).count()
    accounts_first = session.query(Account).filter_by(account_code=DEMO_ACCOUNT_CODE).count()
    tb_first = session.query(TrialBalanceRecord).filter_by(fiscal_period=DEMO_PERIOD).count()

    assert gl_lines_first == 5
    assert bank_tx_first == 5
    assert accounts_first == 1
    assert tb_first == 1

    # Second run (must be completely idempotent)
    counts_second = seed_demo_reconciliation_data(session)
    session.commit()

    assert session.query(JournalLine).count() == gl_lines_first
    assert session.query(BankTransaction).count() == bank_tx_first
    assert session.query(Account).filter_by(account_code=DEMO_ACCOUNT_CODE).count() == accounts_first
    assert session.query(TrialBalanceRecord).filter_by(fiscal_period=DEMO_PERIOD).count() == tb_first


@pytest.mark.asyncio
async def test_mcp_returns_both_gl_and_bank_records_for_demo_account(test_db):
    """MCP tools return both GL and Bank records for the same DEMO-BANK-1010 account."""
    session, factory = test_db
    seed_demo_reconciliation_data(session)
    session.commit()

    mcp = FinancialMCPTools(session_factory=factory, organization_id="default_org")

    gl_records = await mcp.query_gl_transactions(account_code=DEMO_ACCOUNT_CODE, limit=50)
    bank_records = await mcp.query_bank_transactions(account_code=DEMO_ACCOUNT_CODE, limit=50)

    assert len(gl_records) == 5, f"Expected 5 GL records, got {len(gl_records)}"
    assert len(bank_records) == 5, f"Expected 5 Bank records, got {len(bank_records)}"

    gl_refs = {r["reference"] for r in gl_records}
    bank_refs = {r["reference"] for r in bank_records}

    assert "DEMO-TX-001" in gl_refs and "DEMO-TX-001" in bank_refs
    assert "DEMO-GL-ONLY" in gl_refs
    assert "DEMO-GL-ONLY" not in bank_refs
    assert "DEMO-BANK-FEE" in bank_refs
    assert "DEMO-BANK-FEE" not in gl_refs


@pytest.mark.asyncio
async def test_reconciliation_engine_produces_matches_and_deliberate_exceptions(test_db):
    """Reconciliation produces 4 matched pairs, 1 GL exception, and 1 Bank exception."""
    session, factory = test_db
    seed_demo_reconciliation_data(session)
    session.commit()

    mcp = FinancialMCPTools(session_factory=factory, organization_id="default_org")
    gl_records = await mcp.query_gl_transactions(account_code=DEMO_ACCOUNT_CODE, limit=50)
    bank_records = await mcp.query_bank_transactions(account_code=DEMO_ACCOUNT_CODE, limit=50)

    engine = ReconciliationEngine(tolerance=0.01)
    report = engine.reconcile(gl_transactions=gl_records, bank_transactions=bank_records)

    matched = report.get("matched", [])
    unmatched_gl = report.get("unmatched_gl", [])
    unmatched_bank = report.get("unmatched_bank", [])

    assert len(matched) == 4, f"Expected 4 matched transactions, got {len(matched)}"
    assert len(unmatched_gl) == 1, f"Expected 1 unmatched GL exception, got {len(unmatched_gl)}"
    assert len(unmatched_bank) == 1, f"Expected 1 unmatched Bank exception, got {len(unmatched_bank)}"

    assert unmatched_gl[0]["reference"] == "DEMO-GL-ONLY"
    assert unmatched_bank[0]["reference"] == "DEMO-BANK-FEE"


def test_no_original_enquest_files_rewritten(test_db):
    """Ensure no Enquest or source files are modified during seeding."""
    session, _ = test_db
    enquest_dir = Path(__file__).resolve().parents[3] / "data"

    # Capture initial modification times if data directory exists
    mtimes_before = {}
    if enquest_dir.exists():
        for p in enquest_dir.rglob("*"):
            if p.is_file():
                mtimes_before[str(p)] = p.stat().st_mtime_ns

    seed_demo_reconciliation_data(session)
    session.commit()

    if enquest_dir.exists():
        for path_str, before_mtime in mtimes_before.items():
            current_mtime = Path(path_str).stat().st_mtime_ns
            assert current_mtime == before_mtime, f"File {path_str} was modified by demo seed"


import subprocess
import sys
from sqlalchemy.orm import Session


def test_cli_no_demo_flag_means_no_demo_insertion(tmp_path):
    """a) no demo flag means no demo insertion."""
    target_db = tmp_path / "test_no_demo.db"
    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_database.py"
    res = subprocess.run(
        [sys.executable, str(script), "--database", str(target_db)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert target_db.exists()

    test_engine = create_engine(f"sqlite:///{target_db.resolve().as_posix()}")
    with Session(test_engine) as session:
        assert session.query(Account).filter_by(account_code=DEMO_ACCOUNT_CODE).count() == 0
        assert session.query(JournalLine).count() == 0
        assert session.query(BankTransaction).count() == 0
    test_engine.dispose()


def test_cli_demo_flag_without_explicit_database_rejected():
    """b) demo flag without explicit database is rejected."""
    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_database.py"
    res = subprocess.run(
        [sys.executable, str(script), "--demo-recon"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "--database" in (res.stderr + res.stdout)


def test_cli_explicit_target_database_receives_records(tmp_path):
    """c) the explicit target database receives records."""
    target_db = tmp_path / "target_seeded.db"
    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_database.py"
    res = subprocess.run(
        [sys.executable, str(script), "--demo-recon", "--database", str(target_db)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert target_db.exists()

    test_engine = create_engine(f"sqlite:///{target_db.resolve().as_posix()}")
    with Session(test_engine) as session:
        assert session.query(Account).filter_by(account_code=DEMO_ACCOUNT_CODE).count() == 1
        assert session.query(JournalLine).count() == 5
        assert session.query(BankTransaction).count() == 5
        assert session.query(TrialBalanceRecord).filter_by(fiscal_period=DEMO_PERIOD).count() == 1
    test_engine.dispose()


def test_cli_another_database_untouched(tmp_path):
    """d) another/default database is untouched."""
    other_db = tmp_path / "other_database.db"
    other_engine = create_engine(f"sqlite:///{other_db.resolve().as_posix()}")
    Base.metadata.create_all(other_engine)
    with Session(other_engine) as s:
        s.add(Account(account_code="OTHER-9999", account_name="Untouched Account", normalized_name="untouched account", account_type="ASSET", currency_code="USD"))
        s.commit()
    other_mtime_before = other_db.stat().st_mtime_ns
    other_engine.dispose()

    target_db = tmp_path / "target_recon.db"
    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_database.py"
    res = subprocess.run(
        [sys.executable, str(script), "--demo-recon", "--database", str(target_db)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert target_db.exists()

    assert other_db.stat().st_mtime_ns == other_mtime_before
    check_engine = create_engine(f"sqlite:///{other_db.resolve().as_posix()}")
    with Session(check_engine) as s:
        assert s.query(Account).filter_by(account_code="OTHER-9999").count() == 1
        assert s.query(Account).filter_by(account_code=DEMO_ACCOUNT_CODE).count() == 0
        assert s.query(JournalLine).count() == 0
        assert s.query(BankTransaction).count() == 0
    check_engine.dispose()


def test_cli_repeated_seeding_remains_idempotent(tmp_path):
    """e) repeated seeding remains idempotent."""
    target_db = tmp_path / "idempotent_test.db"
    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_database.py"

    res1 = subprocess.run(
        [sys.executable, str(script), "--demo-recon", "--database", str(target_db)],
        capture_output=True,
        text=True,
    )
    assert res1.returncode == 0

    res2 = subprocess.run(
        [sys.executable, str(script), "--demo-recon", "--database", str(target_db)],
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0

    test_engine = create_engine(f"sqlite:///{target_db.resolve().as_posix()}")
    with Session(test_engine) as session:
        assert session.query(Account).filter_by(account_code=DEMO_ACCOUNT_CODE).count() == 1
        assert session.query(JournalLine).count() == 5
        assert session.query(BankTransaction).count() == 5
        assert session.query(TrialBalanceRecord).filter_by(fiscal_period=DEMO_PERIOD).count() == 1
    test_engine.dispose()
