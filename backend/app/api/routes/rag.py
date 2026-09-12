"""
RAG and Policy Ingestion API Routes
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.rag.vectorstore import VectorStoreManager
from app.rag.ingestion import PolicyDocumentIngester
from app.rag.retriever import PolicyRetriever

router = APIRouter(prefix="/rag", tags=["RAG & Policies"])

# Shared RAG manager instances
_vectorstore_manager = VectorStoreManager()
_ingester = PolicyDocumentIngester(vectorstore_manager=_vectorstore_manager)
_retriever = PolicyRetriever(vectorstore_manager=_vectorstore_manager)


# ---------------------------------------------------------------------------
# Pydantic Request & Response Schemas
# ---------------------------------------------------------------------------

class RAGQueryRequest(BaseModel):
    query: str = Field(..., description="Semantic search query or exception description")
    top_k: int = Field(default=3, ge=1, le=20, description="Number of results to retrieve")
    category: Optional[str] = Field(default=None, description="Filter by category (e.g. ACCRUAL, BANK_RECONCILIATION)")


class RAGQueryResponse(BaseModel):
    query: str
    count: int
    results: List[Dict[str, Any]]
    formatted_context: str


class IngestTextRequest(BaseModel):
    doc_id: str = Field(..., description="Unique document identifier")
    text: str = Field(..., description="Policy document text or markdown")
    filename: Optional[str] = Field(default=None, description="Optional filename")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")


class IngestDirectoryRequest(BaseModel):
    directory_path: Optional[str] = Field(
        default=None,
        description="Path to policy directory on server. Defaults to data/policies.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/query", response_model=RAGQueryResponse)
async def query_policies(payload: RAGQueryRequest) -> RAGQueryResponse:
    """Retrieve relevant accounting policy context for a query."""
    results = await _retriever.retrieve_policy_context(
        query=payload.query,
        top_k=payload.top_k,
        category=payload.category,
    )
    formatted = _retriever.format_context_for_prompt(results)
    return RAGQueryResponse(
        query=payload.query,
        count=len(results),
        results=results,
        formatted_context=formatted,
    )


@router.post("/ingest/text")
async def ingest_policy_text(payload: IngestTextRequest) -> Dict[str, Any]:
    """Ingest a policy document from raw text/markdown with zero-duplicate guarantee."""
    res = _ingester.ingest_text(
        text=payload.text,
        doc_id=payload.doc_id,
        filename=payload.filename or f"{payload.doc_id}.md",
        metadata_override=payload.metadata,
    )
    if res.get("status") == "FAILED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("message", "Ingestion failed."),
        )
    return res


@router.post("/ingest/directory")
async def ingest_policy_directory(payload: Optional[IngestDirectoryRequest] = None) -> Dict[str, Any]:
    """Ingest all policy files from the server's policy directory."""
    dir_path = payload.directory_path if payload and payload.directory_path else None
    if not dir_path:
        # Default to repository root data/policies
        candidate_paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "policies")),
            os.path.abspath("data/policies"),
            os.path.abspath("../data/policies"),
        ]
        for cp in candidate_paths:
            if os.path.exists(cp) and os.path.isdir(cp):
                dir_path = cp
                break

    if not dir_path or not os.path.exists(dir_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy directory not found: {dir_path}",
        )

    results = _ingester.ingest_directory(dir_path)
    return {
        "directory_path": dir_path,
        "ingested_files_count": len(results),
        "total_chunks_in_store": _vectorstore_manager.count(),
        "results": results,
    }


@router.get("/documents")
async def list_documents() -> Dict[str, Any]:
    """List all ingested policy documents and total chunks in ChromaDB."""
    docs = _vectorstore_manager.list_documents()
    total_chunks = _vectorstore_manager.count()
    return {
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "documents": docs,
    }


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str) -> Dict[str, Any]:
    """Delete a policy document and its chunks from ChromaDB."""
    deleted_count = _ingester.delete_document(doc_id)
    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in vector store.",
        )
    return {
        "doc_id": doc_id,
        "deleted_chunks": deleted_count,
        "status": "DELETED",
    }
