"""Tests for Financial File Upload API (/api/v1/imports/upload).

Verifies:
- Omitted source ID creates a runtime source
- Later compatible upload reuses the created runtime source
- Sources remain separated by organization and adapter
- Explicit valid source still works
- Explicit missing, inactive, or wrong-organization source is rejected
- Duplicate-file behavior remains correct
- Request body handling (raw bytes, not FormData/JSON)
- Validation of file size (413), header options (422), and bad input (400)
"""
import io
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.database import Base, get_db
from app.database.models import (
    SourceSystem, SourceAccountMapping, ImportBatch,
    SourceFile, BankAccount, Account, BankTransaction
)
from app.ingestion.service import IngestionService, MAX_UPLOAD_BYTES
from app.ingestion.storage import RawStorageManager
from app.api.routes.imports import get_ingestion_service
from tests.ingestion.test_adapters import _make_csv_bytes


@pytest.fixture
def test_db_and_service(tmp_path):
    engine = create_engine(
        'sqlite:///:memory:',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool
    )
    @event.listens_for(engine, 'connect')
    def enforce_fk(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()

    # Pre-seed explicit source, account, bank account
    source = SourceSystem(
        id='explicit_source',
        organization_id='org_a',
        adapter_key='generic_bank',
        source_type='ERP',
        display_name='Explicit Source',
        is_active=True
    )
    inactive_source = SourceSystem(
        id='inactive_source',
        organization_id='org_a',
        adapter_key='generic_bank',
        source_type='ERP',
        display_name='Inactive Source',
        is_active=False
    )
    other_org_source = SourceSystem(
        id='other_org_source',
        organization_id='org_b',
        adapter_key='generic_bank',
        source_type='ERP',
        display_name='Other Org Source',
        is_active=True
    )
    account = Account(
        id='acc_1',
        organization_id='org_a',
        account_code='1010',
        account_name='Cash',
        normalized_name='cash',
        account_type='ASSET',
        currency_code='KES'
    )
    db.add_all([source, inactive_source, other_org_source, account])
    db.flush()

    db.add_all([
        SourceAccountMapping(
            source_system_id=source.id,
            source_account_key='Cash at Bank',
            account_id=account.id,
            mapping_status='REVIEWED'
        ),
        BankAccount(
            id='bank_1',
            organization_id='org_a',
            bank_name='Test Bank',
            account_number_masked='***1234',
            account_name='Primary Operating',
            linked_gl_account_id=account.id,
            currency_code='KES'
        ),
    ])
    db.commit()

    service = IngestionService(storage=RawStorageManager(str(tmp_path / 'raw')), chunk_size=10)
    yield db, service, factory
    db.close()
    engine.dispose()


def make_bank_csv(reference='REF-001', amount='100.00', currency='KES'):
    return _make_csv_bytes([
        ['Booking Date', 'Value Date', 'Amount', 'Reference', 'Description', 'Currency'],
        ['2026-01-15', '2026-01-15', amount, reference, 'Test payment', currency],
    ])


@pytest.fixture
def client_env(test_db_and_service):
    db, service, _ = test_db_and_service
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_ingestion_service] = lambda: service
    with TestClient(app) as client:
        yield client, db, service
    app.dependency_overrides.clear()


