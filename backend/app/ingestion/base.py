"""
Base interfaces, enums, and data containers for the Ingestion Pipeline and Adapters.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional


class RowRole(str, Enum):
    """Classification of worksheet or file row roles."""
    TITLE = "TITLE"
    HEADER = "HEADER"
    OPENING_BALANCE = "OPENING_BALANCE"
    TRANSACTION = "TRANSACTION"
    SUBTOTAL = "SUBTOTAL"
    TOTAL = "TOTAL"
    FOOTER = "FOOTER"
    UNKNOWN = "UNKNOWN"


class ValidationSeverity(str, Enum):
    """Severity classification for validation issues."""
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass
class ValidationIssue:
    """Individual validation failure or warning."""
    code: str
    message: str
    field: Optional[str] = None
    severity: ValidationSeverity = ValidationSeverity.ERROR
    row_number: Optional[int] = None
    sheet_name: Optional[str] = None


@dataclass
class RawSourceRow:
    """Represents a parsed raw row before canonical transformation."""
    row_number: int
    sheet_name: str
    raw_values: Dict[str, Any]
    role: RowRole = RowRole.TRANSACTION
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalRecordPayload:
    """Represents an adapter-mapped record ready for validation and canonical loading."""
    entity_type: str  # "JOURNAL_ENTRY", "BANK_TRANSACTION", "AP_INVOICE", "FIXED_ASSET", "TRIAL_BALANCE"
    data: Dict[str, Any]
    source_row_number: Optional[int] = None
    sheet_name: Optional[str] = None
    source_file_id: Optional[str] = None
    import_batch_id: Optional[str] = None
    raw_lineage: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Outcome of validating and standardizing a record payload."""
    is_valid: bool
    payload: Optional[CanonicalRecordPayload] = None
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]


@dataclass
class BatchIngestionSummary:
    """Summary metrics of an ingestion run."""
    batch_id: str
    source_system_id: str
    files_processed: int = 0
    total_rows: int = 0
    valid_rows: int = 0
    quarantined_rows: int = 0
    warning_rows: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "PROCESSING"
    source_file_id: Optional[str] = None
    duplicate_files: int = 0
    technical_duplicate_rows: int = 0
    business_duplicate_rows: int = 0
    skipped_rows: int = 0


class BaseAdapter(ABC):
    """Abstract base class for source-specific financial file adapters."""

    @abstractmethod
    def get_adapter_key(self) -> str:
        """Return unique key identifying this adapter (e.g., 'enquest_ledger')."""
        pass

    @abstractmethod
    def can_handle(self, file_bytes: bytes, filename: str) -> bool:
        """Determine if this adapter can parse the provided file content and name."""
        pass

    @abstractmethod
    def parse_file(
        self, file_bytes: bytes, filename: str, options: Optional[Dict[str, Any]] = None
    ) -> Generator[RawSourceRow, None, None]:
        """Stream raw rows from source file with role classification."""
        pass

    @abstractmethod
    def map_to_canonical(
        self, raw_rows: List[RawSourceRow], options: Optional[Dict[str, Any]] = None
    ) -> List[CanonicalRecordPayload]:
        """Transform classified raw rows into generic canonical record payloads."""
        pass
