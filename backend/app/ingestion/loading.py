"""Explicit local source loading through Phase 2; never used by runtime startup.

The private manifest owns source paths and reviewed mappings. This module writes
master/configuration rows only; financial rows belong to IngestionService.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import inspect, select

from app.database.models import (
    Account, BankAccount, SourceAccountMapping, SourceSystem, SourceFile,
    ImportBatch, AuditEvent, JournalEntry, JournalLine, BankTransaction,
    APInvoice, FixedAsset, TrialBalanceRecord,
)
from app.ingestion.service import IngestionService, MAX_UPLOAD_BYTES

Key = Annotated[str, StringConstraints(pattern=r'^[a-zA-Z0-9_-]{1,64}$')]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Currency = Annotated[str, StringConstraints(pattern=r'^[A-Z]{3}$')]
AdapterKey = Literal['enquest_ledger', 'enquest_tb', 'generic_bank',
                     'generic_ap_invoice', 'generic_fixed_asset']


class LoadError(ValueError):
    """Public errors contain no source paths, mapping labels or row values."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AccountSpec(StrictModel):
    key: Key
    account_code: Annotated[Text, Field(max_length=64)]
    account_name: Annotated[Text, Field(max_length=255)]
    account_type: Literal['ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE']
    normal_balance: Literal['DEBIT', 'CREDIT']
    currency_code: Currency


class SourceSpec(StrictModel):
    key: Key
    adapter_key: AdapterKey
    source_type: Literal['ERP', 'BANK', 'SUB_LEDGER', 'MANUAL']
    display_name: Annotated[Text, Field(max_length=128)]


class MappingSpec(StrictModel):
    source_key: Key
    source_account_key: Annotated[Text, Field(max_length=255)]
    account_key: Key
    reviewed_by: Annotated[Text, Field(max_length=128)]


class BankSpec(StrictModel):
    key: Key
    bank_name: Annotated[Text, Field(max_length=128)]
    account_name: Annotated[Text, Field(max_length=255)]
    account_number_masked: Annotated[Text, Field(max_length=64)]
    gl_account_key: Key
    currency_code: Currency


class Options(StrictModel):
    currency_code: Currency | None = None
    fiscal_period: Annotated[Text, Field(max_length=32)] | None = None
    bank_account_key: Key | None = None
    useful_life_unit: Literal['months', 'years'] | None = None


class FileSpec(StrictModel):
    source_key: Key
    path: Text
    options: Options = Field(default_factory=Options)


class LoadPlan(StrictModel):
    version: Literal[1]
    organization_id: Key
    source_root: Text = '.'
    accounts: list[AccountSpec] = Field(default_factory=list)
    sources: list[SourceSpec] = Field(min_length=1)
    mappings: list[MappingSpec] = Field(default_factory=list)
    bank_accounts: list[BankSpec] = Field(default_factory=list)
    files: list[FileSpec] = Field(min_length=1)

    @model_validator(mode='after')
    def references(self):
        for items in (self.accounts, self.sources, self.bank_accounts):
            if len({x.key for x in items}) != len(items):
                raise ValueError('Duplicate configuration key')
        if len({x.account_code for x in self.accounts}) != len(self.accounts):
            raise ValueError('Duplicate account code')
        accounts = {x.key: x for x in self.accounts}
        sources = {x.key: x for x in self.sources}
        banks = {x.key: x for x in self.bank_accounts}
        if len({(x.source_key, x.source_account_key) for x in self.mappings}) != len(self.mappings):
            raise ValueError('Duplicate source mapping')
        for mapping in self.mappings:
            if mapping.source_key not in sources or mapping.account_key not in accounts:
                raise ValueError('Unknown mapping reference')
        for bank in self.bank_accounts:
            if bank.gl_account_key not in accounts or accounts[bank.gl_account_key].currency_code != bank.currency_code:
                raise ValueError('Bank GL reference/currency mismatch')
        for file in self.files:
            if file.source_key not in sources:
                raise ValueError('Unknown file source')
            key = sources[file.source_key].adapter_key
            bank_key = file.options.bank_account_key
            if bank_key is not None and key != 'generic_bank':
                raise ValueError('Bank context requires bank adapter')
            if key == 'generic_bank' and bank_key not in banks:
                raise ValueError('Explicit bank mapping required')
            if bank_key and file.options.currency_code not in (None, banks[bank_key].currency_code):
                raise ValueError('Bank option currency mismatch')
            if key == 'enquest_tb' and (not file.options.currency_code or not file.options.fiscal_period):
                raise ValueError('Explicit trial balance currency/period required')
        return self