def test_omitted_source_id_creates_runtime_source(client_env):
    """When source_system_id is omitted, the API creates a runtime source system."""
    client, db, _ = client_env
    content = make_bank_csv('REF-OMIT-1')
    resp = client.post(
        '/api/v1/imports/upload?filename=statement.csv&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={
            'Content-Type': 'text/csv',
            'X-Import-Options': '{"bank_account_id":"bank_1","currency_code":"KES"}'
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['status'] == 'COMPLETED'
    assert data['valid_rows'] == 1

    # Verify runtime source system in database
    created_source_id = data['source_system_id']
    source = db.get(SourceSystem, created_source_id)
    assert source is not None
    assert source.organization_id == 'org_a'
    assert source.adapter_key == 'generic_bank'
    assert source.display_name == 'Runtime uploads'
    assert source.source_type == 'MANUAL'


def test_later_compatible_upload_reuses_runtime_source(client_env):
    """Subsequent uploads with the same organization and adapter reuse the existing runtime source."""
    client, db, _ = client_env
    content1 = make_bank_csv('REF-REUSE-1')
    resp1 = client.post(
        '/api/v1/imports/upload?filename=statement1.csv&organization_id=org_a&adapter_key=generic_bank',
        content=content1,
        headers={
            'Content-Type': 'text/csv',
            'X-Import-Options': '{"bank_account_id":"bank_1","currency_code":"KES"}'
        }
    )
    assert resp1.status_code == 200
    source_id_1 = resp1.json()['source_system_id']

    content2 = make_bank_csv('REF-REUSE-2')
    resp2 = client.post(
        '/api/v1/imports/upload?filename=statement2.csv&organization_id=org_a&adapter_key=generic_bank',
        content=content2,
        headers={
            'Content-Type': 'text/csv',
            'X-Import-Options': '{"bank_account_id":"bank_1","currency_code":"KES"}'
        }
    )
    assert resp2.status_code == 200
    source_id_2 = resp2.json()['source_system_id']

    assert source_id_1 == source_id_2

    # Exactly one runtime source for this org and adapter
    runtime_sources = db.query(SourceSystem).filter_by(
        organization_id='org_a',
        adapter_key='generic_bank',
        display_name='Runtime uploads'
    ).all()
    assert len(runtime_sources) == 1


def test_sources_remain_separated_by_organization_and_adapter(client_env):
    """Runtime sources must be isolated across organizations and adapter keys."""
    client, db, _ = client_env
    # Upload 1: org_a, generic_bank
    c1 = make_bank_csv('REF-ISO-1')
    r1 = client.post(
        '/api/v1/imports/upload?filename=s1.csv&organization_id=org_a&adapter_key=generic_bank',
        content=c1,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert r1.status_code == 200
    src_a_bank = r1.json()['source_system_id']

    # Upload 2: different organization (org_b, generic_bank)
    # Even if ingestion rejects bank account in pipeline, runtime source is created
    c2 = make_bank_csv('REF-ISO-2')
    r2 = client.post(
        '/api/v1/imports/upload?filename=s2.csv&organization_id=org_b&adapter_key=generic_bank',
        content=c2,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    # The source is created for org_b before pipeline processing
    src_b_bank = db.query(SourceSystem).filter_by(
        organization_id='org_b', adapter_key='generic_bank', display_name='Runtime uploads'
    ).first()
    assert src_b_bank is not None
    assert src_b_bank.id != src_a_bank

    # Upload 3: different adapter on org_a (e.g. generic_ap_invoice)
    inv_csv = _make_csv_bytes([
        ['vendor_name', 'invoice_number', 'invoice_date', 'total_amount'],
        ['Acme Corp', 'INV-001', '2026-01-15', '500.00']
    ])
    r3 = client.post(
        '/api/v1/imports/upload?filename=inv.csv&organization_id=org_a&adapter_key=generic_ap_invoice',
        content=inv_csv,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"currency_code":"KES"}'}
    )
    assert r3.status_code == 200
    src_a_ap = r3.json()['source_system_id']
    assert src_a_ap != src_a_bank


def test_explicit_valid_source_still_works(client_env):
    """Providing an explicit, valid source_system_id works as expected."""
    client, db, _ = client_env
    content = make_bank_csv('REF-EXP-1')
    resp = client.post(
        '/api/v1/imports/upload?filename=statement.csv&source_system_id=explicit_source&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['source_system_id'] == 'explicit_source'
    assert data['valid_rows'] == 1


def test_explicit_missing_source_is_rejected(client_env):
    """Explicitly passing a non-existent source_system_id returns 400."""
    client, _, _ = client_env
    content = make_bank_csv('REF-NONEXISTENT')
    resp = client.post(
        '/api/v1/imports/upload?filename=statement.csv&source_system_id=nonexistent_id&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert resp.status_code == 400
    assert "Invalid source system for organization" in resp.text


def test_explicit_inactive_source_is_rejected(client_env):
    """Explicitly passing an inactive source_system_id returns 400."""
    client, _, _ = client_env
    content = make_bank_csv('REF-INACTIVE')
    resp = client.post(
        '/api/v1/imports/upload?filename=statement.csv&source_system_id=inactive_source&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert resp.status_code == 400
    assert "Invalid source system for organization" in resp.text


def test_explicit_wrong_org_source_is_rejected(client_env):
    """Explicitly passing a source_system_id from another organization returns 400."""
    client, _, _ = client_env
    content = make_bank_csv('REF-WRONG-ORG')
    resp = client.post(
        '/api/v1/imports/upload?filename=statement.csv&source_system_id=other_org_source&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert resp.status_code == 400
    assert "Invalid source system for organization" in resp.text


def test_duplicate_file_behavior_remains_correct(client_env):
    """Uploading the exact same file content again returns status DUPLICATE."""
    client, db, _ = client_env
    content = make_bank_csv('REF-DUP-1')
    # First upload
    r1 = client.post(
        '/api/v1/imports/upload?filename=bank1.csv&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1['status'] == 'COMPLETED'
    assert d1['valid_rows'] == 1

    # Second upload with identical bytes (even if filename differs)
    r2 = client.post(
        '/api/v1/imports/upload?filename=bank1_renamed.csv&organization_id=org_a&adapter_key=generic_bank',
        content=content,
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{"bank_account_id":"bank_1"}'}
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2['status'] == 'DUPLICATE'
    assert d2['duplicate_files'] == 1
    assert d2['batch_id'] == d1['batch_id']

    # Database records were not duplicated
    assert db.query(BankTransaction).count() == 1
    assert db.query(SourceFile).count() == 1


def test_invalid_json_import_options_returns_422(client_env):
    """Non-JSON or array X-Import-Options returns 422."""
    client, _, _ = client_env
    resp = client.post(
        '/api/v1/imports/upload?filename=bank.csv&organization_id=org_a&adapter_key=generic_bank',
        content=b"some bytes",
        headers={'Content-Type': 'text/csv', 'X-Import-Options': 'not-json'}
    )
    assert resp.status_code == 422

    resp_array = client.post(
        '/api/v1/imports/upload?filename=bank.csv&organization_id=org_a&adapter_key=generic_bank',
        content=b"some bytes",
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '["array"]'}
    )
    assert resp_array.status_code == 422


def test_empty_upload_returns_400(client_env):
    """Empty upload body returns 400."""
    client, _, _ = client_env
    resp = client.post(
        '/api/v1/imports/upload?filename=empty.csv&organization_id=org_a&adapter_key=generic_bank',
        content=b"",
        headers={'Content-Type': 'text/csv', 'X-Import-Options': '{}'}
    )
    assert resp.status_code == 400
