"""
Comprehensive RAG and Policy Ingestion Test Suite

Tests ChromaDB VectorStoreManager, PolicyDocumentIngester, PolicyRetriever,
metadata extraction, deduplicated re-ingestion, and FastAPI endpoints.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag.vectorstore import VectorStoreManager
from app.rag.ingestion import PolicyDocumentIngester
from app.rag.retriever import PolicyRetriever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_collection_name():
    """Generate a unique test collection name for full test isolation."""
    return f"test_policies_{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def ephemeral_vectorstore():
    """Create a clean in-memory ChromaDB vector store manager."""
    return VectorStoreManager(is_ephemeral=True)


@pytest.fixture()
def ingester(ephemeral_vectorstore, test_collection_name):
    """Return an ingester bound to an isolated test collection."""
    inst = PolicyDocumentIngester(
        vectorstore_manager=ephemeral_vectorstore,
        chunk_size=300,
        chunk_overlap=40,
        collection_name=test_collection_name,
    )
    yield inst
    ephemeral_vectorstore.delete_collection(test_collection_name)


@pytest.fixture()
def retriever(ephemeral_vectorstore, test_collection_name):
    """Return a retriever bound to the same isolated test collection."""
    return PolicyRetriever(
        vectorstore_manager=ephemeral_vectorstore,
        collection_name=test_collection_name,
    )


@pytest.fixture()
def sample_policy_text():
    """Sample accounting policy markdown text with headers and rules."""
    return """# Corporate Accounting SOPs

## Policy ACC-001: Bank Reconciliation Standard
1. All general ledger cash accounts must be reconciled against official bank statements monthly.
2. Unmatched items exceeding $50.00 must be flagged for manual investigation by the accounting team.
3. Timing differences over 30 days must be evaluated for stale checks.

## Policy ACC-002: Accrual & Expense Matching
1. Expenses incurred during the accounting period must be accrued if uninvoiced by period end.
2. Material variances exceeding 10% against prior 3-month baseline require explanatory variance notes.
"""


# ---------------------------------------------------------------------------
# 1. VectorStoreManager Tests
# ---------------------------------------------------------------------------

def test_vectorstore_manager_ephemeral_init(ephemeral_vectorstore, test_collection_name):
    """Verify ephemeral client initialization and collection creation."""
    assert ephemeral_vectorstore.is_ephemeral is True
    col = ephemeral_vectorstore.get_or_create_collection(test_collection_name)
    assert col is not None
    assert ephemeral_vectorstore.count(test_collection_name) == 0


def test_vectorstore_manager_count_and_delete(ephemeral_vectorstore, test_collection_name):
    """Verify item addition, count, and collection deletion."""
    col = ephemeral_vectorstore.get_or_create_collection(test_collection_name)
    col.add(ids=["chk_1", "chk_2"], documents=["Text A", "Text B"], metadatas=[{"doc_id": "doc1"}, {"doc_id": "doc1"}])
    assert ephemeral_vectorstore.count(test_collection_name) == 2

    # Delete by doc_id
    deleted = ephemeral_vectorstore.delete_by_doc_id("doc1", test_collection_name)
    assert deleted == 2
    assert ephemeral_vectorstore.count(test_collection_name) == 0

    # Delete collection
    assert ephemeral_vectorstore.delete_collection(test_collection_name) is True


# ---------------------------------------------------------------------------
# 2. PolicyDocumentIngester Tests
# ---------------------------------------------------------------------------

def test_ingest_text_metadata_and_chunks(ingester, test_collection_name, sample_policy_text):
    """Verify metadata extraction, chunking, and ChromaDB insertion."""
    result = ingester.ingest_text(
        text=sample_policy_text,
        doc_id="sop_standard_v1",
        filename="accounting_sop.md",
    )

    assert result["status"] == "INGESTED"
    assert result["doc_id"] == "sop_standard_v1"
    assert result["title"] == "Corporate Accounting SOPs"
    assert result["policy_id"] == "ACC-001"
    assert result["chunks_count"] >= 2

    # Verify stored chunks count in vector store
    assert ingester.vectorstore_manager.count(test_collection_name) == result["chunks_count"]


def test_reingestion_zero_duplicates(ingester, test_collection_name, sample_policy_text):
    """Re-ingesting the same doc_id must replace existing chunks without duplication."""
    # First ingestion
    res1 = ingester.ingest_text(sample_policy_text, doc_id="reingest_doc")
    first_count = res1["chunks_count"]
    assert ingester.vectorstore_manager.count(test_collection_name) == first_count

    # Second ingestion with the same doc_id
    res2 = ingester.ingest_text(sample_policy_text, doc_id="reingest_doc")
    second_count = res2["chunks_count"]

    # Total stored chunks MUST equal second_count, not first_count + second_count
    assert ingester.vectorstore_manager.count(test_collection_name) == second_count
    assert second_count == first_count


def test_ingest_file_and_directory(ingester, sample_policy_text):
    """Test file extraction and directory batch ingestion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file1 = os.path.join(tmpdir, "policy_acc.md")
        with open(file1, "w", encoding="utf-8") as f:
            f.write(sample_policy_text)

        file2 = os.path.join(tmpdir, "policy_dep.txt")
        with open(file2, "w", encoding="utf-8") as f:
            f.write("# Depreciation Policy\nStraight-line method over 36 months.")

        batch_results = ingester.ingest_directory(tmpdir)
        assert len(batch_results) == 2
        assert all(r["status"] == "INGESTED" for r in batch_results)


