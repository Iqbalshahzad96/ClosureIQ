"""Raw-body financial upload. Account/source setup is explicit; no ERP logic here."""
import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.ingestion.service import IngestionService, MAX_UPLOAD_BYTES, json_safe

router = APIRouter(prefix="/imports", tags=["Financial imports"])


def get_ingestion_service():
    return IngestionService()


@router.post("/upload")
async def upload(request: Request, filename: str = Query(...),
                 source_system_id: str | None = Query(default=None), organization_id: str = "default_org",
                 adapter_key: str | None = None, batch_id: str | None = None,
                 x_import_options: str = Header(default="{}"),
                 db: Session = Depends(get_db), service: IngestionService = Depends(get_ingestion_service)):
    """Send CSV/Excel bytes as the body and optional JSON adapter settings in X-Import-Options."""
    try:
        options = json.loads(x_import_options)
        if not isinstance(options, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "X-Import-Options must be a JSON object")
    content = bytearray()
    async for part in request.stream():
        if len(content) + len(part) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Upload exceeds 25 MiB")
        content.extend(part)
    try:
        summary = await run_in_threadpool(service.ingest_file, db, bytes(content), filename,
                    organization_id, source_system_id, batch_id, adapter_key, options)
        return json_safe(asdict(summary))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        raise HTTPException(500, "Import could not be completed") from None

from pydantic import BaseModel

class ConfirmImportRequest(BaseModel):
    file_id: str
    filename: str
    options: dict

@router.post("/stage")
async def stage(request: Request, filename: str = Query(...),
                service: IngestionService = Depends(get_ingestion_service)):
    """Stage file upload for context detection."""
    content = bytearray()
    async for part in request.stream():
        if len(content) + len(part) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Upload exceeds 25 MiB")
        content.extend(part)
    try:
        result = await run_in_threadpool(service.stage_file, bytes(content), filename)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        raise HTTPException(500, "File staging failed") from None


@router.post("/confirm")
async def confirm(payload: ConfirmImportRequest,
                  source_system_id: str | None = Query(default=None), 
                  organization_id: str = "default_org",
                  adapter_key: str | None = None, 
                  batch_id: str | None = None,
                  db: Session = Depends(get_db), 
                  service: IngestionService = Depends(get_ingestion_service)):
    """Confirm a staged import and run ingestion pipeline."""
    try:
        content = await run_in_threadpool(service.storage.read_file, payload.file_id)
    except Exception:
        raise HTTPException(404, "Staged file not found") from None

    try:
        summary = await run_in_threadpool(
            service.ingest_file, db, content, payload.filename,
            organization_id, source_system_id, batch_id, adapter_key, payload.options
        )
        return json_safe(asdict(summary))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        raise HTTPException(500, "Import could not be completed") from None
    finally:
        await run_in_threadpool(service.storage.delete_file, payload.file_id)

