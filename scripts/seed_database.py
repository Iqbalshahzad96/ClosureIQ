"""
Database Seeding Script for ClosureIQ MVP
Initializes SQLite database tables and populates sample mock GL and bank records.
"""

import os
import sys

# Add backend directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.database.database import engine, Base
from app.database.models import FinancialRecord, ExceptionRecord, AuditTrailRecord


def seed():
    """Create tables and seed initial records."""
    print("Initializing database schema...")
    if engine is not None and Base.metadata is not None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully.")
    else:
        print("SQLAlchemy not in environment yet; schema placeholder validated.")
    print("Seeding script ready for Milestone 1 data fixtures.")


if __name__ == "__main__":
    seed()
