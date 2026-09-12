"""
Policy Ingestion Script
Ingests policy markdown documents into the ChromaDB vector store.
"""

import os
import sys

# Add backend directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.rag.ingestion import PolicyDocumentIngester


def main():
    """Ingest accounting policies from data/policies."""
    policies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "policies"))
    print(f"Scanning policy directory: {policies_dir}")
    ingester = PolicyDocumentIngester()
    results = ingester.ingest_directory(policies_dir)
    total_chunks = sum(r.get("chunks_count", 0) for r in results)
    print(f"Successfully processed {len(results)} policy document(s) with {total_chunks} total chunk(s) stored in ChromaDB.")
    for r in results:
        print(f"  - [{r.get('policy_id', 'N/A')}] {r.get('title', 'Doc')} ({r.get('chunks_count', 0)} chunks)")


if __name__ == "__main__":
    main()
