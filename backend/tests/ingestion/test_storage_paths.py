"""
Tests for RawStorageManager Windows path reliability, containment validation,
cross-drive behavior, traversal defense, and stored-file replay.
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from app.ingestion.storage import RawStorageManager


def test_normal_stored_file_replay_after_source_removal(tmp_path):
    """Stored file must remain readable/replayable even after the original source file is deleted."""
    storage_root = tmp_path / "storage"
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    source_file = source_dir / "statement.csv"
    content = b"date,amount,reference\n2025-12-01,1000,REF1\n"
    source_file.write_bytes(content)

    manager = RawStorageManager(base_storage_dir=str(storage_root))
    rel_path, sha256, byte_size = manager.store_file(
        file_bytes=content,
        filename="statement.csv",
        batch_id="batch-001",
    )

    # Delete original source file
    source_file.unlink()
    assert not source_file.exists()

    # Verify stored file is accessible via read_file and resolve_path
    resolved = manager.resolve_path(rel_path)
    assert resolved.exists()
    assert resolved.read_bytes() == content
    assert manager.read_file(rel_path) == content
    assert sha256 == manager.calculate_sha256(content)
    assert byte_size == len(content)


def test_windows_cross_drive_path_storage_and_read(tmp_path):
    """When os.path.relpath raises ValueError (cross-drive on Windows), storage uses safe absolute path within root."""
    storage_root = tmp_path / "storage"
    manager = RawStorageManager(base_storage_dir=str(storage_root))
    content = b"booking_date,amount\n2025-12-10,500\n"

    # Simulate cross-drive ValueError from os.path.relpath(target_path)
    def fake_relpath(path, start=None):
        if start is None:
            raise ValueError("path is on mount 'C:', start on mount 'D:'")
        return Path(path).name

    with patch("app.ingestion.storage.os.path.relpath", side_effect=fake_relpath):
        rel_path, sha256, byte_size = manager.store_file(
            file_bytes=content,
            filename="cross_drive.csv",
            batch_id="batch-cross-001",
        )

    # In cross-drive scenario, rel_path must be directly openable via Path(rel_path)
    assert Path(rel_path).is_file(), f"Path({rel_path}) must exist directly"
    assert Path(rel_path).read_bytes() == content
    # And manager.read_file and manager.resolve_path must resolve it correctly
    assert manager.read_file(rel_path) == content
    resolved = manager.resolve_path(rel_path)
    assert resolved.is_relative_to(storage_root.resolve())


def test_path_traversal_attempts_rejected(tmp_path):
    """Path traversal sequences (../, escaping root) must be rejected with ValueError."""
    storage_root = tmp_path / "storage"
    manager = RawStorageManager(base_storage_dir=str(storage_root))

    # Test store_file invalid components
    with pytest.raises(ValueError, match="Invalid storage path component"):
        manager.store_file(b"data", "../escaped.csv", "batch-1")

    with pytest.raises(ValueError, match="Invalid storage path component"):
        manager.store_file(b"data", "file.csv", "../batch-1")

    # Test read_file / resolve_path traversal attempts
    with pytest.raises(ValueError, match="Storage path escapes root"):
        manager.resolve_path("../outside.txt")

    with pytest.raises(ValueError, match="Storage path escapes root"):
        manager.resolve_path("batch/../../etc/passwd")

    with pytest.raises(ValueError, match="Storage path escapes root"):
        manager.read_file("../outside.txt")


def test_absolute_path_outside_storage_root_rejected(tmp_path):
    """Absolute paths pointing outside the configured storage root must be rejected."""
    storage_root = tmp_path / "storage"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_bytes(b"confidential")

    manager = RawStorageManager(base_storage_dir=str(storage_root))

    with pytest.raises(ValueError, match="Storage path escapes root"):
        manager.resolve_path(str(outside_file.resolve()))

    with pytest.raises(ValueError, match="Storage path escapes root"):
        manager.read_file(str(outside_file.resolve()))


def test_legacy_safe_reference_relative_to_root(tmp_path):
    """Legacy relative references stored relative to the storage root (e.g. 'batch_id/file.csv') must be supported."""
    storage_root = tmp_path / "storage"
    batch_dir = storage_root / "legacy-batch"
    batch_dir.mkdir(parents=True)
    legacy_file = batch_dir / "legacy.csv"
    legacy_file.write_bytes(b"legacy content")

    manager = RawStorageManager(base_storage_dir=str(storage_root))
    # Legacy reference format: 'legacy-batch/legacy.csv'
    legacy_ref = "legacy-batch/legacy.csv"

    resolved = manager.resolve_path(legacy_ref)
    assert resolved == legacy_file.resolve()
    assert manager.read_file(legacy_ref) == b"legacy content"
