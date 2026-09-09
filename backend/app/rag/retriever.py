"""
Policy Retriever for Grounding AI Agent Reasoning

Performs top-k semantic similarity search against the ChromaDB policy store
and formats structured context evidence with verified citations for Agent 2.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.rag.vectorstore import VectorStoreManager


class PolicyRetriever:
    """Retrieves relevant accounting policy evidence given an audit query, anomaly, or rule check."""

    def __init__(
        self,
        vectorstore_manager: Optional[VectorStoreManager] = None,
        collection_name: str = "accounting_policies",
    ) -> None:
        self.vectorstore_manager = vectorstore_manager or VectorStoreManager()
        self.collection_name = collection_name

    def query_similar(
        self,
        query: str,
        top_k: int = 3,
        where_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Synchronously query the ChromaDB collection for the top-k most similar policy chunks.

        Parameters
        ----------
        query : str
            The question, audit exception description, or keyword query.
        top_k : int, default 3
            Number of top matching chunks to retrieve.
        where_filter : dict, optional
            Chroma metadata filter (e.g. {"category": "ACCRUAL"}).

        Returns
        -------
        list of dict
            Retrieved chunks containing text, metadata, distance score, and formatted citation.
        """
        if not query or not query.strip():
            return []

        collection = self.vectorstore_manager.get_or_create_collection(self.collection_name)
        count = collection.count()
        if count == 0:
            return []

        actual_k = min(max(1, int(top_k)), count)

        query_kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": actual_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            query_kwargs["where"] = where_filter

        try:
            results = collection.query(**query_kwargs)
        except Exception:
            return []

        retrieved: List[Dict[str, Any]] = []

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0] if "distances" in results else [0.0] * len(ids)

        for i, doc_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            text = documents[i] if i < len(documents) else ""
            dist = distances[i] if i < len(distances) else 0.0

            # Construct clear audit citation
            policy_id = meta.get("policy_id") or "POL-GEN"
            title = meta.get("title") or meta.get("filename") or "Accounting SOP"
            section = meta.get("section") or "General"
            citation = f"[{policy_id}] {title} — Section: {section}"

            retrieved.append({
                "chunk_id": doc_id,
                "content": text,
                "metadata": meta,
                "distance": round(float(dist), 4) if dist is not None else 0.0,
                "citation": citation,
            })

        return retrieved

    async def retrieve_policy_context(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Asynchronously retrieve relevant policy excerpts to ground agent reasoning."""
        where_filter = {"category": category} if category else None
        return self.query_similar(query=query, top_k=top_k, where_filter=where_filter)

    @staticmethod
    def format_context_for_prompt(retrieved_items: List[Dict[str, Any]]) -> str:
        """Format retrieved items into a clean markdown block ready for LLM prompt context."""
        if not retrieved_items:
            return "No relevant accounting policies found in knowledge base."

        formatted_blocks = []
        for i, item in enumerate(retrieved_items, start=1):
            citation = item.get("citation", f"Reference {i}")
            content = item.get("content", "").strip()
            formatted_blocks.append(f"### Evidence {i}: {citation}\n{content}")

        return "\n\n".join(formatted_blocks)
