"""Public, independently constructed fixtures; no local source files required."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import Base
from app.database.models import (Account, BankAccount, SourceSystem, SourceAccountMapping,
    SourceFile, ImportBatch, AuditEvent, JournalEntry, JournalLine, BankTransaction,
    APInvoice, FixedAsset, TrialBalanceRecord, FinancialRecord)
from app.ingestion.loading import (LoadPlan, LoadError, load_sources, context_id,
    verify_canonical, verify_mcp, read_plan, resolve_files)
from app.ingestion.storage import RawStorageManager
from tests.ingestion.test_adapters import _make_csv_bytes, _make_xlsx_bytes


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / 'sources'
    source.mkdir()
    (source/'cash.xls').write_bytes(_make_xlsx_bytes([
        ['Voucher Date','Particulars','Voucher Type','Voucher No','Ref No','Curr.','Ex.Rate','Debit Amount','Credit Amount','Balance Amount'],
        ['2025-01-02','Receipt','receipt','voucher-1','reference-1','USD',1,100,0,100],
    ]))
    (source/'tb.xls').write_bytes(_make_xlsx_bytes([
        ['Account','Opening','Debit','Credit','Closing'],['Cash',0,100,0,100]]))
    (source/'bank.csv').write_bytes(_make_csv_bytes([
        ['booking_date','amount','bank_reference','currency_code','external_transaction_id'],
        ['2025-01-02','100','reference-1','USD','bank-1']]))
    (source/'ap.csv').write_bytes(_make_csv_bytes([
        ['vendor_name','invoice_number','invoice_date','due_date','subtotal_amount','tax_amount','total_amount','paid_amount','outstanding_amount','currency_code'],
        ['Fixture vendor','invoice-1','2025-01-01','2025-02-01',100,0,100,0,100,'USD']]))
    (source/'asset.csv').write_bytes(_make_csv_bytes([
        ['asset_code','asset_name','category','acquisition_cost','salvage_value','useful_life_months','accumulated_depreciation','book_value','currency_code'],
        ['asset-1','Fixture equipment','EQUIPMENT',1200,0,12,0,1200,'USD']]))
    adapters = ['enquest_ledger','enquest_tb','generic_bank','generic_ap_invoice','generic_fixed_asset']
    data = dict(version=1,organization_id='fixture-org',source_root='sources',
        accounts=[dict(key='cash',account_code='cash-code',account_name='Cash',account_type='ASSET',normal_balance='DEBIT',currency_code='USD')],
        sources=[dict(key=k,adapter_key=k,source_type='MANUAL',display_name=k) for k in adapters],
        mappings=[dict(source_key=k,source_account_key=name,account_key='cash',reviewed_by='Fixture reviewer')
                  for k,name in [('enquest_ledger','cash'),('enquest_tb','Cash')]],
        bank_accounts=[dict(key='bank',bank_name='Fixture bank',account_name='Cash account',account_number_masked='****1',gl_account_key='cash',currency_code='USD')],
        files=[dict(source_key=k,path=path,options=options) for k,path,options in zip(adapters,
            ['cash.xls','tb.xls','bank.csv','ap.csv','asset.csv'],
            [{},{'fiscal_period':'2025-01','currency_code':'USD'},{'bank_account_key':'bank'},{},{}])])
    return tmp_path, data


@pytest.fixture
def database():
    engine=create_engine('sqlite:///:memory:',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def fk(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def run(inputs, database):
    root,data=inputs
    return load_sources(database,LoadPlan.model_validate(data),root,RawStorageManager(str(root/'stored')))


def test_all_adapters_context_canonical_lineage_and_replay(inputs,database):
    root,data=inputs
    plan=LoadPlan.model_validate(data)
    first=run(inputs,database)
    assert [f['imported_rows'] for f in first['files']]==[1]*5
    assert first['files'][0]['diagnostic_codes']=={'WARN_INCOMPLETE_JOURNAL':1}
    expected={'journal_entries':1,'journal_lines':1,'bank_transactions':1,'ap_invoices':1,
              'fixed_assets':1,'trial_balance_records':1,'import_batches':5,'source_files':5}
    assert verify_canonical(database,plan)=={'counts':expected,'lineage_issues':{}}
    with database() as db:
        mapping=db.scalar(select(SourceAccountMapping).where(SourceAccountMapping.source_account_key=='cash'))
        assert mapping.mapping_status=='REVIEWED' and mapping.reviewed_by=='Fixture reviewer' and mapping.reviewed_at
        bank=db.get(BankAccount,context_id(plan,'bank','bank'))
        assert bank.gl_account.id==mapping.account_id
        line=db.scalar(select(JournalLine))
        assert line.journal_entry.status=='DRAFT' and not line.is_reconciled
        files=db.scalars(select(SourceFile)).all()
        hashes={f.id:f.sha256 for f in files}
        for f in files:
            original=root/'sources'/f.original_filename
            assert Path(f.relative_raw_path).read_bytes()==original.read_bytes()
        # A legacy-only record must not appear in MCP output.
        db.add(FinancialRecord(id='legacy-only',source='GL',account_code='cash-code',amount=999))
        db.commit()
    second=run(inputs,database)
    assert second['created_context']=={}
    assert all(f['status']=='DUPLICATE' and f['duplicate_files']==1 and f['imported_rows']==0 for f in second['files'])
    assert all(f['retained_imported_rows']==1 for f in second['files'])
    assert [f['source_file_id'] for f in first['files']]==[f['source_file_id'] for f in second['files']]
    assert verify_canonical(database,plan)['counts']==expected
    with database() as db:
        assert hashes=={f.id:f.sha256 for f in db.scalars(select(SourceFile))}
    # Verification works after originals disappear; runtime tools are canonical-only.
    (root/'sources').rename(root/'offline-sources')
    assert asyncio.run(verify_mcp(database,plan))['accounts']==[
        {'account_number':1,'gl_rows_returned':1,'bank_rows_returned':1}]


@pytest.mark.parametrize('change', ['duplicate_key','missing_bank','wrong_currency','missing_period','unknown_option','unreviewed'])
def test_invalid_plan_rejected(inputs, change):
    _,data=inputs
    if change=='duplicate_key': data['accounts'].append(copy.deepcopy(data['accounts'][0]))
    elif change=='missing_bank': data['files'][2]['options']={}
    elif change=='wrong_currency': data['bank_accounts'][0]['currency_code']='EUR'
    elif change=='missing_period': data['files'][1]['options'].pop('fiscal_period')
    elif change=='unknown_option': data['files'][0]['options']['guess_missing_money']=True
    else: data['mappings'][0]['reviewed_by']=''
    with pytest.raises(ValidationError): LoadPlan.model_validate(data)


@pytest.mark.parametrize('path',['../outside.csv','absent.csv'])
def test_path_preflight_prevents_partial_setup(inputs,database,path):
    root,data=inputs
    (root/'outside.csv').write_text('outside',encoding='utf-8')
    data['files'][-1]['path']=path
    with pytest.raises(LoadError): run(inputs,database)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Account))==0
        assert db.scalar(select(func.count()).select_from(ImportBatch))==0


def test_context_conflict_rolls_back_new_masters(inputs,database):
    root,data=inputs
    run(inputs,database)
    data['accounts'].insert(0,dict(key='new',account_code='new',account_name='New',account_type='ASSET',normal_balance='DEBIT',currency_code='USD'))
    data['sources'][0]['display_name']='Changed source'
    with pytest.raises(LoadError,match='conflicts'): run(inputs,database)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Account))==1
        assert db.scalar(select(func.count()).select_from(ImportBatch))==5


def test_changed_replay_options_require_explicit_reprocessing(inputs,database):
    run(inputs,database)
    inputs[1]['files'][1]['options']['fiscal_period']='2025-02'
    with pytest.raises(LoadError,match='reprocessing'): run(inputs,database)
    with database() as db: assert db.scalar(select(func.count()).select_from(ImportBatch))==5


def test_missing_mapping_quarantines_without_invented_account(inputs,database):
    inputs[1]['mappings']=[]
    result=run(inputs,database)
    assert [f['quarantined_rows'] for f in result['files']]==[1,1,0,0,0]
    assert result['files'][0]['diagnostic_codes']=={'ERR_MISSING_ACCOUNT':1}
    assert verify_canonical(database,LoadPlan.model_validate(inputs[1]))['lineage_issues']=={}
    replay=run(inputs,database)
    assert replay['files'][0]['stored_parse_status']=='QUARANTINED'
    assert replay['files'][0]['retained_quarantined_rows']==1
    with database() as db: assert db.scalar(select(func.count()).select_from(Account))==1


def test_duplicate_and_invalid_rows_report_codes_without_values(inputs,database,capsys,caplog):
    root,data=inputs
    (root/'sources'/'ap.csv').write_bytes(_make_csv_bytes([
        ['vendor_name','invoice_number','subtotal_amount','tax_amount','total_amount','paid_amount','outstanding_amount','currency_code'],
        ['Private fixture marker','number-1',100,0,100,0,100,'USD'],
        ['Private fixture marker','number-1',100,0,100,0,100,'USD'],
        ['Private fixture marker','number-2','invalid',0,100,0,100,'USD']]))
    result=run(inputs,database)
    ap=result['files'][3]
    assert (ap['imported_rows'],ap['quarantined_rows'],ap['warning_rows'])==(2,1,1)
    assert ap['diagnostic_codes']=={'WARN_POTENTIAL_BUSINESS_DUPLICATE':1,'ERR_INVALID_AMOUNT':1}
    assert 'Private fixture marker' not in json.dumps(result)+caplog.text+capsys.readouterr().out


def test_cross_organization_context_collision_rejected(inputs,database):
    plan=LoadPlan.model_validate(inputs[1])
    with database() as db:
        db.add(Account(id=context_id(plan,'account','cash'),organization_id='another-org',
            account_code='cash-code',account_name='Cash',normalized_name='cash',account_type='ASSET',currency_code='USD'))
        db.commit()
    with pytest.raises(LoadError): run(inputs,database)
    with database() as db: assert db.scalar(select(func.count()).select_from(ImportBatch))==0


def test_same_account_code_different_identity_rejected(inputs,database):
    with database() as db:
        db.add(Account(id='existing-master',organization_id='fixture-org',account_code='cash-code',
            account_name='Cash',normalized_name='cash',account_type='ASSET',currency_code='USD'))
        db.commit()
    with pytest.raises(LoadError,match='different master'): run(inputs,database)


def cli():
    path=Path(__file__).resolve().parents[3]/'scripts/load_financial_sources.py'
    spec=importlib.util.spec_from_file_location('load_financial_sources',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_explicit_initialization_and_safe_rerun(inputs,capsys):
    root,data=inputs
    manifest=root/'sources.local.json'
    manifest.write_text(json.dumps(data),encoding='utf-8')
    db_path=root/'local.sqlite'
    args=['--manifest',str(manifest),'--database',str(db_path),'--storage-root',str(root/'stored')]
    entry=cli()
    assert entry.main(args+['--validate-only'])==0 and not db_path.exists()
    assert entry.main(args)==1 and not db_path.exists()
    assert entry.main(args+['--initialize'])==0
    capsys.readouterr()
    assert entry.main(args)==0
    output=json.loads(capsys.readouterr().out)
    assert all(f['status']=='DUPLICATE' for f in output['files'])


def test_cli_redacts_invalid_manifest(inputs,capsys):
    root,_=inputs
    manifest=root/'confidential-path.json'
    manifest.write_text('{"private financial value":',encoding='utf-8')
    code=cli().main(['--manifest',str(manifest),'--database',str(root/'db.sqlite'),'--storage-root',str(root/'raw')])
    output=capsys.readouterr()
    assert code==1 and 'private financial value' not in output.err and 'confidential-path' not in output.err


def test_cli_quarantine_still_requires_review_on_replay(inputs,capsys):
    root,data=inputs
    data['mappings']=[]
    manifest=root/'sources.local.json'
    manifest.write_text(json.dumps(data),encoding='utf-8')
    args=['--manifest',str(manifest),'--database',str(root/'db.sqlite'),'--storage-root',str(root/'stored')]
    entry=cli()
    assert entry.main(args+['--initialize'])==2
    capsys.readouterr()
    assert entry.main(args)==2
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='REVIEW_REQUIRED'
    assert result['files'][0]['status']=='DUPLICATE'
    assert result['files'][0]['retained_quarantined_rows']==1


def test_renamed_ledger_replay_cannot_change_account_identity(inputs,database):
    root,data=inputs
    run(inputs,database)
    (root/'sources'/'cash.xls').rename(root/'sources'/'other-cash.xls')
    data['files'][0]['path']='other-cash.xls'
    with pytest.raises(LoadError,match='reprocessing'): run(inputs,database)


def test_identical_planned_bytes_cannot_silently_change_mapping(inputs,database):
    root,data=inputs
    (root/'sources'/'other-cash.xls').write_bytes((root/'sources'/'cash.xls').read_bytes())
    data['files'].append(dict(source_key='enquest_ledger',path='other-cash.xls'))
    with pytest.raises(LoadError,match='conflicting mapping options'): run(inputs,database)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(ImportBatch))==0
        assert db.scalar(select(func.count()).select_from(Account))==0


def test_incomplete_existing_schema_fails_without_import(inputs,tmp_path):
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as conn: conn.exec_driver_sql('CREATE TABLE accounts (id TEXT PRIMARY KEY)')
    factory=sessionmaker(bind=engine)
    with pytest.raises(LoadError,match='migration'): run(inputs,factory)
    engine.dispose()
