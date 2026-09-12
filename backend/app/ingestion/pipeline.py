"""
Shared Data Quality, Standardization, Transformation & Business Rules Pipeline.

Operates on canonical representations (CanonicalRecordPayload), not on
source-specific fields. Reusable across all adapters.
"""

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from app.ingestion.base import (
    CanonicalRecordPayload,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Currency aliases → ISO 4217
# ---------------------------------------------------------------------------

CURRENCY_ALIAS_MAP: Dict[str, str] = {
    "rs": "PKR",
    "rs.": "PKR",
    "pkr": "PKR",
    "kes": "KES",
    "ksh": "KES",
    "usd": "USD",
    "us$": "USD",
    "$": "USD",
    "eur": "EUR",
    "€": "EUR",
    "gbp": "GBP",
    "£": "GBP",
    "inr": "INR",
    "₹": "INR",
}

# Status aliases
STATUS_ALIAS_MAP: Dict[str, str] = {
    "active": "ACTIVE",
    "disposed": "DISPOSED",
    "fully depreciated": "FULLY_DEPRECIATED",
    "fully_depreciated": "FULLY_DEPRECIATED",
    "open": "OPEN",
    "paid": "PAID",
    "partially paid": "PARTIALLY_PAID",
    "partially_paid": "PARTIALLY_PAID",
    "void": "VOID",
    "posted": "POSTED",
    "draft": "DRAFT",
    "reversed": "REVERSED",
}

VOUCHER_TYPE_ALIAS_MAP: Dict[str, str] = {
    "jnl": "JOURNAL",
    "journal": "JOURNAL",
    "jv": "JOURNAL",
    "pmt": "PAYMENT",
    "payment": "PAYMENT",
    "pay": "PAYMENT",
    "rcpt": "RECEIPT",
    "receipt": "RECEIPT",
    "rec": "RECEIPT",
    "contra": "CONTRA",
    "cntr": "CONTRA",
    "credit note": "CREDIT_NOTE",
    "debit note": "DEBIT_NOTE",
    "sales": "SALES",
    "purchase": "PURCHASE",
}


# ===========================================================================
# Required field definitions per entity type
# ===========================================================================

# Fields that MUST be non-null and non-empty for a record to pass validation
REQUIRED_FIELDS: Dict[str, List[str]] = {
    "JOURNAL_ENTRY": ["entry_type"],
    "BANK_TRANSACTION": ["bank_account_id", "amount"],
    "AP_INVOICE": ["vendor_name", "invoice_number"],
    "FIXED_ASSET": ["asset_name", "category"],
    "TRIAL_BALANCE": ["account_name_raw", "fiscal_period"],
}

# Monetary fields that must be Decimal if present (never silently zeroed)
MONETARY_FIELDS: Dict[str, List[str]] = {
    "JOURNAL_ENTRY": ["exchange_rate"],
    "BANK_TRANSACTION": ["amount", "running_balance"],
    "AP_INVOICE": [
        "subtotal_amount", "tax_amount", "total_amount",
        "paid_amount", "outstanding_amount",
    ],
    "FIXED_ASSET": [
        "acquisition_cost", "salvage_value",
        "accumulated_depreciation", "book_value",
    ],
    "TRIAL_BALANCE": [
        "opening_balance", "period_debit",
        "period_credit", "closing_balance",
    ],
}

# Date fields that must be valid datetime if present
DATE_FIELDS: Dict[str, List[str]] = {
    "JOURNAL_ENTRY": ["entry_date", "posting_date"],
    "BANK_TRANSACTION": ["booking_date", "value_date"],
    "AP_INVOICE": ["invoice_date", "due_date"],
    "FIXED_ASSET": ["acquisition_date", "in_service_date", "disposal_date"],
    "TRIAL_BALANCE": ["period_start", "period_end"],
}


# ===========================================================================
# Pipeline Class
# ===========================================================================

class IngestionPipeline:
    """Validate canonical values without inventing missing financial facts.

    SQL non-null monetary fields are required unless deterministically derivable.
    Source defaults/replacements must be explicitly configured by the caller.
    """
    def __init__(self, currency_aliases=None, status_aliases=None,
                 voucher_type_aliases=None, value_replacements=None, defaults=None):
        self.currency_aliases = {**CURRENCY_ALIAS_MAP, **(currency_aliases or {})}
        self.status_aliases = {**STATUS_ALIAS_MAP, **(status_aliases or {})}
        self.voucher_type_aliases = {**VOUCHER_TYPE_ALIAS_MAP, **(voucher_type_aliases or {})}
        self.value_replacements = value_replacements or {}
        self.defaults = defaults or {}

    def process(self, payload):
        from copy import deepcopy
        from app.ingestion.adapters.tabular import date_value, decimal_value
        payload = deepcopy(payload)
        data, entity = payload.data, payload.entity_type
        issues = []
        def issue(code, field, warning=False):
            issues.append(ValidationIssue(code, code.replace('_', ' ').capitalize(), field,
                ValidationSeverity.WARNING if warning else ValidationSeverity.ERROR,
                payload.source_row_number, payload.sheet_name))
        if entity not in REQUIRED_FIELDS:
            issue('ERR_ENTITY_TYPE', 'entity_type')
            return ValidationResult(False, payload, issues)
        # Preserve pre-standardization values in addition to the immutable raw file.
        payload.raw_lineage.setdefault('canonical_before_validation', deepcopy(data))
        for key, value in self.defaults.get(entity, {}).items():
            if data.get(key) is None:
                data[key] = deepcopy(value)
        for key, mapping in self.value_replacements.get(entity, {}).items():
            value = data.get(key)
            if isinstance(value, (str, int, bool, Decimal)) and value in mapping:
                data[key] = mapping[value]
        for key in DATE_FIELDS.get(entity, []):
            data[key] = date_value(data.get(key))
            if data[key] is not None and not isinstance(data[key], datetime):
                issue('ERR_INVALID_DATE', key)
        def money(container, keys, prefix=''):
            for key in keys:
                value = decimal_value(container.get(key))
                container[key] = value
                if value is None:
                    continue
                if not isinstance(value, Decimal) or not value.is_finite():
                    issue('ERR_INVALID_AMOUNT', prefix + key)
                    continue
                # Reject silent database rounding/overflow. Rates have six places.
                scale = 6 if key == 'exchange_rate' else 4
                try:
                    quantum = Decimal(1).scaleb(-scale)
                    if abs(value) >= Decimal(10) ** (18-scale) or value != value.quantize(quantum):
                        issue('ERR_AMOUNT_PRECISION', prefix + key)
                    else:
                        container[key] = value.quantize(quantum)
                except InvalidOperation:
                    issue('ERR_INVALID_AMOUNT', prefix + key)
        money(data, MONETARY_FIELDS[entity])
        lines = data.get('lines', [])
        if entity == 'JOURNAL_ENTRY':
            if not isinstance(lines, list) or not lines or any(not isinstance(x, dict) for x in lines):
                issue('ERR_JOURNAL_STRUCTURE', 'lines')
                lines = []
            for i, line in enumerate(lines):
                money(line, ['debit_amount','credit_amount','base_debit_amount',
                             'base_credit_amount','source_running_balance'], f'lines.{i}.')
        containers = [data] + lines
        amount_keys = set(sum(MONETARY_FIELDS.values(), [])) | {'debit_amount','credit_amount','base_debit_amount','base_credit_amount','source_running_balance'}
        integer_keys = {'useful_life_months', 'line_number'}
        bool_keys = {'partial_journal','is_reconciled','is_active'}
        complex_keys = {'lines','dimensions_json'}
        for container in containers:
            for key, value in list(container.items()):
                if key in amount_keys or key in sum(DATE_FIELDS.values(), []) or key in complex_keys:
                    continue
                if key in integer_keys:
                    if value is not None:
                        parsed = decimal_value(value)
                        if not isinstance(parsed, Decimal) or not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed <= 0 or parsed > 2147483647:
                            issue('ERR_INVALID_INTEGER', key)
                        else:
                            container[key] = int(parsed)
                elif key in bool_keys:
                    if isinstance(value, str) and value.strip().lower() in ('true','false','yes','no','1','0'):
                        container[key] = value.strip().lower() in ('true','yes','1')
                    elif value is not None and not isinstance(value, bool):
                        issue('ERR_INVALID_BOOLEAN', key)
                elif value is not None:
                    if not isinstance(value, str):
                        issue('ERR_INVALID_STRING', key)
                    else:
                        if any(ord(c) < 32 and c not in '\t\n\r' for c in value):
                            issue('ERR_INVALID_IDENTIFIER', key)
                        container[key] = ' '.join(value.split()) or None
        if any(i.severity == ValidationSeverity.ERROR for i in issues):
            return ValidationResult(False, payload, issues)
        currency = data.get('currency_code')
        if isinstance(currency, str):
            data['currency_code'] = self.currency_aliases.get(currency.lower(), currency.upper())
            if not re.fullmatch('[A-Z]{3}', data['currency_code']):
                issue('ERR_INVALID_CURRENCY', 'currency_code')
        if data.get('base_currency_code'):
            base = data['base_currency_code']
            data['base_currency_code'] = self.currency_aliases.get(base.lower(), base.upper())
            if not re.fullmatch('[A-Z]{3}', data['base_currency_code']):
                issue('ERR_INVALID_CURRENCY', 'base_currency_code')
        status_sets = {'JOURNAL_ENTRY': {'DRAFT','POSTED','REVERSED'},
                      'AP_INVOICE': {'OPEN','PAID','PARTIALLY_PAID','VOID'},
                      'FIXED_ASSET': {'ACTIVE','DISPOSED','FULLY_DEPRECIATED'}}
        if entity in status_sets:
            status = data.get('status')
            if isinstance(status, str):
                data['status'] = self.status_aliases.get(status.lower(), status.upper())
            if data.get('status') not in status_sets[entity]:
                issue('ERR_INVALID_STATUS', 'status')
        if entity == 'JOURNAL_ENTRY' and isinstance(data.get('entry_type'), str):
            value = data['entry_type'].lower()
            data['entry_type'] = self.voucher_type_aliases.get(value, value.upper())
        if entity == 'FIXED_ASSET':
            for key in ('category', 'depreciation_method'):
                if isinstance(data.get(key), str):
                    data[key] = re.sub(r'[\s&-]+', '_', data[key]).upper()
        def derive(target, left, right):
            a,b = data.get(left),data.get(right)
            if data.get(target) is None and all(isinstance(x, Decimal) and x.is_finite() for x in (a,b)):
                data[target] = a-b
        if entity == 'AP_INVOICE':
            derive('subtotal_amount','total_amount','tax_amount')
            derive('outstanding_amount','total_amount','paid_amount')
        if entity == 'FIXED_ASSET':
            derive('book_value','acquisition_cost','accumulated_depreciation')
        if entity == 'JOURNAL_ENTRY' and not data.get('fiscal_period') and isinstance(data.get('entry_date'), datetime):
            data['fiscal_period'] = data['entry_date'].strftime('%Y-%m')
        if entity == 'BANK_TRANSACTION' and isinstance(data.get('amount'), Decimal) and data['amount'].is_finite():
            payload.raw_lineage['transaction_direction'] = 'INFLOW' if data['amount'] > 0 else 'OUTFLOW' if data['amount'] < 0 else 'ZERO'
        required = {
            'JOURNAL_ENTRY': ['entry_type','external_entry_id','exchange_rate'],
            'BANK_TRANSACTION': ['bank_account_id','amount'],
            'AP_INVOICE': ['vendor_name','invoice_number'] + MONETARY_FIELDS['AP_INVOICE'],
            'FIXED_ASSET': ['asset_code','asset_name','category','depreciation_method'] + MONETARY_FIELDS['FIXED_ASSET'],
            'TRIAL_BALANCE': ['fiscal_period'] + MONETARY_FIELDS['TRIAL_BALANCE'],
        }[entity] + ['currency_code']
        for key in required:
            if data.get(key) is None:
                issue('ERR_MISSING_FIELD', key)
        if entity == 'TRIAL_BALANCE' and not (data.get('account_id') or data.get('account_name_raw')):
            issue('ERR_MISSING_ACCOUNT','account_id')
        nonnegative = {'AP_INVOICE':['subtotal_amount','tax_amount','total_amount','paid_amount'],
                      'FIXED_ASSET':['acquisition_cost','salvage_value','accumulated_depreciation'],
                      'TRIAL_BALANCE':['period_debit','period_credit']}.get(entity, [])
        for key in nonnegative:
            if isinstance(data.get(key), Decimal) and data[key].is_finite() and data[key] < 0:
                issue('ERR_NEGATIVE_AMOUNT',key)
        def known(*keys):
            return all(isinstance(data.get(k), Decimal) and data[k].is_finite() for k in keys)
        if entity == 'AP_INVOICE':
            if known('subtotal_amount','tax_amount','total_amount') and data['subtotal_amount']+data['tax_amount'] != data['total_amount']:
                issue('WARN_INVOICE_TOTAL_MISMATCH','total_amount',True)
            if known('paid_amount','total_amount') and data['paid_amount'] > data['total_amount']:
                issue('WARN_INVOICE_OVERPAYMENT','paid_amount',True)
        if entity == 'FIXED_ASSET' and known('salvage_value','acquisition_cost') and data['salvage_value'] > data['acquisition_cost']:
            issue('WARN_ASSET_SALVAGE_EXCEEDS_COST','salvage_value',True)
        if entity == 'TRIAL_BALANCE' and known('opening_balance','period_debit','period_credit','closing_balance'):
            if data['opening_balance']+data['period_debit']-data['period_credit'] != data['closing_balance']:
                issue('WARN_TRIAL_BALANCE_CONTROL','closing_balance',True)
        for first, second, code in [('invoice_date','due_date','WARN_AP_DATE_INCONSISTENCY'),
                ('acquisition_date','in_service_date','WARN_ASSET_DATE_INCONSISTENCY')]:
            if isinstance(data.get(first), datetime) and isinstance(data.get(second), datetime) and data[second] < data[first]:
                issue(code, second, True)
        if entity == 'JOURNAL_ENTRY':
            rate = data.get('exchange_rate')
            if isinstance(rate, Decimal) and rate.is_finite():
                if rate <= 0 or data.get('base_currency_code') == data.get('currency_code') and rate != 1:
                    issue('ERR_EXCHANGE_RATE', 'exchange_rate')
            total_d,total_c = Decimal(0),Decimal(0)
            for line in lines:
                if not (line.get('account_id') or line.get('account_name_raw')):
                    issue('ERR_MISSING_ACCOUNT','account_id')
                for key in ('debit_amount','credit_amount'):
                    value = line.get(key)
                    if value is None:
                        issue('ERR_MISSING_FIELD',key)
                    elif isinstance(value, Decimal) and value.is_finite() and value < 0:
                        issue('ERR_NEGATIVE_AMOUNT',key)
                debit,credit = line.get('debit_amount'),line.get('credit_amount')
                if all(isinstance(x, Decimal) and x.is_finite() for x in (debit,credit)):
                    total_d += debit; total_c += credit
                    if debit > 0 and credit > 0:
                        issue('WARN_DUAL_SIDED_POSTING','lines',True)
                    if isinstance(rate, Decimal) and rate.is_finite() and rate > 0:
                        for base,key in [('base_debit_amount','debit_amount'),('base_credit_amount','credit_amount')]:
                            if line.get(base) is None:
                                line[base] = (line[key]*rate).quantize(Decimal('0.0001'))
                            elif line[base] != (line[key]*rate).quantize(Decimal('0.0001')):
                                issue('WARN_BASE_AMOUNT_MISMATCH',base,True)
            if total_d != total_c:
                if data.get('partial_journal') is True:
                    issue('WARN_INCOMPLETE_JOURNAL','lines',True)
                    data['status'] = 'DRAFT'
                else:
                    issue('ERR_UNBALANCED_JOURNAL','lines')
        # Check derived values as well; they must fit the canonical storage precision.
        money(data, MONETARY_FIELDS[entity])
        for line in lines:
            money(line,['base_debit_amount','base_credit_amount'])
        for code in payload.flags:
            if code.startswith('WARN_') and not any(i.code == code for i in issues):
                issue(code,None,True)
        payload.flags = list(dict.fromkeys(payload.flags + [i.code for i in issues if i.severity == ValidationSeverity.WARNING]))
        return ValidationResult(not any(i.severity == ValidationSeverity.ERROR for i in issues), payload, issues)

    def process_batch(self, payloads):
        results = [self.process(p) for p in payloads]
        return ([r for r in results if r.is_valid], [r for r in results if not r.is_valid])

    def _fingerprint(self, payload):
        import hashlib, json
        data = payload.data
        keys = {'AP_INVOICE':['vendor_name','invoice_number'],
                'BANK_TRANSACTION':['bank_account_id','booking_date','amount','bank_reference'],
                'FIXED_ASSET':['asset_code'],
                'JOURNAL_ENTRY':['external_entry_id','entry_date','entry_type','currency_code','lines'],
                'TRIAL_BALANCE':['account_id','fiscal_period']}.get(payload.entity_type, [])
        values = {key:data.get(key) for key in keys}
        if payload.entity_type == 'JOURNAL_ENTRY':
            values['lines'] = [{k:l.get(k) for k in ('account_id','debit_amount','credit_amount')} for l in data.get('lines',[])]
        text = json.dumps(values,sort_keys=True,default=str).casefold()
        return hashlib.sha256((payload.entity_type+text).encode()).hexdigest()

    def detect_duplicates(self, payloads):
        seen, issues = set(), []
        for p in payloads:
            fp = self._fingerprint(p)
            if fp in seen:
                if 'WARN_POTENTIAL_BUSINESS_DUPLICATE' not in p.flags:
                    p.flags.append('WARN_POTENTIAL_BUSINESS_DUPLICATE')
                issues.append(ValidationIssue('WARN_POTENTIAL_BUSINESS_DUPLICATE',
                    'Potential business duplicate retained', severity=ValidationSeverity.WARNING,
                    row_number=p.source_row_number, sheet_name=p.sheet_name))
            seen.add(fp)
        return payloads, issues
