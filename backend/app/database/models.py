"""
SQLAlchemy Database Models for Financial Records, Exceptions, and Traces
"""

try:
    from sqlalchemy import Column, String, Float, DateTime, Boolean, Text, JSON
    from datetime import datetime
    from app.database.database import Base

    class FinancialRecord(Base):
        """General Ledger and Bank Statement transactions."""
        __tablename__ = "financial_records"

        id = Column(String, primary_key=True, index=True)
        source = Column(String, nullable=False)  # "GL" | "BANK"
        account_code = Column(String, nullable=False, index=True)
        transaction_date = Column(DateTime, default=datetime.utcnow)
        amount = Column(Float, nullable=False)
        description = Column(String, default="")
        reference = Column(String, default="")
        is_reconciled = Column(Boolean, default=False)


    class ExceptionRecord(Base):
        """Detected financial anomalies and exceptions."""
        __tablename__ = "exception_records"

        id = Column(String, primary_key=True, index=True)
        period = Column(String, nullable=False, index=True)
        category = Column(String, nullable=False)
        severity = Column(String, default="MEDIUM")
        amount_variance = Column(Float, default=0.0)
        description = Column(Text, default="")
        status = Column(String, default="OPEN")  # OPEN, IN_REVIEW, RESOLVED
        created_at = Column(DateTime, default=datetime.utcnow)


    class AuditTrailRecord(Base):
        """Observability trace and human decision logs."""
        __tablename__ = "audit_trail_records"

        id = Column(String, primary_key=True, index=True)
        run_id = Column(String, index=True, nullable=False)
        event_type = Column(String, nullable=False)  # AGENT_DECISION, HITL_APPROVAL, ERROR
        details = Column(JSON, default=dict)
        created_at = Column(DateTime, default=datetime.utcnow)

except ImportError:
    class FinancialRecord:
        pass

    class ExceptionRecord:
        pass

    class AuditTrailRecord:
        pass
