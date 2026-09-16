"""Canonical ingestion with immutable files, bounded row chunks and row savepoints.

Use a dedicated Session. Single-process import serialization matches the current
ClosureIQ deployment contract; distributed import locking is not implemented.
"""
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from itertools import islice
from pathlib import Path

from sqlalchemy import func
from app.database.models import (APInvoice, Account, AuditEvent, BankAccount,
    BankTransaction, FixedAsset, ImportBatch, JournalEntry, JournalLine,
    SourceAccountMapping, SourceFile, SourceSystem, TrialBalanceRecord)
from app.ingestion.adapters.registry import default_adapter_registry
from app.ingestion.base import BatchIngestionSummary, RowRole, ValidationIssue, ValidationSeverity
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.storage import RawStorageManager

logger = logging.getLogger(__name__)
_IMPORT_LOCK = threading.RLock()
PERSISTENCE_CHUNK_SIZE = 500
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (Decimal,datetime)):
        return str(value)
    if hasattr(value, 'value'):
        return value.value
    return value


class IngestionService:
    def __init__(self, storage=None, registry=None, pipeline=None, chunk_size=PERSISTENCE_CHUNK_SIZE):
        if not isinstance(chunk_size,int) or chunk_size <= 0:
            raise ValueError('chunk_size must be positive')
        self.storage = storage or RawStorageManager()
        self.registry = registry or default_adapter_registry
        self.pipeline = pipeline or IngestionPipeline()
        self.chunk_size = chunk_size

    def ingest_path(self, db, path, **kwargs):
        path = Path(path)
        with path.open('rb') as stream:
            content = stream.read(MAX_UPLOAD_BYTES + 1)
        return self.ingest_file(db,content,path.name,**kwargs)

    def ingest_file(self, db, file_bytes, filename, organization_id='default_org',
                    source_system_id=None, batch_id=None, adapter_key=None, options=None):
        if not isinstance(file_bytes,bytes) or not file_bytes or len(file_bytes)>MAX_UPLOAD_BYTES:
            raise ValueError('Upload must contain between 1 byte and 25 MiB')
        self.storage.validate_component(filename)
        if batch_id:
            self.storage.validate_component(batch_id)
        if not isinstance(organization_id,str) or not organization_id.strip():
            raise ValueError('organization_id is required')
        with _IMPORT_LOCK:
            try:
                return self._ingest(db,file_bytes,filename,organization_id,source_system_id,
                                    batch_id,adapter_key,dict(options or {}))
            except Exception:
                db.rollback()
                raise


    def stage_file(self, file_bytes: bytes, filename: str) -> dict:
        from app.ingestion.detector import detect_context
        
        relative_path, sha, size = self.storage.stage_file(
            file_bytes, filename
        )
        context = detect_context(file_bytes, filename)
        return {
            "file_id": relative_path,
            "filename": filename,
            "size": size,
            "detected_context": context,
        }

    def _ingest(self, db, content, filename, org, source_id, batch_id, adapter_key, options):
        source = db.get(SourceSystem,source_id) if source_id else None
        if source_id and (source is None or source.organization_id != org or not source.is_active):
            raise ValueError('Invalid source system for organization')
        if source is None:
            source = db.query(SourceSystem).filter_by(organization_id=org,
                         adapter_key=adapter_key or 'auto', display_name='Runtime uploads').first()
            if source is None:
                source = SourceSystem(organization_id=org,adapter_key=adapter_key or 'auto',
                                      source_type='MANUAL',display_name='Runtime uploads')
                db.add(source); db.flush()
        batch = db.get(ImportBatch,batch_id) if batch_id else None
        if batch and (batch.source_system_id != source.id or batch.organization_id != org):
            raise ValueError('Batch scope does not match source system and organization')
        sha = self.storage.calculate_sha256(content)
        prior = db.query(SourceFile).join(ImportBatch).filter(
            ImportBatch.source_system_id==source.id, ImportBatch.organization_id==org,
            SourceFile.sha256==sha, SourceFile.parse_status.in_(['PARSED','QUARANTINED'])).first()
        if prior:
            result = BatchIngestionSummary(batch_id=prior.import_batch_id,source_system_id=source.id,
                     source_file_id=prior.id,status='DUPLICATE',duplicate_files=1)
            result.warnings.append({'code':'WARN_TECHNICAL_DUPLICATE_FILE','existing_file_id':prior.id})
            db.commit()
            return result
        if batch is None:
            batch = ImportBatch(source_system_id=source.id,organization_id=org,status='PROCESSING')
            if batch_id:
                batch.id=batch_id
            db.add(batch); db.flush()
        batch.status='PROCESSING'
        file = SourceFile(import_batch_id=batch.id,original_filename=filename,relative_raw_path='',
                          sha256=sha,byte_size=len(content),parse_status='PENDING')
        db.add(file); db.flush()
        summary = BatchIngestionSummary(batch.id,source.id,source_file_id=file.id)
        try:
            path,_,_ = self.storage.store_file(content,filename,batch.id,check_duplicate=False)
            file.relative_raw_path=path
            summary.files_processed=1
            adapter = self.registry.resolve_adapter(content,filename,adapter_key or
                      (source.adapter_key if source.adapter_key != 'auto' else None))
            if adapter is None:
                raise ValueError('ERR_NO_ADAPTER')
            file.file_metadata_json={'adapter_key':adapter.get_adapter_key(),'options':json_safe(options)}
            # A parser failure rolls back all canonical rows for this file, retaining raw evidence.
            with db.begin_nested():
                rows = iter(adapter.parse_file(content,filename,options))
                try:
                    while chunk := list(islice(rows,self.chunk_size)):
                        for row in chunk:
                            if row.role != RowRole.TRANSACTION:
                                summary.skipped_rows += 1
                                self._audit(db,batch,file,row,None,'INGEST_CONTROL',{'role':row.role.value})
                                continue
                            summary.total_rows += 1
                            identity = f'{row.sheet_name}:R{row.row_number}'
                            technical = db.query(AuditEvent.id).filter(
                                AuditEvent.import_batch_id==batch.id,
                                AuditEvent.details['source_file_id'].as_string()==file.id,
                                AuditEvent.details['source_row_identifier'].as_string()==identity).first()
                            if technical:
                                summary.technical_duplicate_rows += 1
                                continue
                            try:
                                payloads=adapter.map_to_canonical([row],options)
                                if len(payloads)!=1:
                                    raise ValueError('Mapping must produce one canonical record per transaction row')
                                payload=payloads[0]
                                payload.source_file_id=file.id; payload.import_batch_id=batch.id
                                payload.raw_lineage.update(source_system_id=source.id,import_batch_id=batch.id,source_file_id=file.id)
                                result=self.pipeline.process(payload)
                                payload=result.payload
                                if result.is_valid:
                                    self._references(db,payload,source,org)
                                if not result.is_valid:
                                    self._reject(db,batch,file,row,payload,summary,[asdict(i) for i in result.errors])
                                    continue
                                fingerprint=self.pipeline._fingerprint(payload)
                                duplicate=db.query(AuditEvent.id).filter(AuditEvent.organization_id==org,
                                    AuditEvent.event_type=='INGEST_IMPORTED',
                                    AuditEvent.details['fingerprint'].as_string()==fingerprint).first()
                                warnings=[asdict(i) for i in result.warnings]
                                if duplicate:
                                    summary.business_duplicate_rows+=1
                                    payload.flags.append('WARN_POTENTIAL_BUSINESS_DUPLICATE')
                                    warnings.append({'code':'WARN_POTENTIAL_BUSINESS_DUPLICATE',
                                                     'message':'Potential business duplicate retained'})
                                with db.begin_nested():
                                    record=self._persist(db,payload,org)
                                    db.flush()
                                    self._audit(db,batch,file,row,payload,'INGEST_IMPORTED',
                                        {'record_id':record.id,'entity_type':payload.entity_type,
                                         'fingerprint':fingerprint,'warnings':warnings})
                                    db.flush()
                                summary.valid_rows+=1
                                if warnings:
                                    summary.warning_rows+=1
                                    summary.warnings.extend([{'row_number':row.row_number,'sheet_name':row.sheet_name,**w}
                                                             for w in warnings][:max(0,100-len(summary.warnings))])
                            except ReferenceError as exc:
                                self._reject(db,batch,file,row,None,summary,[{'code':str(exc),'message':'Invalid canonical reference'}])
                            except Exception:
                                # Never include SQL statements/parameters or financial row contents in logs/errors.
                                self._reject(db,batch,file,row,None,summary,[{'code':'ERR_ROW_PROCESSING','message':'Row could not be mapped or persisted'}])
                        db.flush()
                finally:
                    close=getattr(rows,'close',None)
                    if close: close()
            file.parse_status='PARSED' if not summary.quarantined_rows else 'QUARANTINED'
            summary.status='COMPLETED' if not summary.quarantined_rows else 'PARTIAL' if summary.valid_rows else 'QUARANTINED'
        except Exception as exc:
            exc_str = str(exc)
            safe_messages = {
                'ERR_NO_ADAPTER': 'No supported parser matched this file. Check that the file has recognizable financial columns.',
                'Required table headers not found': 'Required table headers were not found. Check the detected document type and file columns.',
                'Ambiguous duplicate headers': 'Duplicate column headers were found. Rename duplicate columns and retry.',
                'Unsupported binary format': 'Unsupported binary spreadsheet format. Please upload CSV, XLSX, or XLS.',
            }
            safe_message = safe_messages.get(
                exc_str,
                f'File parsing or storage failed; no records imported. (Error: {exc_str})',
            )
            if exc_str.startswith("Missing required columns:"):
                safe_message = exc_str
            summary.status='FAILED'; file.parse_status='FAILED'
            summary.valid_rows=0; summary.quarantined_rows=summary.total_rows
            summary.warning_rows=0; summary.business_duplicate_rows=0
            summary.errors=[{'code':'ERR_NO_ADAPTER' if str(exc)=='ERR_NO_ADAPTER' else 'ERR_FILE_PROCESSING',
                             'message':safe_message}]
            self._audit(db,batch,file,None,None,'INGEST_FILE_FAILED',{'errors':summary.errors})
        batch.file_count=(batch.file_count or 0)+summary.files_processed
        batch.total_rows=(batch.total_rows or 0)+summary.total_rows
        batch.valid_rows=(batch.valid_rows or 0)+summary.valid_rows
        batch.error_rows=(batch.error_rows or 0)+summary.quarantined_rows
        batch.status=summary.status
        batch.completed_at=datetime.now(timezone.utc)
        previous=dict(batch.validation_summary_json or {})
        files=list(previous.get('files',[])); files.append(json_safe(asdict(summary)))
        if any(f['status'] in ('FAILED','QUARANTINED','PARTIAL') for f in files):
            batch.status='PARTIAL' if batch.valid_rows else 'FAILED' if any(f['status']=='FAILED' for f in files) else 'QUARANTINED'
        summary.status=batch.status
        batch.validation_summary_json={'files':files,'total_rows':batch.total_rows,
             'valid_rows':batch.valid_rows,'error_rows':batch.error_rows}
        db.commit()
        if summary.status == 'FAILED' or (summary.valid_rows == 0 and summary.quarantined_rows > 0):
            try:
                self.storage.delete_file(file.relative_raw_path)
            except Exception:
                logger.warning('Failed to clean up raw file for failed batch %s', batch.id)
        logger.info('Ingestion finished status=%s total=%d imported=%d rejected=%d',
                    summary.status,summary.total_rows,summary.valid_rows,summary.quarantined_rows)
        return summary

    def _audit(self,db,batch,file,row,payload,event,details):
        identity=f'{row.sheet_name}:R{row.row_number}' if row else None
        db.add(AuditEvent(organization_id=batch.organization_id,import_batch_id=batch.id,
            event_type=event,actor='ingestion',details=json_safe({
                'source_file_id':file.id,'source_row_identifier':identity,
                'sheet_name':row.sheet_name if row else None,'row_number':row.row_number if row else None,
                'lineage':payload.raw_lineage if payload else {},**details})))
        db.flush()

    def _reject(self,db,batch,file,row,payload,summary,errors):
        summary.quarantined_rows+=1
        self._audit(db,batch,file,row,payload,'INGEST_QUARANTINED',
                    {'errors':errors,'warnings':payload.flags if payload else []})
        summary.errors.extend([{'row_number':row.row_number,'sheet_name':row.sheet_name,**e}
                               for e in errors][:max(0,100-len(summary.errors))])

    def _account(self,db,data,source,org):
        account_id=data.get('account_id')
        key=data.get('account_name_raw') or 'Suspense'
        if account_id is None:
            matches=db.query(SourceAccountMapping).filter_by(source_system_id=source.id,
                source_account_key=key).all()
            if len(matches)!=1 or matches[0].mapping_status not in ('REVIEWED','AUTO_MAPPED'):
                account = Account(organization_id=org, account_name=key, normalized_name=key.upper(), account_type="EXPENSE", currency_code=data.get('currency_code', 'USD'))
                db.add(account)
                db.flush()
                if len(matches) == 1:
                    matches[0].account_id = account.id
                    matches[0].mapping_status = 'AUTO_MAPPED'
                else:
                    db.add(SourceAccountMapping(source_system_id=source.id, source_account_key=key, account_id=account.id, raw_account_name=key, mapping_status='AUTO_MAPPED'))
                account_id = account.id
            else:
                account_id=matches[0].account_id
        account=db.get(Account,account_id)
        if account is None or account.organization_id != org or not account.is_active:
            account = Account(organization_id=org, account_name=key, normalized_name=key.upper(), account_type="EXPENSE", currency_code=data.get('currency_code', 'USD'))
            db.add(account)
            db.flush()
        data['account_id']=account.id
        return account

    def _references(self,db,payload,source,org):
        data=payload.data
        if payload.entity_type=='JOURNAL_ENTRY':
            for line in data['lines']:
                account=self._account(db,line,source,org)
        elif payload.entity_type=='TRIAL_BALANCE':
            account=self._account(db,data,source,org)
        elif payload.entity_type=='BANK_TRANSACTION':
            bank_acct_key = data.get('bank_account_id') or 'UNKNOWN'
            account = db.get(BankAccount, bank_acct_key)
            if account is None and bank_acct_key:
                account = db.query(BankAccount).filter_by(
                    organization_id=org, 
                    account_number_masked=bank_acct_key,
                    is_active=True
                ).first()
            if account is None:
                bank_name = data.get('bank_name') or "Commercial Bank"
                account_name = data.get('account_name') or f"Account {bank_acct_key}"
                
                if "DTB" in bank_acct_key.upper() or "DIAMOND" in str(data.get('bank_name') or '').upper():
                    bank_name = "Diamond Trust Bank Kenya Limited"
                    account_name = "Diamond Trust Bank-KES Credit Card" if "CC" in bank_acct_key.upper() else "Diamond Trust Bank KSHS (Operating)"
                elif "PRIME" in bank_acct_key.upper() or "PRIME" in str(data.get('bank_name') or '').upper():
                    bank_name = "Prime Bank Limited"
                    account_name = "Prime Bank KSHS (Commercial Current)"
                    
                account = BankAccount(
                    organization_id=org,
                    bank_name=bank_name,
                    account_number_masked=bank_acct_key,
                    account_name=account_name,
                    currency_code=data.get('currency_code', 'KES')
                )
                db.add(account)
                db.flush()
            elif account.bank_name in ("Suspense Bank", "UNKNOWN", "Suspense"):
                if "DTB" in account.account_number_masked.upper() or "DIAMOND" in str(data.get('bank_name') or '').upper():
                    account.bank_name = "Diamond Trust Bank Kenya Limited"
                    account.account_name = "Diamond Trust Bank-KES Credit Card" if "CC" in account.account_number_masked.upper() else "Diamond Trust Bank KSHS (Operating)"
                elif "PRIME" in account.account_number_masked.upper() or "PRIME" in str(data.get('bank_name') or '').upper():
                    account.bank_name = "Prime Bank Limited"
                    account.account_name = "Prime Bank KSHS (Commercial Current)"
                db.flush()
                
            if account.linked_gl_account_id is None:
                from sqlalchemy import or_
                gl_matches = db.query(Account).filter(
                    Account.organization_id == org,
                    Account.is_active == True,
                    or_(
                        Account.account_code == account.account_number_masked,
                        Account.account_name.ilike(f"%{account.bank_name}%"),
                        Account.account_name.ilike(f"%{account.account_name}%"),
                        Account.account_name.ilike("%DIAMOND TRUST BANK%" if "DTB" in account.account_number_masked.upper() else "%PRIME BANK%" if "PRIME" in account.account_number_masked.upper() else "%BANK%"),
                        Account.normalized_name == account.account_name.upper()
                    )
                ).all()
                if "CC" in account.account_number_masked.upper():
                    cc_gl = [g for g in gl_matches if "CREDIT CARD" in g.account_name.upper()]
                    if cc_gl:
                        account.linked_gl_account_id = cc_gl[0].id
                elif "DTB" in account.account_number_masked.upper():
                    dtb_gl = [g for g in gl_matches if "CREDIT CARD" not in g.account_name.upper() and "DIAMOND" in g.account_name.upper()]
                    if dtb_gl:
                        account.linked_gl_account_id = dtb_gl[0].id
                elif "PRIME" in account.account_number_masked.upper():
                    prime_gl = [g for g in gl_matches if "PRIME" in g.account_name.upper()]
                    if prime_gl:
                        account.linked_gl_account_id = prime_gl[0].id
                elif len(gl_matches) == 1:
                    account.linked_gl_account_id = gl_matches[0].id
                db.flush()
                    
            data['bank_account_id'] = account.id
        for key in ('gl_account_id','asset_account_id','accum_deprec_account_id','deprec_expense_account_id'):
            if data.get(key):
                self._account(db,{'account_id':data[key]},source,org)

    def _persist(self,db,payload,org):
        data=dict(payload.data)
        entity=payload.entity_type
        models={'BANK_TRANSACTION':BankTransaction,'AP_INVOICE':APInvoice,
                'FIXED_ASSET':FixedAsset,'TRIAL_BALANCE':TrialBalanceRecord,'JOURNAL_ENTRY':JournalEntry}
        model=models[entity]
        allowed={c.name for c in model.__table__.columns} - {'id','created_at','updated_at'}
        values={key:value for key,value in data.items() if key in allowed}
        values['import_batch_id']=payload.import_batch_id
        if 'organization_id' in allowed: values['organization_id']=org
        if entity=='JOURNAL_ENTRY': values['source_file_id']=payload.source_file_id
        # Source markers can never approve/reconcile a canonical record.
        if 'is_reconciled' in allowed: values['is_reconciled']=False
        record=model(**values)
        db.add(record); db.flush()
        if entity=='JOURNAL_ENTRY':
            keys={c.name for c in JournalLine.__table__.columns}-{'id','created_at','journal_entry_id'}
            for i,line in enumerate(data['lines'],1):
                values={k:v for k,v in line.items() if k in keys}
                values['line_number']=i
                values['is_reconciled']=False
                values['dimensions_json']={**line.get('dimensions_json',{}),
                    'source_file_id':payload.source_file_id,'sheet_name':payload.sheet_name,
                    'source_row_number':payload.source_row_number,'warnings':payload.flags}
                db.add(JournalLine(journal_entry_id=record.id,**values))
        return record
