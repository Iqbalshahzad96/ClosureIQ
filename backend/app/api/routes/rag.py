"""
RAG and Policy Ingestion API Routes
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.config import settings
from app.rag.vectorstore import VectorStoreManager
from app.rag.ingestion import PolicyDocumentIngester
from app.rag.retriever import PolicyRetriever

router = APIRouter(prefix="/rag", tags=["RAG & Policies"])

# Shared RAG manager instances
_vectorstore_manager = VectorStoreManager()
_ingester = PolicyDocumentIngester(vectorstore_manager=_vectorstore_manager)
_retriever = PolicyRetriever(vectorstore_manager=_vectorstore_manager)


def get_vectorstore_manager() -> VectorStoreManager:
    return _vectorstore_manager


def get_ingester(
    vectorstore_manager: VectorStoreManager = Depends(get_vectorstore_manager),
) -> PolicyDocumentIngester:
    if vectorstore_manager is _vectorstore_manager:
        return _ingester
    return PolicyDocumentIngester(vectorstore_manager=vectorstore_manager)


def get_retriever(
    vectorstore_manager: VectorStoreManager = Depends(get_vectorstore_manager),
) -> PolicyRetriever:
    if vectorstore_manager is _vectorstore_manager:
        return _retriever
    return PolicyRetriever(vectorstore_manager=vectorstore_manager)


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


class ChatHistoryMessage(BaseModel):
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")


class RAGAnswerRequest(BaseModel):
    question: str = Field(..., description="User's policy question")
    history: List[ChatHistoryMessage] = Field(default_factory=list)
    top_k: int = Field(default=2, ge=1, le=10)
    category: Optional[str] = Field(default=None)


class RAGAnswerResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]]
    retrieved_count: int
    model: str


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
async def query_policies(
    payload: RAGQueryRequest,
    retriever: PolicyRetriever = Depends(get_retriever),
) -> RAGQueryResponse:
    """Retrieve relevant accounting policy context for a query."""
    results = await retriever.retrieve_policy_context(
        query=payload.query,
        top_k=payload.top_k,
        category=payload.category,
    )
    formatted = retriever.format_context_for_prompt(results)
    return RAGQueryResponse(
        query=payload.query,
        count=len(results),
        results=results,
        formatted_context=formatted,
    )


@router.post("/answer", response_model=RAGAnswerResponse)
async def answer_policy_question(
    payload: RAGAnswerRequest,
    retriever: PolicyRetriever = Depends(get_retriever),
) -> RAGAnswerResponse:
    """Generate a chatbot-style answer grounded in retrieved policy documents."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    evidence = await retriever.retrieve_policy_context(
        query=question,
        top_k=payload.top_k,
        category=payload.category,
    )
    if not evidence:
        return RAGAnswerResponse(
            answer="I could not find relevant policy content in ChromaDB for that question.",
            citations=[],
            retrieved_count=0,
            model=settings.GEMINI_MODEL,
        )

    from app.rag.llm import generate_gemini_content, format_chat_history

    history_lines_str = format_chat_history(payload.history[-4:])

    context = retriever.format_context_for_prompt(evidence)
    system_instruction = (
        "You are a Policy & SOP assistant for ClosureIQ. Answer the user's question "
        "using only the supplied policy evidence and conversation history. If the "
        "evidence does not answer the question, say that clearly. Keep the answer "
        "concise and cite policy IDs or section names from the evidence."
    )
    user_content = (
        "Conversation history:\n"
        f"{history_lines_str}\n\n"
        "Policy evidence:\n"
        f"{context}\n\n"
        "User question:\n"
        f"{question}"
    )

    try:
        answer = await generate_gemini_content(
            system_instruction=system_instruction,
            user_content=user_content,
        )
        answer = answer.strip()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini model is unavailable because its API key is not configured.",
        ) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini model is unavailable because the google-genai SDK is missing.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gemini model generation failed.",
        ) from exc

    return RAGAnswerResponse(
        answer=answer or "No answer was generated.",
        citations=[
            {
                "citation": item.get("citation"),
                "policy_id": item.get("policy_id"),
                "policy_name": item.get("policy_name"),
                "category": item.get("category"),
            }
            for item in evidence
        ],
        retrieved_count=len(evidence),
        model=settings.GEMINI_MODEL,
    )


@router.post("/ingest/text")
async def ingest_policy_text(
    payload: IngestTextRequest,
    ingester: PolicyDocumentIngester = Depends(get_ingester),
) -> Dict[str, Any]:
    """Ingest a policy document from raw text/markdown with zero-duplicate guarantee."""
    res = ingester.ingest_text(
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


@router.post("/ingest/file")
@router.post("/upload")
async def upload_policy_file(
    file: UploadFile = File(...),
    category: Optional[str] = Form(default=None),
    policy_id: Optional[str] = Form(default=None),
    doc_id: Optional[str] = Form(default=None),
    ingester: PolicyDocumentIngester = Depends(get_ingester),
) -> Dict[str, Any]:
    """Ingest an uploaded policy document (.md, .txt, .pdf, .docx) into ChromaDB."""
    filename = file.filename or "policy.md"
    content_bytes = await file.read()
    if not content_bytes or len(content_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded policy file is empty.")

    ext = os.path.splitext(filename)[1].lower()
    resolved_doc_id = doc_id or policy_id or os.path.splitext(filename)[0].lower().replace(" ", "_")
    meta_override: Dict[str, Any] = {}
    if category:
        meta_override["category"] = category
    if policy_id:
        meta_override["policy_id"] = policy_id

    if ext in {".md", ".txt", ".markdown", ".csv", ".json"}:
        text = content_bytes.decode("utf-8", errors="replace")
    elif ext in {".pdf", ".docx", ".doc"}:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content_bytes)
            tmp_path = tmp.name
        try:
            text = ingester.extract_text_from_file(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    else:
        text = content_bytes.decode("utf-8", errors="replace")

    res = ingester.ingest_text(
        text=text,
        doc_id=resolved_doc_id,
        filename=filename,
        metadata_override=meta_override,
    )
    if res.get("status") == "FAILED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("message", "Policy ingestion failed."),
        )
    return res


@router.post("/ingest/directory")
async def ingest_policy_directory(
    payload: Optional[IngestDirectoryRequest] = None,
    ingester: PolicyDocumentIngester = Depends(get_ingester),
    vectorstore_manager: VectorStoreManager = Depends(get_vectorstore_manager),
) -> Dict[str, Any]:
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

    results = ingester.ingest_directory(dir_path)
    return {
        "directory_path": dir_path,
        "ingested_files_count": len(results),
        "total_chunks_in_store": vectorstore_manager.count(),
        "results": results,
    }


@router.get("/documents")
async def list_documents(
    vectorstore_manager: VectorStoreManager = Depends(get_vectorstore_manager),
) -> Dict[str, Any]:
    """List all ingested policy documents and total chunks in ChromaDB."""
    docs = vectorstore_manager.list_documents()
    total_chunks = vectorstore_manager.count()
    return {
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "documents": docs,
    }


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    ingester: PolicyDocumentIngester = Depends(get_ingester),
) -> Dict[str, Any]:
    """Delete a policy document and its chunks from ChromaDB."""
    deleted_count = ingester.delete_document(doc_id)
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

