"""
Deterministic regression tests for synthetic SOP corpus and policy metadata/listing.
Tests multi-chunk aggregation, distinct document counting, section policy identity,
and semantic retrieval across ACC-001 to ACC-006 without calling external LLMs.
"""

from pathlib import Path
import pytest

from app.rag.vectorstore import VectorStoreManager
from app.rag.ingestion import PolicyDocumentIngester
from app.rag.retriever import PolicyRetriever


@pytest.fixture
def isolated_rag():
    """Isolated ephemeral vectorstore, ingester, and retriever."""
    vsm = VectorStoreManager(is_ephemeral=True)
    coll_name = "test_sop_corpus"
    ingester = PolicyDocumentIngester(vectorstore_manager=vsm, collection_name=coll_name, chunk_size=200, chunk_overlap=30)
    retriever = PolicyRetriever(vectorstore_manager=vsm, collection_name=coll_name)
    yield vsm, ingester, retriever, coll_name
    vsm.delete_collection(coll_name)


def test_empty_collection_safe(isolated_rag):
    """Empty vector store returns 0 count and empty document list safely."""
    vsm, _, retriever, coll_name = isolated_rag
    assert vsm.count(coll_name) == 0
    docs = vsm.list_documents(coll_name)
    assert docs == []
    results = retriever.query_similar(query="reconciliation", top_k=3)
    assert results == []


def test_multiple_chunks_belonging_to_one_document(isolated_rag):
    """A long document split into multiple chunks must aggregate into 1 distinct document with chunk count > 1."""
    vsm, ingester, _, coll_name = isolated_rag
    long_text = (
        "# Single Long Policy\n\n"
        "## Policy ACC-001: General Operations\n\n"
        + "Paragraph detailing standard bank reconciliation and statement balancing rules in depth. " * 10
        + "\n\n## Section 2: Escalation Rules\n\n"
        + "Additional guidance on investigating variance thresholds and outstanding stale checks over time. " * 10
    )

    res = ingester.ingest_text(long_text, doc_id="doc_acc_001", filename="ACC-001.md")
    assert res["status"] == "INGESTED"
    assert res["chunks_count"] > 1

    docs = vsm.list_documents(coll_name)
    assert len(docs) == 1, "Must aggregate to exactly 1 document"
    assert docs[0]["doc_id"] == "doc_acc_001"
    assert docs[0]["chunks_count"] == res["chunks_count"]
    assert docs[0]["policy_id"] == "ACC-001"


def test_multiple_distinct_policy_documents(isolated_rag):
    """Multiple distinct documents must be listed with their respective policy IDs and chunk counts."""
    vsm, ingester, _, coll_name = isolated_rag

    policies = [
        ("doc_1", "# Policy ACC-001: Bank Recon\n\nBank statement balancing."),
        ("doc_2", "# Policy ACC-002: Accrual Policy\n\nExpense recognition rules."),
        ("doc_3", "# Policy ACC-003: Asset Depreciation\n\nStraight line depreciation."),
    ]
    for doc_id, text in policies:
        ingester.ingest_text(text, doc_id=doc_id, filename=f"{doc_id}.md")

    docs = vsm.list_documents(coll_name)
    assert len(docs) == 3
    policy_ids = {d["policy_id"] for d in docs}
    assert policy_ids == {"ACC-001", "ACC-002", "ACC-003"}


def test_acc002_content_never_labelled_acc001(isolated_rag):
    """ACC-002 accrual content must retain ACC-002 policy ID and never inherit ACC-001."""
    _, ingester, retriever, _ = isolated_rag

    mixed_text = (
        "# Multi-Policy Document\n\n"
        "## Policy ACC-001: Bank Reconciliation\n"
        "Cash accounts must be reconciled against bank statements every month.\n\n"
        "## Policy ACC-002: Accrual Recognition\n"
        "Operating expenses incurred during the fiscal period must be accrued if uninvoiced."
    )

    ingester.ingest_text(mixed_text, doc_id="multi_policy", filename="policies.md")

    # Query for accruals
    accrual_results = retriever.query_similar(query="accrual uninvoiced operating expenses", top_k=2)
    assert len(accrual_results) > 0
    top_accrual = accrual_results[0]
    assert "ACC-002" in top_accrual["metadata"].get("policy_id", "")
    assert "ACC-001" not in top_accrual["metadata"].get("policy_id", "")
    assert "ACC-002" in top_accrual.get("citation", "")


