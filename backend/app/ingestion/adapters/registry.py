"""
Adapter Registry for source-specific and generic financial adapters.
"""

from typing import Dict, List, Optional

from app.ingestion.adapters.enquest_ledger import EnquestLedgerAdapter
from app.ingestion.adapters.enquest_tb import EnquestTBAdapter
from app.ingestion.adapters.generic_ap_invoice import GenericAPInvoiceAdapter
from app.ingestion.adapters.generic_bank import GenericBankStatementAdapter
from app.ingestion.adapters.generic_fixed_asset import GenericFixedAssetAdapter
from app.ingestion.base import BaseAdapter


class AdapterRegistry:
    """Registry managing available adapters and resolving matching adapter for files."""

    def __init__(self):
        self._adapters: Dict[str, BaseAdapter] = {}
        self._ordered_adapters: List[BaseAdapter] = []

        # Register default built-in adapters
        self.register(EnquestLedgerAdapter())
        self.register(EnquestTBAdapter())
        self.register(GenericBankStatementAdapter())
        self.register(GenericAPInvoiceAdapter())
        self.register(GenericFixedAssetAdapter())

    def register(self, adapter: BaseAdapter) -> None:
        """Register a new adapter instance."""
        key = adapter.get_adapter_key()
        self._adapters[key] = adapter
        self._ordered_adapters = [a for a in self._ordered_adapters if a.get_adapter_key() != key]
        self._ordered_adapters.append(adapter)

    def get_by_key(self, adapter_key: str) -> Optional[BaseAdapter]:
        """Retrieve adapter directly by key."""
        return self._adapters.get(adapter_key)

    def resolve_adapter(
        self,
        file_bytes: bytes,
        filename: str,
        explicit_adapter_key: Optional[str] = None,
    ) -> Optional[BaseAdapter]:
        """
        Determine and return the appropriate adapter.
        If explicit_adapter_key is provided, attempts to use it first.
        """
        if explicit_adapter_key:
            return self._adapters.get(explicit_adapter_key)

        for adapter in self._ordered_adapters:
            if adapter.can_handle(file_bytes, filename):
                return adapter

        return None


# Global registry instance
default_adapter_registry = AdapterRegistry()