def read_plan(path):
    try:
        return LoadPlan.model_validate_json(Path(path).read_text(encoding='utf-8'))
    except Exception:
        raise LoadError('Invalid load manifest; check its schema and explicit references') from None


def context_id(plan, kind, key):
    return str(uuid5(NAMESPACE_URL, f'closureiq:local-load:{plan.organization_id}:{kind}:{key}'))


def resolve_files(plan, manifest_directory):
    """Preflight all files before any database writes; never expand wildcards."""
    root = (Path(manifest_directory) / plan.source_root).resolve()
    paths = []
    for entry in plan.files:
        relative = Path(entry.path)
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
            raise LoadError('Source file missing or outside configured source root')
        if not 0 < path.stat().st_size <= MAX_UPLOAD_BYTES:
            raise LoadError('Source file is empty or exceeds the ingestion size limit')
        IngestionService().storage.validate_component(path.name)
        if path in paths:
            raise LoadError('Repeated source path in load manifest')
        paths.append(path)
    return paths


def validate_schema(engine):
    """create_all is not a migration; reject incomplete existing schemas."""
    inspector = inspect(engine)
    for model in (Account, BankAccount, SourceAccountMapping, SourceSystem, SourceFile,
                  ImportBatch, AuditEvent, JournalEntry, JournalLine, BankTransaction,
                  APInvoice, FixedAsset, TrialBalanceRecord):
        table = model.__table__
        if not inspector.has_table(table.name):
            raise LoadError('Canonical schema missing; initialize a clean database first')
        if not set(table.columns.keys()) <= {c['name'] for c in inspector.get_columns(table.name)}:
            raise LoadError('Existing schema requires a separate migration')


def prepare_context(db, plan):
    """Create explicit masters atomically; reject conflicting existing values."""
    counts = Counter()

    def ensure(model, ident, values):
        row = db.get(model, ident)
        if row is None:
            row = model(id=ident, **values)
            db.add(row)
            counts[model.__tablename__] += 1
        elif any(getattr(row, key) != value for key, value in values.items()):
            raise LoadError('Existing canonical context conflicts with the reviewed manifest')
        db.flush()
        return row

    try:
        for spec in plan.accounts:
            ident = context_id(plan, 'account', spec.key)
            collisions = db.scalars(select(Account).where(Account.organization_id == plan.organization_id,
                Account.account_code == spec.account_code)).all()
            if any(x.id != ident for x in collisions):
                raise LoadError('Account code already exists under a different master identity')
            ensure(Account, ident, dict(organization_id=plan.organization_id,
                **spec.model_dump(exclude={'key'}), normalized_name=spec.account_name.casefold(), is_active=True))
        for spec in plan.sources:
            ensure(SourceSystem, context_id(plan, 'source', spec.key), dict(
                organization_id=plan.organization_id, **spec.model_dump(exclude={'key'}), is_active=True))
        for spec in plan.mappings:
            source_id = context_id(plan, 'source', spec.source_key)
            ident = context_id(plan, 'mapping', f'{spec.source_key}:{spec.source_account_key}')
            existing = db.scalars(select(SourceAccountMapping).where(
                SourceAccountMapping.source_system_id == source_id,
                SourceAccountMapping.source_account_key == spec.source_account_key)).all()
            if any(x.id != ident for x in existing):
                raise LoadError('Source mapping already exists under a different master identity')
            row = ensure(SourceAccountMapping, ident, dict(source_system_id=source_id,
                source_account_key=spec.source_account_key, account_id=context_id(plan, 'account', spec.account_key),
                mapping_status='REVIEWED', reviewed_by=spec.reviewed_by))
            if row.reviewed_at is None:
                row.reviewed_at = datetime.now(timezone.utc)
        for spec in plan.bank_accounts:
            ensure(BankAccount, context_id(plan, 'bank', spec.key), dict(
                organization_id=plan.organization_id, **spec.model_dump(exclude={'key', 'gl_account_key'}),
                linked_gl_account_id=context_id(plan, 'account', spec.gl_account_key), is_active=True))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return dict(counts)


