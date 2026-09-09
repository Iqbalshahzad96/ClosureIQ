"""
ChromaDB Vector Store Manager

Manages local persistent or ephemeral ChromaDB collections for accounting policies.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from app.config import settings


class VectorStoreManager:
    """Manages ChromaDB vector store connections, collections, and document operations."""

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        is_ephemeral: bool = False,
    ) -> None:
        """Initialize ChromaDB client.

        Parameters
        ----------
        persist_directory : str, optional
            Path to persistent directory on disk. Defaults to ``settings.CHROMA_PERSIST_DIRECTORY``.
        is_ephemeral : bool, default False
            If True, creates an in-memory ephemeral client (ideal for fast test isolation).
        """
        self.is_ephemeral = is_ephemeral
        if is_ephemeral or persist_directory == ":memory:":
            self.persist_directory = None
            self._client: ClientAPI = chromadb.EphemeralClient()
        else:
            self.persist_directory = persist_directory or settings.CHROMA_PERSIST_DIRECTORY
            os.makedirs(self.persist_directory, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_directory)

    @property
    def client(self) -> ClientAPI:
        """Return the underlying ChromaDB ClientAPI instance."""
        return self._client

    def get_or_create_collection(
        self,
        collection_name: str = "accounting_policies",
        embedding_function: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Collection:
        """Retrieve or create a ChromaDB collection.

        Parameters
        ----------
        collection_name : str, default "accounting_policies"
            Name of the collection.
        embedding_function : callable, optional
            Embedding function. If None, Chroma's default embedding function is used.
        metadata : dict, optional
            Optional metadata for collection (e.g. {"hnsw:space": "cosine"}).
        """
        coll_metadata = metadata or {"hnsw:space": "cosine"}
        if embedding_function is not None:
            return self._client.get_or_create_collection(
                name=collection_name,
                embedding_function=embedding_function,
                metadata=coll_metadata,
            )
        return self._client.get_or_create_collection(
            name=collection_name,
            metadata=coll_metadata,
        )

    def delete_collection(self, collection_name: str = "accounting_policies") -> bool:
        """Delete an entire collection by name."""
        try:
            self._client.delete_collection(name=collection_name)
            return True
        except Exception:
            return False

    def count(self, collection_name: str = "accounting_policies") -> int:
        """Return the total number of chunks stored in the collection."""
        try:
            col = self.get_or_create_collection(collection_name)
            return col.count()
        except Exception:
            return 0

    def delete_by_doc_id(
        self,
        doc_id: str,
        collection_name: str = "accounting_policies",
    ) -> int:
        """Delete all chunks belonging to a specific document ID.

        Guarantees idempotency when re-ingesting or updating policies.
        """
        try:
            col = self.get_or_create_collection(collection_name)
            existing = col.get(where={"doc_id": doc_id})
            ids_to_delete = existing.get("ids", []) if existing else []
            count_to_delete = len(ids_to_delete)
            if count_to_delete > 0:
                col.delete(where={"doc_id": doc_id})
            return count_to_delete
        except Exception:
            return 0

    def list_documents(
        self,
        collection_name: str = "accounting_policies",
    ) -> List[Dict[str, Any]]:
        """List distinct policy documents ingested in the collection with chunk counts."""
        try:
            col = self.get_or_create_collection(collection_name)
            all_records = col.get(include=["metadatas"])
            metadatas = all_records.get("metadatas", []) or []

            docs_map: Dict[str, Dict[str, Any]] = {}
            for meta in metadatas:
                if not meta:
                    continue
                doc_id = meta.get("doc_id", "unknown")
                if doc_id not in docs_map:
                    docs_map[doc_id] = {
                        "doc_id": doc_id,
                        "filename": meta.get("filename", "unknown"),
                        "title": meta.get("title", doc_id),
                        "policy_id": meta.get("policy_id", ""),
                        "category": meta.get("category", "GENERAL"),
                        "chunks_count": 0,
                        "last_ingested": meta.get("ingested_at", ""),
                    }
                docs_map[doc_id]["chunks_count"] += 1

            return list(docs_map.values())
        except Exception:
            return []

    def reset(self) -> None:
        """Reset the vector store client."""
        try:
            self._client.reset()
        except Exception:
            pass