def test_delete_document(ingester, test_collection_name, sample_policy_text):
    """Test deleting an ingested document by doc_id."""
    ingester.ingest_text(sample_policy_text, doc_id="to_delete")
    assert ingester.vectorstore_manager.count(test_collection_name) > 0

    deleted = ingester.delete_document("to_delete")
    assert deleted > 0
    assert ingester.vectorstore_manager.count(test_collection_name) == 0


def test_list_documents(ingester, test_collection_name, sample_policy_text):
    """Verify list_documents aggregates metadata correctly."""
    ingester.ingest_text(sample_policy_text, doc_id="doc_list_test", filename="test.md")
    docs = ingester.vectorstore_manager.list_documents(test_collection_name)

    assert len(docs) == 1
    assert docs[0]["doc_id"] == "doc_list_test"
    assert docs[0]["filename"] == "test.md"
    assert docs[0]["chunks_count"] > 0


# ---------------------------------------------------------------------------
# 3. PolicyRetriever Tests
# ---------------------------------------------------------------------------

def test_semantic_retrieval(ingester, retriever, sample_policy_text):
    """Verify semantic top-k similarity search returns relevant excerpts and citations."""
    ingester.ingest_text(sample_policy_text, doc_id="retrieval_doc")

    # Query for bank reconciliation threshold
    results = retriever.query_similar(query="What is the bank reconciliation threshold?", top_k=2)

    assert len(results) > 0
    top_hit = results[0]
    assert "content" in top_hit
    assert "citation" in top_hit
    assert "distance" in top_hit
    assert "ACC-001" in top_hit["citation"] or "Bank Reconciliation" in top_hit["content"]


@pytest.mark.asyncio
async def test_async_policy_retrieval_and_formatting(ingester, retriever, sample_policy_text):
    """Verify async retrieve_policy_context and format_context_for_prompt."""
    ingester.ingest_text(sample_policy_text, doc_id="async_doc")

    results = await retriever.retrieve_policy_context(query="accrual material variance percentage", top_k=1)
    assert len(results) == 1

    formatted = retriever.format_context_for_prompt(results)
    assert "### Evidence 1:" in formatted
    assert "10%" in formatted or "Accrual" in formatted


def test_retrieval_empty_query_or_empty_store(retriever):
    """Empty query or unpopulated collection returns empty list gracefully."""
    assert retriever.query_similar("") == []
    assert retriever.query_similar("sample query") == []


# ---------------------------------------------------------------------------
# 4. FastAPI RAG Route Tests
# ---------------------------------------------------------------------------

def test_api_rag_ingest_and_query_endpoints():
    """Test /api/v1/rag endpoints via FastAPI TestClient."""
    client = TestClient(app)

    # 1. Ingest policy text
    ingest_resp = client.post(
        "/api/v1/rag/ingest/text",
        json={
            "doc_id": "api_test_sop",
            "text": "# Fixed Asset Policy\n## Policy ACC-003: Depreciation\nAll fixed assets above $1,000 must follow straight-line depreciation.",
            "filename": "api_test.md",
        },
    )
    assert ingest_resp.status_code == 200
    ingest_data = ingest_resp.json()
    assert ingest_data["doc_id"] == "api_test_sop"
    assert ingest_data["status"] == "INGESTED"

    # 2. List documents
    list_resp = client.get("/api/v1/rag/documents")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_documents"] >= 1

    # 3. Query policy
    query_resp = client.post(
        "/api/v1/rag/query",
        json={"query": "fixed assets straight line depreciation", "top_k": 2},
    )
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    assert query_data["count"] >= 1
    assert "formatted_context" in query_data

    # 4. Delete document
    del_resp = client.delete("/api/v1/rag/documents/api_test_sop")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "DELETED"