def file_options(plan, entry):
    options = entry.options.model_dump(exclude_none=True, exclude={'bank_account_key'})
    if entry.options.bank_account_key:
        options['bank_account_id'] = context_id(plan, 'bank', entry.options.bank_account_key)
    return options


def load_sources(factory, plan, manifest_directory, storage):
    paths = resolve_files(plan, manifest_directory)
    sources = {x.key: x for x in plan.sources}
    service = IngestionService(storage=storage)
    # Check replay options before changing master context or importing another file.
    with factory() as db:
        validate_schema(db.get_bind())
        planned_content = {}
        for entry, path in zip(plan.files, paths):
            source_id = context_id(plan, 'source', entry.source_key)
            with path.open('rb') as stream:
                sha = service.storage.calculate_sha256(stream.read(MAX_UPLOAD_BYTES + 1))
            adapter = sources[entry.source_key].adapter_key
            contract = (adapter, file_options(plan, entry), path.name if adapter == 'enquest_ledger' else None)
            identity = (source_id, sha)
            if identity in planned_content and planned_content[identity] != contract:
                raise LoadError('Identical planned source bytes have conflicting mapping options')
            planned_content[identity] = contract
            prior = db.scalar(select(SourceFile).join(ImportBatch).where(
                ImportBatch.organization_id == plan.organization_id,
                ImportBatch.source_system_id == source_id, SourceFile.sha256 == sha,
                SourceFile.parse_status.in_(['PARSED', 'QUARANTINED'])))
            if prior:
                metadata = prior.file_metadata_json or {}
                if (metadata.get('adapter_key') != adapter or metadata.get('options') != file_options(plan, entry)
                        or adapter == 'enquest_ledger' and prior.original_filename != path.name):
                    raise LoadError('Previously imported bytes have different mapping options; explicit reprocessing is required')
        created = prepare_context(db, plan)
    results = []
    for number, (entry, path) in enumerate(zip(plan.files, paths), 1):
        adapter = sources[entry.source_key].adapter_key
        with factory() as db:
            summary = service.ingest_path(db, path, organization_id=plan.organization_id,
                source_system_id=context_id(plan, 'source', entry.source_key), adapter_key=adapter,
                options=file_options(plan, entry))
            # Full audit diagnostics, rather than the capped inline summary.
            codes = Counter()
            retained = Counter()
            events = db.scalars(select(AuditEvent).where(AuditEvent.import_batch_id == summary.batch_id)).all()
            for audit in events:
                if audit.details.get('source_file_id') != summary.source_file_id:
                    continue
                retained[audit.event_type] += 1
                for field in ('errors', 'warnings'):
                    for item in audit.details.get(field, []):
                        if isinstance(item, dict) and str(item.get('code', '')).startswith(('ERR_', 'WARN_')):
                            codes[item['code']] += 1
            results.append(dict(file_number=number, adapter_key=adapter, status=summary.status,
                source_file_id=summary.source_file_id, batch_id=summary.batch_id,
                total_rows=summary.total_rows, imported_rows=summary.valid_rows,
                quarantined_rows=summary.quarantined_rows, warning_rows=summary.warning_rows,
                duplicate_files=summary.duplicate_files, skipped_rows=summary.skipped_rows,
                retained_imported_rows=retained['INGEST_IMPORTED'],
                retained_quarantined_rows=retained['INGEST_QUARANTINED'],
                stored_parse_status=db.get(SourceFile, summary.source_file_id).parse_status,
                diagnostic_codes=dict(codes)))
    return {'created_context': created, 'files': results}


