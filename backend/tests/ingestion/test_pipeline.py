"""Financial validation invariants with explicit synthetic canonical payloads."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal

import pytest

from app.ingestion.base import CanonicalRecordPayload
from app.ingestion.pipeline import IngestionPipeline


def payload(entity='AP_INVOICE', **changes):
    data = {
        'AP_INVOICE': dict(vendor_name=' Demo Vendor ',invoice_number=' INV-1 ',
            invoice_date='2025-01-01',due_date=None,subtotal_amount='100',tax_amount='20',
            total_amount='120',paid_amount='0',outstanding_amount=None,status=' open ',currency_code='Rs'),
        'FIXED_ASSET': dict(asset_code='FA-1',asset_name='Demo asset',category='office equipment',
            acquisition_date='2025-01-01',in_service_date=None,acquisition_cost='100',
            salvage_value='10',accumulated_depreciation='20',book_value=None,
            useful_life_months='6',depreciation_method='straight-line',status='active',currency_code='PKR'),
        'BANK_TRANSACTION': dict(bank_account_id='bank',amount='10',booking_date=None,
            value_date=None,currency_code='PKR',bank_reference='r'),
        'JOURNAL_ENTRY': dict(external_entry_id='V1',entry_type='jnl',entry_date='2025-01-01',
            currency_code='PKR',exchange_rate='1',status='posted',lines=[
                dict(account_id='a',debit_amount='10',credit_amount='0'),
                dict(account_id='b',debit_amount='0',credit_amount='10')]),
        'TRIAL_BALANCE': dict(account_name_raw='cash',fiscal_period='2025-01',currency_code='PKR',
            opening_balance='5',period_debit='10',period_credit='2',closing_balance='13'),
    }[entity]
    data.update(changes)
    return CanonicalRecordPayload(entity,data,source_row_number=7,sheet_name='Demo')


def codes(result):
    return {i.code for i in result.issues}


@pytest.mark.parametrize('entity',['AP_INVOICE','FIXED_ASSET','BANK_TRANSACTION','JOURNAL_ENTRY','TRIAL_BALANCE'])
def test_valid_entities_and_preserved_input(entity):
    p=payload(entity); original=deepcopy(p)
    r=IngestionPipeline().process(p)
    assert r.is_valid, r.issues
    assert p == original
    assert r.payload.raw_lineage['canonical_before_validation']==original.data


@pytest.mark.parametrize('value',['bad',True,Decimal('NaN'),Decimal('Infinity'),'1e100','1.00001'])
def test_invalid_money_is_rejected_without_zero(value):
    r=IngestionPipeline().process(payload(total_amount=value))
    assert not r.is_valid
    assert codes(r) & {'ERR_INVALID_AMOUNT','ERR_AMOUNT_PRECISION'}
    assert r.payload.data['total_amount'] != Decimal(0)


@pytest.mark.parametrize('field',['subtotal_amount','tax_amount','total_amount','paid_amount'])
def test_missing_required_money_not_defaulted(field):
    # Subtotal is derivable only when total and tax are known.
    p=payload(**{field:None})
    if field=='subtotal_amount': p.data['total_amount']=None
    r=IngestionPipeline().process(p)
    assert not r.is_valid
    assert r.payload.data[field] is None
    assert 'ERR_MISSING_FIELD' in codes(r)


@pytest.mark.parametrize('value',['not-a-date','2025-02-30',True])
def test_bad_dates_explicit(value):
    r=IngestionPipeline().process(payload(invoice_date=value))
    assert not r.is_valid and 'ERR_INVALID_DATE' in codes(r)
    assert all(i.row_number==7 and i.sheet_name=='Demo' for i in r.issues)


def test_optional_dates_stay_null_and_zero_is_preserved():
    r=IngestionPipeline().process(payload(paid_amount=0,invoice_date=None))
    assert r.is_valid
    assert r.payload.data['invoice_date'] is None
    assert r.payload.data['due_date'] is None
    assert r.payload.data['paid_amount']==Decimal(0)


def test_standardization_replacements_and_derived_values():
    pipe=IngestionPipeline(value_replacements={'AP_INVOICE':{'status':{'unsettled':'open'}}})
    r=pipe.process(payload(status='unsettled',vendor_name='  Demo   Vendor\t'))
    assert r.is_valid
    assert r.payload.data['vendor_name']=='Demo Vendor'
    assert r.payload.data['currency_code']=='PKR'
    assert r.payload.data['status']=='OPEN'
    assert r.payload.data['outstanding_amount']==Decimal('120')


@pytest.mark.parametrize('currency',['Rs','rs.','pkr','PKR'])
def test_currency_aliases(currency):
    assert IngestionPipeline().process(payload(currency_code=currency)).payload.data['currency_code']=='PKR'


@pytest.mark.parametrize('changes,code',[
    ({'vendor_name':123},'ERR_INVALID_STRING'),({'invoice_number':'x\x00y'},'ERR_INVALID_IDENTIFIER'),
    ({'status':'nonsense'},'ERR_INVALID_STATUS'),({'currency_code':'123'},'ERR_INVALID_CURRENCY'),
    ({'vendor_name':'  '},'ERR_MISSING_FIELD'),({'total_amount':'-1'},'ERR_NEGATIVE_AMOUNT')])
def test_validation_codes(changes,code):
    r=IngestionPipeline().process(payload(**changes))
    assert not r.is_valid and code in codes(r)


@pytest.mark.parametrize('value',[0,-1,'1.5',True,'bad'])
def test_integer_validation(value):
    r=IngestionPipeline().process(payload('FIXED_ASSET',useful_life_months=value))
    assert not r.is_valid and 'ERR_INVALID_INTEGER' in codes(r)


def test_boolean_validation():
    r=IngestionPipeline().process(payload('JOURNAL_ENTRY',partial_journal='no'))
    assert r.is_valid and r.payload.data['partial_journal'] is False
    r=IngestionPipeline().process(payload('JOURNAL_ENTRY',partial_journal='perhaps'))
    assert not r.is_valid and 'ERR_INVALID_BOOLEAN' in codes(r)


def test_dual_sided_preserved_without_netting():
    p=payload('JOURNAL_ENTRY'); p.data['lines']=[dict(account_id='a',debit_amount='10',credit_amount='10')]
    r=IngestionPipeline().process(p)
    assert r.is_valid and 'WARN_DUAL_SIDED_POSTING' in codes(r)
    assert r.payload.data['lines'][0]['debit_amount']==r.payload.data['lines'][0]['credit_amount']==10


def test_unbalanced_complete_journal_and_partial_extract():
    p=payload('JOURNAL_ENTRY'); p.data['lines'].pop()
    r=IngestionPipeline().process(p)
    assert not r.is_valid and 'ERR_UNBALANCED_JOURNAL' in codes(r)
    p.data['partial_journal']=True
    r=IngestionPipeline().process(p)
    assert r.is_valid and 'WARN_INCOMPLETE_JOURNAL' in codes(r)
    assert r.payload.data['status']=='DRAFT'


@pytest.mark.parametrize('lines,code',[
    ([], 'ERR_JOURNAL_STRUCTURE'),([None], 'ERR_JOURNAL_STRUCTURE'),
    ([dict(debit_amount=1,credit_amount=1)],'ERR_MISSING_ACCOUNT'),
    ([dict(account_id='a',debit_amount=-1,credit_amount=-1)],'ERR_NEGATIVE_AMOUNT'),
    ([dict(account_id='a',debit_amount=None,credit_amount=0)],'ERR_MISSING_FIELD')])
def test_journal_structure(lines,code):
    r=IngestionPipeline().process(payload('JOURNAL_ENTRY',lines=lines))
    assert not r.is_valid and code in codes(r)


@pytest.mark.parametrize('rate',[0,-1,'bad','NaN'])
def test_exchange_rates(rate):
    r=IngestionPipeline().process(payload('JOURNAL_ENTRY',exchange_rate=rate))
    assert not r.is_valid


def test_currency_rate_consistency():
    r=IngestionPipeline().process(payload('JOURNAL_ENTRY',base_currency_code='pkr',exchange_rate=2))
    assert 'ERR_EXCHANGE_RATE' in codes(r)


@pytest.mark.parametrize('entity,changes,warning',[
    ('AP_INVOICE',{'due_date':'2024-01-01'},'WARN_AP_DATE_INCONSISTENCY'),
    ('FIXED_ASSET',{'in_service_date':'2024-01-01'},'WARN_ASSET_DATE_INCONSISTENCY')])
def test_suspicious_date_order_preserved(entity,changes,warning):
    r=IngestionPipeline().process(payload(entity,**changes))
    assert r.is_valid and warning in codes(r)


def test_business_duplicates_retained_after_standardization():
    pipe=IngestionPipeline()
    records=[pipe.process(payload()).payload,pipe.process(payload(vendor_name='Demo Vendor')).payload]
    retained,issues=pipe.detect_duplicates(records)
    assert len(retained)==2 and len(issues)==1
    assert issues[0].code=='WARN_POTENTIAL_BUSINESS_DUPLICATE'


def test_batch_quarantine_separation_and_explicit_defaults():
    valid,bad=IngestionPipeline().process_batch([payload(),payload(invoice_number=None)])
    assert len(valid)==len(bad)==1
    r=IngestionPipeline(defaults={'AP_INVOICE':{'paid_amount':'0'}}).process(payload(paid_amount=None))
    assert r.is_valid


def test_bank_direction_and_period_derivation():
    assert IngestionPipeline().process(payload('BANK_TRANSACTION',amount=-2)).payload.raw_lineage['transaction_direction']=='OUTFLOW'
    assert IngestionPipeline().process(payload('JOURNAL_ENTRY')).payload.data['fiscal_period']=='2025-01'


@pytest.mark.parametrize('entity,changes,warning',[
    ('AP_INVOICE',{'total_amount':'125'},'WARN_INVOICE_TOTAL_MISMATCH'),
    ('AP_INVOICE',{'paid_amount':'130'},'WARN_INVOICE_OVERPAYMENT'),
    ('FIXED_ASSET',{'salvage_value':'150'},'WARN_ASSET_SALVAGE_EXCEEDS_COST'),
    ('TRIAL_BALANCE',{'closing_balance':'99'},'WARN_TRIAL_BALANCE_CONTROL')])
def test_usable_business_rule_discrepancies_preserved(entity,changes,warning):
    result=IngestionPipeline().process(payload(entity,**changes))
    assert result.is_valid and warning in codes(result)
