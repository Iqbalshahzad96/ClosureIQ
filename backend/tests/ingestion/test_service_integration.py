"""Synthetic upload-to-canonical SQLite integration; no business files required."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import Base, get_db
from app.database.models import (SourceSystem, SourceAccountMapping, ImportBatch,
    SourceFile, JournalEntry, JournalLine, Account, BankAccount, BankTransaction,
    APInvoice, FixedAsset, TrialBalanceRecord, AuditEvent, FinancialRecord)
from app.ingestion.base import RawSourceRow, RowRole
from app.ingestion.service import IngestionService
from app.ingestion.storage import RawStorageManager
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.adapters.generic_bank import GenericBankStatementAdapter
from app.ingestion.adapters.registry import AdapterRegistry
from tests.ingestion.test_adapters import _make_csv_bytes, _make_xlsx_bytes, TestEnquestLedgerAdapter as LedgerFixture


@pytest.fixture
def env(tmp_path):
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def enforce_fk(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    db=factory()
    source=SourceSystem(id='source',organization_id='org',adapter_key='auto',source_type='ERP',display_name='Synthetic')
    account=Account(id='account',organization_id='org',account_code='1010',account_name='Cash',normalized_name='cash',account_type='ASSET',currency_code='KES')
    db.add_all([source,account]); db.flush()
    db.add_all([SourceAccountMapping(source_system_id=source.id,source_account_key='ledger',account_id=account.id,mapping_status='REVIEWED'),
                SourceAccountMapping(source_system_id=source.id,source_account_key='Cash at Bank',account_id=account.id,mapping_status='REVIEWED'),
                BankAccount(id='bank',organization_id='org',bank_name='Demo',account_number_masked='***1',account_name='Demo bank',linked_gl_account_id=account.id,currency_code='KES')])
    db.commit()
    service=IngestionService(storage=RawStorageManager(str(tmp_path/'raw')),chunk_size=1)
    yield db,service,factory
    db.close(); engine.dispose()


def ingest(env,content,filename='bank.csv',**kwargs):
    db,service,_=env
    return service.ingest_file(db,content,filename,organization_id='org',source_system_id='source',**kwargs)


def bank_content(rows=None):
    return _make_csv_bytes([['Booking Date','Value Date','Amount','Reference','Currency']]+(
        rows or [['2025-01-01','','10','R1','KES']]))


def test_ledger_lineage_draft_and_immutable_copy(env):
    content=LedgerFixture()._build_ledger_workbook()
    result=ingest(env,content,'ledger.xls')
    db,service,_=env
    assert result.status=='COMPLETED',result.errors
    assert (result.total_rows,result.valid_rows,result.warning_rows)==(1,1,1)
    entry=db.query(JournalEntry).one(); line=db.query(JournalLine).one()
    file=db.query(SourceFile).one(); batch=db.query(ImportBatch).one()
    assert entry.import_batch_id==batch.id and entry.source_file_id==file.id
    assert line.journal_entry_id==entry.id and line.account_id=='account'
    assert entry.status=='DRAFT' and not line.is_reconciled
    assert line.dimensions_json['cuin_fda']=='CUIN-001'
    assert line.source_row_identifier=='Sheet1:R6'
    assert service.storage.read_file(file.relative_raw_path)==content
    assert file.sha256==service.storage.calculate_sha256(content)
    assert db.query(FinancialRecord).count()==0
    assert db.query(AuditEvent).filter_by(event_type='INGEST_IMPORTED').one().details['lineage']['raw_values']


def test_dual_posting_preserved_warned(env):
    result=ingest(env,LedgerFixture()._build_ledger_workbook(dual_sided=True),'ledger.xls')
    assert result.valid_rows==1
    assert 'WARN_DUAL_SIDED_POSTING' in {w['code'] for w in result.warnings}
    line=env[0].query(JournalLine).one()
    assert line.debit_amount>0 and line.credit_amount>0


def test_bad_date_quarantined_good_row_imported_and_counts(env):
    result=ingest(env,bank_content([['2025-01-01','','10','R1','KES'],['bad','','20','R2','KES']]),options={'bank_account_id':'bank'})
    db,_,_=env
    assert (result.status,result.total_rows,result.valid_rows,result.quarantined_rows)==('PARTIAL',2,1,1)
    assert result.errors[0]['code']=='ERR_INVALID_DATE'
    assert db.query(BankTransaction).count()==1
    q=db.query(AuditEvent).filter_by(event_type='INGEST_QUARANTINED').one()
    assert q.details['row_number']==3 and q.details['sheet_name']=='CSV'
    batch=db.query(ImportBatch).one()
    assert (batch.total_rows,batch.valid_rows,batch.error_rows)==(2,1,1)


def test_same_hash_idempotent_no_extra_file_or_rows(env):
    first=ingest(env,bank_content(),options={'bank_account_id':'bank'})
    second=ingest(env,bank_content(),'renamed.csv',options={'bank_account_id':'bank'})
    assert second.status=='DUPLICATE' and second.duplicate_files==1
    assert second.batch_id==first.batch_id
    assert env[0].query(SourceFile).count()==1 and env[0].query(BankTransaction).count()==1


def test_hash_scoped_to_source_system(env):
    db,service,_=env
    ingest(env,bank_content(),options={'bank_account_id':'bank'})
    db.add(SourceSystem(id='other',organization_id='org',adapter_key='auto',source_type='BANK',display_name='Other'))
    db.commit()
    second=service.ingest_file(db,bank_content(),'other.csv',organization_id='org',source_system_id='other',options={'bank_account_id':'bank'})
    assert second.status=='COMPLETED' and second.valid_rows==1
    assert db.query(BankTransaction).count()==2


def test_business_duplicate_preserved_across_chunks_and_files(env):
    rows=[['2025-01-01','','10','R1','KES']]*2
    result=ingest(env,bank_content(rows),options={'bank_account_id':'bank'})
    assert result.valid_rows==2 and result.business_duplicate_rows==1
    assert 'WARN_POTENTIAL_BUSINESS_DUPLICATE' in {w['code'] for w in result.warnings}
    result=ingest(env,bank_content()+b'\n',options={'bank_account_id':'bank'})
    assert result.valid_rows==1 and result.business_duplicate_rows==1
    assert env[0].query(BankTransaction).count()==3


@pytest.mark.parametrize('options',[{}, {'bank_account_id':'missing'}])
def test_no_invented_bank_account(env,options):
    result=ingest(env,bank_content(),options=options)
    assert result.quarantined_rows==1 and result.valid_rows==0
    assert env[0].query(BankTransaction).count()==0


def test_unmapped_ledger_not_autocreated(env):
    result=ingest(env,LedgerFixture()._build_ledger_workbook(),'unknown.xls')
    assert result.valid_rows==0 and result.errors[0]['code']=='ERR_MISSING_ACCOUNT'
    assert env[0].query(Account).count()==1 and env[0].query(JournalEntry).count()==0


def test_scope_and_currency_validation(env):
    db,service,_=env
    with pytest.raises(ValueError):
        service.ingest_file(db,bank_content(),'bank.csv',source_system_id='source',organization_id='wrong')
    result=ingest(env,bank_content([['2025-01-01','','10','R1','USD']]),options={'bank_account_id':'bank'})
    assert result.valid_rows==0 and result.errors[0]['code']=='ERR_CURRENCY_MISMATCH'


def test_batch_scope_rejected(env):
    result=ingest(env,bank_content(),options={'bank_account_id':'bank'})
    db,service,_=env
    db.add(SourceSystem(id='other',organization_id='org',adapter_key='auto',source_type='BANK',display_name='Other'))
    db.commit()
    with pytest.raises(ValueError):
        service.ingest_file(db,bank_content(),'bank.csv',organization_id='org',source_system_id='other',batch_id=result.batch_id)


def test_ap_and_asset_and_tb_persistence(env):
    ap=_make_csv_bytes([['Vendor Name','Invoice Number','Invoice Date','Due Date','Subtotal','Tax','Total','Paid','Currency','Status'],
        ['Demo','INV-1','2025-01-02','2025-01-01','100','20','120','0','KES','open']])
    result=ingest(env,ap,'ap.csv')
    assert result.valid_rows==1 and result.warning_rows==1,result.errors
    assert env[0].query(APInvoice).one().outstanding_amount==120
    asset=_make_csv_bytes([['Asset Code','Asset Name','Category','Acquisition Cost','Salvage Value','Useful Life Months','Accumulated Depreciation','Currency'],
        ['A1','Demo','equipment','100','10','6','20','KES']])
    result=ingest(env,asset,'asset.csv')
    assert result.valid_rows==1,result.errors
    assert env[0].query(FixedAsset).one().book_value==80
    tb=_make_xlsx_bytes([['Account','Opening','Debit','Credit','Closing'],['Cash at Bank',10,20,5,25]])
    result=ingest(env,tb,'tb.xls',options={'fiscal_period':'2025-01','currency_code':'KES'})
    assert result.valid_rows==1,result.errors
    assert env[0].query(TrialBalanceRecord).one().closing_balance==25


def test_failed_file_retains_raw_and_explicit_error(env):
    result=ingest(env,b'not a table','unknown.csv')
    assert result.status=='FAILED' and result.errors[0]['code']=='ERR_NO_ADAPTER'
    file=env[0].query(SourceFile).one()
    assert env[1].storage.read_file(file.relative_raw_path)==b'not a table'


@pytest.mark.parametrize('name',['../escape.csv','..\\escape.csv','C:bad.csv','CON','x/evil.csv'])
def test_path_escape_rejected(env,name):
    with pytest.raises(ValueError):
        ingest(env,bank_content(),name)
    assert env[0].query(ImportBatch).count()==0


def test_storage_never_overwrites(env):
    storage=env[1].storage
    path,_,_=storage.store_file(b'original','same.csv','batch')
    with pytest.raises(FileExistsError): storage.store_file(b'changed','same.csv','batch')
    assert storage.read_file(path)==b'original'


def test_persistence_failure_savepoint_and_no_sensitive_logs(env,monkeypatch,caplog):
    db,service,_=env
    original=service._persist
    def fail_one(db,payload,org):
        record=original(db,payload,org)
        if payload.data['bank_reference']=='R1':
            raise RuntimeError('SECRET FINANCIAL VALUE')
        return record
    monkeypatch.setattr(service,'_persist',fail_one)
    result=ingest(env,bank_content([['2025-01-01','','10','R1','KES'],['2025-01-02','','20','R2','KES']]),options={'bank_account_id':'bank'})
    assert result.valid_rows==result.quarantined_rows==1
    assert db.query(BankTransaction).one().bank_reference=='R2'
    assert 'SECRET FINANCIAL VALUE' not in caplog.text+str(result.errors)


def test_parse_failure_rolls_back_already_imported_rows(env):
    class Failing(GenericBankStatementAdapter):
        def parse_file(self,*args,**kwargs):
            yield from super().parse_file(*args,**kwargs)
            raise ValueError('late parser error')
    registry=AdapterRegistry(); registry.register(Failing())
    env[1].registry=registry
    result=ingest(env,bank_content(),adapter_key='generic_bank',options={'bank_account_id':'bank'})
    assert result.status=='FAILED' and result.valid_rows==0
    assert env[0].query(BankTransaction).count()==0
    assert env[0].query(AuditEvent).filter_by(event_type='INGEST_IMPORTED').count()==0


def test_technical_source_row_duplicate_prevented(env):
    class Repeated(GenericBankStatementAdapter):
        def parse_file(self,*args,**kwargs):
            for row in super().parse_file(*args,**kwargs):
                yield row
                if row.role==RowRole.TRANSACTION: yield row
    registry=AdapterRegistry(); registry.register(Repeated()); env[1].registry=registry
    result=ingest(env,bank_content(),adapter_key='generic_bank',options={'bank_account_id':'bank'})
    assert result.total_rows==2 and result.valid_rows==1 and result.technical_duplicate_rows==1


def test_upload_http_to_database(env):
    from app.main import app
    from app.api.routes.imports import get_ingestion_service
    db,service,_=env
    def dependency(): yield db
    app.dependency_overrides[get_db]=dependency
    app.dependency_overrides[get_ingestion_service]=lambda:service
    try:
        with TestClient(app) as client:
            response=client.post('/api/v1/imports/upload?filename=bank.csv&source_system_id=source&organization_id=org',
                content=bank_content(),headers={'Content-Type':'text/csv','X-Import-Options':'{"bank_account_id":"bank"}'})
        assert response.status_code==200,response.text
        assert response.json()['valid_rows']==1
        assert db.query(BankTransaction).count()==1
    finally:
        app.dependency_overrides.clear()


def test_canonical_ingestion_reaches_mcp_and_legacy_is_not_read(env):
    import asyncio
    from app.mcp.tools import FinancialMCPTools
    db,service,factory=env
    ingest(env,LedgerFixture()._build_ledger_workbook(),'ledger.xls')
    ingest(env,bank_content(),options={'bank_account_id':'bank'})
    db.add(FinancialRecord(id='legacy',source='GL',account_code='1010',amount=999))
    db.commit()
    tools=FinancialMCPTools(factory,organization_id='org')
    gl=asyncio.run(tools.query_gl_transactions('1010'))
    bank=asyncio.run(tools.query_bank_transactions('1010'))
    assert len(gl)==len(bank)==1
    assert gl[0]['amount']==50000.75 and gl[0]['entry_status']=='DRAFT'
    assert bank[0]['amount']==10
    assert asyncio.run(FinancialMCPTools(factory,organization_id='different').query_gl_transactions('1010'))==[]


def test_existing_batch_status_aggregates_errors(env):
    bad=ingest(env,bank_content([['bad','','10','R1','KES']]),'bad.csv',options={'bank_account_id':'bank'})
    good=ingest(env,bank_content(),'good.csv',batch_id=bad.batch_id,options={'bank_account_id':'bank'})
    batch=env[0].get(ImportBatch,bad.batch_id)
    assert good.status==batch.status=='PARTIAL'
    assert (batch.total_rows,batch.valid_rows,batch.error_rows,batch.file_count)==(2,1,1,2)


def test_row_chunk_size_is_bounded(env):
    from app.ingestion.adapters.generic_bank import GenericBankStatementAdapter
    class Tracking(GenericBankStatementAdapter):
        maximum=0
        def map_to_canonical(self,rows,options=None):
            self.maximum=max(self.maximum,len(rows))
            return super().map_to_canonical(rows,options)
    adapter=Tracking(); env[1].registry.register(adapter)
    data=bank_content([[f'2025-01-{i:02d}','','10',f'R{i}','KES'] for i in range(1,25)])
    result=ingest(env,data,adapter_key='generic_bank',options={'bank_account_id':'bank'})
    assert result.valid_rows==24 and adapter.maximum<=env[1].chunk_size
