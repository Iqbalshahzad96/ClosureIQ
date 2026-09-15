"""
Database Seeding Script for ClosureIQ
Initializes SQLite database tables and seeds presentation-ready demo data into an explicit target database.
"""

import argparse
import os
import sys
from pathlib import Path

# Add backend directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database.database import Base
from app.database.demo_seed import (
    seed_demo_reconciliation_data,
    DEMO_ACCOUNT_CODE,
    DEMO_PERIOD,
)


def seed(
    database: str | Path | None = None,
    drop_existing: bool = False,
    seed_demo: bool = False,
    engine=None,
):
    """Create tables and optionally seed canonical demo reconciliation records into target database."""
    if engine is None:
        if not database:
            raise ValueError("An explicit target database path must be provided.")
        resolved_path = Path(database).resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{resolved_path.as_posix()}"
        target_engine = create_engine(db_url, connect_args={"check_same_thread": False})
        own_engine = True
    else:
        target_engine = engine
        own_engine = False

    try:
        if drop_existing:
            print("Dropping existing tables...")
            Base.metadata.drop_all(bind=target_engine)
            Base.metadata.create_all(bind=target_engine)
            print("Database tables created successfully.")
        else:
            print("Ensuring database schema exists...")
            Base.metadata.create_all(bind=target_engine)
            print("Database tables validated.")

        if seed_demo:
            with Session(target_engine) as session:
                counts = seed_demo_reconciliation_data(session)
                session.commit()
                print(f"Successfully seeded demo reconciliation data for {DEMO_ACCOUNT_CODE} (Period: {DEMO_PERIOD}):")
                for k, v in counts.items():
                    print(f"  - {k}: {v}")
    finally:
        if own_engine:
            target_engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="ClosureIQ Database Seeding Utility")
    parser.add_argument(
        "--database",
        "-d",
        type=str,
        default=None,
        help="Explicit SQLite database file path (e.g. backend/closureiq_manual_verification.db)",
    )
    parser.add_argument(
        "--demo-recon",
        action="store_true",
        default=False,
        help="Seed controlled synthetic reconciliation data (requires explicit --database)",
    )
    parser.add_argument(
        "--drop-tables",
        action="store_true",
        default=False,
        help="Drop tables before creating (caution: resets database)",
    )
    args = parser.parse_args(argv)

    if not args.database:
        if args.demo_recon:
            parser.error("--demo-recon requires an explicit target database via --database")
        else:
            parser.error("A target database path must be specified via --database")

    seed(
        database=args.database,
        drop_existing=args.drop_tables,
        seed_demo=args.demo_recon,
    )


if __name__ == "__main__":
    main()
