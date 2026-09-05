"""
Database Session and Engine Management
"""

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    from app.config import settings

    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except ImportError:
    engine = None
    SessionLocal = None
    class Base:
        metadata = None


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