def verify_canonical(factory, plan):
    """Count scoped entities and validate ingestion lineage; return no row contents."""
    from sqlalchemy import func
    models = {'JOURNAL_ENTRY': JournalEntry, 'BANK_TRANSACTION': BankTransaction,
              'AP_INVOICE': APInvoice, 'FIXED_ASSET': FixedAsset, 'TRIAL_BALANCE': TrialBalanceRecord}
    counts = {}
    issues = Counter()
    with factory() as db:
        batches = db.scalars(select(ImportBatch).where(ImportBatch.organization_id == plan.organization_id)).all()
        batch_ids = [b.id for b in batches]
        files = {f.id: f for f in db.scalars(select(SourceFile).where(SourceFile.import_batch_id.in_(batch_ids)))}
        seen = set()
        for audit in db.scalars(select(AuditEvent).where(AuditEvent.import_batch_id.in_(batch_ids),
                                                      AuditEvent.event_type == 'INGEST_IMPORTED')):
            detail = audit.details
            source_file = files.get(detail.get('source_file_id'))
            model = models.get(detail.get('entity_type'))
            record = db.get(model, detail.get('record_id')) if model else None
            if (source_file is None or source_file.import_batch_id != audit.import_batch_id
                    or record is None or record.import_batch_id != audit.import_batch_id
                    or not detail.get('source_row_identifier')):
                issues['invalid_audit_lineage'] += 1
                continue
            seen.add((detail['entity_type'], record.id))
            if model is JournalEntry:
                if record.source_file_id != source_file.id or not record.lines:
                    issues['invalid_journal_lineage'] += 1
                for line in record.lines:
                    if (line.account.organization_id != plan.organization_id
                            or line.dimensions_json.get('source_file_id') != source_file.id):
                        issues['invalid_journal_account_or_source'] += 1
            if model is BankTransaction:
                bank = record.bank_account
                if (bank.organization_id != plan.organization_id or bank.gl_account is None
                        or bank.gl_account.organization_id != plan.organization_id
                        or record.currency_code != bank.currency_code
                        or bank.gl_account.currency_code != bank.currency_code):
                    issues['invalid_bank_mapping'] += 1
        for entity, model in models.items():
            records = db.scalars(select(model).where(model.import_batch_id.in_(batch_ids))).all()
            counts[model.__tablename__] = len(records)
            issues['missing_import_audit'] += sum((entity, r.id) not in seen for r in records)
        counts['journal_lines'] = db.scalar(select(func.count()).select_from(JournalLine).join(JournalEntry).where(JournalEntry.import_batch_id.in_(batch_ids)))
        counts.update(import_batches=len(batches), source_files=len(files))
    return {'counts': counts, 'lineage_issues': {k: v for k, v in issues.items() if v}}


async def verify_mcp(factory, plan):
    """Use existing canonical tools; never expose transactions in loader output."""
    from app.mcp.tools import FinancialMCPTools
    tools = FinancialMCPTools(factory, organization_id=plan.organization_id)
    results = []
    for number, account in enumerate(plan.accounts, 1):
        gl = await tools.query_gl_transactions(account.account_code, limit=100)
        bank = await tools.query_bank_transactions(account.account_code, limit=100)
        results.append(dict(account_number=number, gl_rows_returned=len(gl), bank_rows_returned=len(bank)))
    return {'query_limit_per_account': 100, 'accounts': results}
