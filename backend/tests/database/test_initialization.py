"""Regression coverage for API startup against an uninitialized SQLite file."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.database import database
from app.database.models import AuditEvent
from app import main
from app.services import workflow_service


def test_relative_sqlite_path_does_not_depend_on_cwd(tmp_path, monkeypatch):
    expected = Path(database.__file__).resolve().parents[2] / "closureiq.db"
    monkeypatch.chdir(tmp_path)
    assert Path(database.resolve_database_url("sqlite:///./closureiq.db").database) == expected
    absolute = tmp_path / "explicit.db"
    assert Path(database.resolve_database_url(f"sqlite:///{absolute}").database) == absolute
    assert database.resolve_database_url("sqlite:///:memory:").database == ":memory:"
    uri = "sqlite:///file:shared?mode=memory&cache=shared&uri=true"
    assert database.resolve_database_url(uri).database == "file:shared"


def test_initialization_adds_missing_audit_table_and_preserves_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    try:
        database.Base.metadata.create_all(
            engine,
            tables=[table for table in database.Base.metadata.sorted_tables
                    if table.name != "audit_events"],
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE existing_data (value TEXT)")
            connection.exec_driver_sql("INSERT INTO existing_data VALUES ('keep me')")
        assert not inspect(engine).has_table("audit_events")
        database.initialize_database(engine)
        factory = sessionmaker(bind=engine)
        with factory.begin() as session:
            session.add(AuditEvent(id="preserved-audit", event_type="TEST"))
        database.initialize_database(engine)
        with factory() as session:
            assert session.get(AuditEvent, "preserved-audit").event_type == "TEST"
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT value FROM existing_data").scalar_one() == "keep me"
        assert {fk["referred_table"] for fk in inspect(engine).get_foreign_keys("audit_events")} == {
            "reconciliation_runs", "import_batches", "exception_records",
        }
    finally:
        engine.dispose()


def test_startup_initializes_api_database_and_run_persists_audit(tmp_path, monkeypatch):
    path = tmp_path / "api.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(workflow_service, "SessionLocal", factory)
    try:
        assert not inspect(engine).has_table("audit_events")
        with TestClient(main.create_application()) as client:
            response = client.post("/api/v1/reconciliation/run", json={
                "account_code": "schema-test", "period": "2026-Q1", "run_id": "startup-test",
            })
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "clean_close"
        with factory() as session:
            events = session.scalars(select(AuditEvent).where(AuditEvent.run_id == "startup-test")).all()
            assert {event.event_type for event in events} == {"RUN_STARTED", "RUN_COMPLETED"}
        with engine.connect() as connection:
            databases = {row[1]: row[2] for row in connection.exec_driver_sql("PRAGMA database_list")}
            assert Path(databases["main"]) == path
    finally:
        engine.dispose()
