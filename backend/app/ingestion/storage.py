"""
Immutable raw storage and file hashing for financial file ingestion.
"""

import hashlib
import os
import shutil
from pathlib import Path
import re
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.database.models import SourceFile, ImportBatch


class DuplicateImportError(Exception):
    """Raised when an identical raw file has already been imported for the source system."""
    def __init__(self, message: str, existing_file_id: str, sha256: str):
        super().__init__(message)
        self.existing_file_id = existing_file_id
        self.sha256 = sha256


class RawStorageManager:
    """Manages immutable batch-scoped storage of uploaded raw files."""

    def __init__(self, base_storage_dir: str = "storage/raw", staging_dir: str = "storage/staged"):
        self.base_storage_dir = base_storage_dir
        self.staging_dir = staging_dir

    @staticmethod
    def validate_component(value: str) -> None:
        if not isinstance(value, str) or not value or value in (".", "..") or value.endswith((".", " ")) or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
            raise ValueError("Invalid storage path component")
        if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
            raise ValueError("Reserved storage name")

    def calculate_sha256(self, file_bytes: bytes) -> str:
        """Compute SHA-256 hash of file content."""
        hasher = hashlib.sha256()
        hasher.update(file_bytes)
        return hasher.hexdigest()

    def store_file(
        self,
        file_bytes: bytes,
        filename: str,
        batch_id: str,
        db: Optional[Session] = None,
        source_system_id: Optional[str] = None,
        check_duplicate: bool = True,
    ) -> Tuple[str, str, int]:
        """
        Store file bytes into immutable storage under batch directory.

        Returns:
            Tuple[relative_path, sha256_hash, byte_size]
        """
        self.validate_component(filename)
        self.validate_component(batch_id)
        sha256 = self.calculate_sha256(file_bytes)
        byte_size = len(file_bytes)

        # Check for accidental duplicate import against database
        if check_duplicate and db is not None and source_system_id is not None:
            existing = (
                db.query(SourceFile)
                .join(ImportBatch, SourceFile.import_batch_id == ImportBatch.id)
                .filter(SourceFile.sha256 == sha256, ImportBatch.source_system_id == source_system_id,
                        SourceFile.parse_status.in_(["PARSED", "QUARANTINED"]))
                .first()
            )
            if existing is not None:
                raise DuplicateImportError(
                    f"File '{filename}' with hash {sha256[:12]}... was already imported (SourceFile ID: {existing.id})",
                    existing_file_id=existing.id,
                    sha256=sha256,
                )

        # Ensure directory exists: storage/raw/<batch_id>/
        root = Path(self.base_storage_dir).resolve()
        batch_dir = (root / batch_id).resolve()
        if not batch_dir.is_relative_to(root):
            raise ValueError("Storage path escapes root")
        os.makedirs(batch_dir, exist_ok=True)

        target_path = (batch_dir / filename).resolve()
        if not target_path.is_relative_to(batch_dir):
            raise ValueError("Storage path escapes batch")
        with open(target_path, "xb") as f:
            f.write(file_bytes)

        # Relative path for portable storage reference
        try:
            relative_path = os.path.relpath(target_path).replace("\\", "/")
        except ValueError:
            relative_path = os.path.relpath(target_path, root).replace("\\", "/")
            # Cross-drive on Windows: path cannot be relative across drive boundaries, use absolute resolved path
            relative_path = str(target_path.resolve()).replace("\\", "/")
        return relative_path, sha256, byte_size

    def stage_file(self, file_bytes: bytes, filename: str) -> Tuple[str, str, int]:
        """Stage file bytes using SHA-256 for deduplication."""
        self.validate_component(filename)
        sha256 = self.calculate_sha256(file_bytes)
        byte_size = len(file_bytes)

        staging_root = Path(self.staging_dir).resolve()
        os.makedirs(staging_root, exist_ok=True)
        
        target_path = (staging_root / f"{sha256}_{filename}").resolve()
        if not target_path.is_relative_to(staging_root):
            raise ValueError("Storage path escapes staging")
            
        if not target_path.exists():
            with open(target_path, "xb") as f:
                f.write(file_bytes)

        try:
            relative_path = os.path.relpath(target_path).replace("\\", "/")
        except ValueError:
            relative_path = str(target_path).replace("\\", "/")
            
        return relative_path, sha256, byte_size

    def delete_file(self, relative_path: str) -> None:
        """Safely delete a stored or staged file."""
        try:
            full_path = self.resolve_path(relative_path)
            if full_path.exists():
                os.remove(full_path)
        except Exception as e:
            pass # Ignore deletion errors to avoid breaking flows

    def cleanup_staged_files(self, max_age_hours: int = 24) -> int:
        """Delete staged files older than max_age_hours."""
        import time
        staging_root = Path(self.staging_dir).resolve()
        if not staging_root.exists():
            return 0
            
        deleted_count = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for file_path in staging_root.iterdir():
            if file_path.is_file():
                try:
                    mtime = file_path.stat().st_mtime
                    if current_time - mtime > max_age_seconds:
                        file_path.unlink()
                        deleted_count += 1
                except Exception:
                    pass
        return deleted_count

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a stored raw file path, ensuring containment within storage root."""
        root = Path(self.base_storage_dir).resolve()
        staging_root = Path(self.staging_dir).resolve()
        
        # Try as-is from cwd
        try:
            cwd_candidate = Path(os.path.abspath(relative_path)).resolve()
            if cwd_candidate.exists() and (cwd_candidate.is_relative_to(root) or cwd_candidate.is_relative_to(staging_root)):
                return cwd_candidate
        except Exception:
            pass

        # Try relative to staging root (for staged files)
        full_path_staged = (staging_root / relative_path).resolve()
        if full_path_staged.is_relative_to(staging_root) and full_path_staged.exists():
            return full_path_staged

        # Try relative to raw root
        full_path_raw = (root / relative_path).resolve()
        if full_path_raw.is_relative_to(root):
            return full_path_raw

        raise ValueError("Storage path escapes root and staging")

    def read_file(self, relative_path: str) -> bytes:
        """Read bytes of an existing stored raw file."""
        full_path = self.resolve_path(relative_path)
        with open(full_path, "rb") as f:
            return f.read()
