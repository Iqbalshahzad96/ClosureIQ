"""
Database Session and Engine Management
"""

import logging
from pathlib import Path

def resolve_database_url(database_url):
    """Resolve file SQLite URLs relative to backend, independent of launch cwd."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        # SQLite URI filenames have their own path/connection semantics.
        if url.query.get("uri", "false").lower() != "true":
            path = Path(url.database)
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[2] / path
            url = url.set(database=str(path.resolve()))
    return url


try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    from app.config import settings

    engine = create_engine(
        resolve_database_url(settings.DATABASE_URL),
        connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except ImportError:
    engine = None
    SessionLocal = None
    class Base:
        metadata = None


def initialize_database(bind=None):
    """Create missing tables on the API engine without deleting existing data.

    This is additive initialization, not a migration of existing columns.
    Import all models before inspecting metadata, including AuditEvent.
    """
    from app.database import models

    target = engine if bind is None else bind
    if target is None or Base.metadata is None:
        raise RuntimeError("SQLAlchemy is required for database initialization")
    if Base.metadata.tables.get("audit_events") is not models.AuditEvent.__table__:
        raise RuntimeError("AuditEvent is not registered in database metadata")
    Base.metadata.create_all(bind=target)
    if target.dialect.name == "sqlite":
        with target.connect() as connection:
            databases = connection.exec_driver_sql("PRAGMA database_list").all()
        logging.getLogger("closureiq.database").info("SQLite schema initialized; database_list=%s", databases)


def get_db():
    """Dependency for providing database sessions to API routes."""
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
