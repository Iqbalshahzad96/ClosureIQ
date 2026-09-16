import os
import time
import pytest
from pathlib import Path
from app.ingestion.storage import RawStorageManager

def test_stage_and_cleanup_files(tmp_path):
    storage = RawStorageManager(base_storage_dir=str(tmp_path / "raw"), staging_dir=str(tmp_path / "staged"))
    
    # Stage a file
    rel_path, sha, size = storage.stage_file(b"test content", "test.csv")
    assert "test.csv" in rel_path
    
    # Verify file is in staging dir
    staged_file = storage.resolve_path(rel_path)
    assert staged_file.exists()
    assert staged_file.parent == Path(storage.staging_dir).resolve()
    
    # Deduplication check: stage same file again
    rel_path2, sha2, size2 = storage.stage_file(b"test content", "test.csv")
    assert rel_path == rel_path2
    assert sha == sha2
    
    # Cleanup check
    # Manually modify mtime to simulate old file
    staged_file_stat = staged_file.stat()
    os.utime(staged_file, (staged_file_stat.st_atime, time.time() - 3600 * 25))
    
    deleted_count = storage.cleanup_staged_files(max_age_hours=24)
    assert deleted_count == 1
    assert not staged_file.exists()

def test_delete_file(tmp_path):
    storage = RawStorageManager(base_storage_dir=str(tmp_path / "raw"), staging_dir=str(tmp_path / "staged"))
    rel_path, sha, size = storage.stage_file(b"content to delete", "delete_me.csv")
    
    storage.delete_file(rel_path)
    
    full_path = storage.resolve_path(rel_path)
    assert not full_path.exists()