def test_malformed_partial_response_safety(isolated_rag):
    """Documents with missing headers or empty metadata do not crash list_documents or retriever."""
    vsm, ingester, retriever, coll_name = isolated_rag

    ingester.ingest_text("Plain text with no headers and no policy tags.", doc_id="plain_doc", filename="plain.txt")
    docs = vsm.list_documents(coll_name)
    assert len(docs) == 1
    assert docs[0]["doc_id"] == "plain_doc"
    assert docs[0]["category"] == "GENERAL"

    retrieved = retriever.query_similar("plain search", top_k=1)
    assert len(retrieved) == 1
    assert "POL-GEN" in retrieved[0]["citation"] or "Accounting SOP" in retrieved[0]["citation"]


def test_all_six_synthetic_sop_documents_retrieval():
    """All 6 synthetic SOP documents in data/policies are ingested and retrieve appropriately."""
    vsm = VectorStoreManager(is_ephemeral=True)
    coll_name = "test_synthetic_sops"
    ingester = PolicyDocumentIngester(vectorstore_manager=vsm, collection_name=coll_name, chunk_size=500)
    retriever = PolicyRetriever(vectorstore_manager=vsm, collection_name=coll_name)

    policies_dir = Path(__file__).resolve().parents[3] / "data" / "policies"
    assert policies_dir.exists(), "data/policies directory must exist"

    results = ingester.ingest_directory(str(policies_dir))
    assert len(results) == 6, f"Expected 6 synthetic policies ingested, got {len(results)}"

    docs = vsm.list_documents(coll_name)
    assert len(docs) == 6, f"Expected 6 distinct indexed documents, got {len(docs)}"

    policy_ids = {d["policy_id"] for d in docs}
    expected_ids = {"ACC-001", "ACC-002", "ACC-003", "ACC-004", "ACC-005", "ACC-006"}
    assert policy_ids == expected_ids

    # Verify synthetic demo notice in all documents
    for file_path in policies_dir.glob("*.md"):
        content = file_path.read_text(encoding="utf-8")
        assert "Synthetic Demo Policy" in content, f"{file_path.name} must have synthetic notice"
        assert "Enquest internal policy" not in content or "not" in content.lower(), (
            f"{file_path.name} must not claim to be an internal Enquest policy"
        )

    # 1. Reconciliation query -> ACC-001
    r_recon = retriever.query_similar("bank reconciliation variance stale check", top_k=1)
    assert len(r_recon) > 0
    assert r_recon[0]["metadata"]["policy_id"] == "ACC-001"

    # 2. Accrual query -> ACC-002
    r_accrual = retriever.query_similar("accrual unbilled goods received historical baseline", top_k=1)
    assert len(r_accrual) > 0
    assert r_accrual[0]["metadata"]["policy_id"] == "ACC-002"

    # 3. Depreciation query -> ACC-003
    r_deprec = retriever.query_similar("fixed asset capitalization straight line useful life", top_k=1)
    assert len(r_deprec) > 0
    assert r_deprec[0]["metadata"]["policy_id"] == "ACC-003"

    # 4. Accounts Payable query -> ACC-004
    r_ap = retriever.query_similar("accounts payable three-way match purchase order duplicate invoice", top_k=1)
    assert len(r_ap) > 0
    assert r_ap[0]["metadata"]["policy_id"] == "ACC-004"

    # 5. Materiality query -> ACC-005
    r_mat = retriever.query_similar("materiality exception escalation threshold critical severity SLA", top_k=1)
    assert len(r_mat) > 0
    assert r_mat[0]["metadata"]["policy_id"] == "ACC-005"

    # 6. HITL / approval controls query -> ACC-006
    r_hitl = retriever.query_similar("human approval segregation of duties dual authorization journal adjustment", top_k=1)
    assert len(r_hitl) > 0
    assert r_hitl[0]["metadata"]["policy_id"] == "ACC-006"

    vsm.delete_collection(coll_name)
