"""
RAG and Vector Store Structural Tests
"""

import asyncio
from app.rag.vectorstore import VectorStoreManager
from app.rag.ingestion import PolicyDocumentIngester
from app.rag.retriever import PolicyRetriever


def test_vectorstore_manager_init():
    manager = VectorStoreManager(persist_directory="./test_chroma")
    assert manager.persist_directory == "./test_chroma"
    collection = manager.get_collection()
    assert collection is None


def test_document_ingester():
    ingester = PolicyDocumentIngester()
    result = ingester.ingest_file("sample_policy.txt")
    assert result["status"] == "placeholder_ingested"


def test_policy_retriever():
    retriever = PolicyRetriever()
    results = asyncio.run(retriever.retrieve_policy_context("revenue recognition"))
    assert isinstance(results, list)
