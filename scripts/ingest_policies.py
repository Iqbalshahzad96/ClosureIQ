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
    print(f"Ingested {len(results)} policy documents (placeholder ready for Milestone 1).")


if __name__ == "__main__":
    main()
