"""
Document Ingestion & Chunking for Accounting Policies and SOPs

Extracts text from Markdown, TXT, PDF, and DOCX files, splits them into semantic chunks
with rich policy metadata, and indexes them in ChromaDB with zero-duplicate re-ingestion.
"""

from __future__ import annotations

import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.rag.vectorstore import VectorStoreManager


class PolicyDocumentIngester:
    """Ingests, chunks, and indexes accounting SOPs and policies into ChromaDB."""

    def __init__(
        self,
        vectorstore_manager: Optional[VectorStoreManager] = None,
        chunk_size: int = 600,
        chunk_overlap: int = 80,
        collection_name: str = "accounting_policies",
    ) -> None:
        self.vectorstore_manager = vectorstore_manager or VectorStoreManager()
        self.chunk_size = max(100, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size // 2))
        self.collection_name = collection_name

    # ----------------------------------------------------------------------
    # Text Extraction Helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def extract_text_from_file(file_path: str) -> str:
        """Extract text from supported file formats (md, txt, pdf, docx)."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {file_path}")

        ext = path.suffix.lower()

        if ext in {".md", ".txt", ".markdown", ".csv", ".json"}:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        elif ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                text_pages = [page.extract_text() or "" for page in reader.pages]
                return "\n\n".join(text_pages)
            except ImportError:
                # Fallback to plain binary extraction or inform user
                with open(path, "rb") as f:
                    raw = f.read()
                    # Extract printable ascii text sequences as graceful fallback
                    printable = re.findall(rb"[\x20-\x7E\s]{4,}", raw)
                    return b"\n".join(printable).decode("utf-8", errors="replace")

        elif ext in {".docx", ".doc"}:
            try:
                import docx
                doc = docx.Document(str(path))
                return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            except ImportError:
                with open(path, "rb") as f:
                    raw = f.read()
                    printable = re.findall(rb"[\x20-\x7E\s]{4,}", raw)
                    return b"\n".join(printable).decode("utf-8", errors="replace")

        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

    # ----------------------------------------------------------------------
    # Metadata and Chunking Logic
    # ----------------------------------------------------------------------

    @staticmethod
    def _extract_policy_metadata(text: str, filename: str) -> Dict[str, Any]:
        """Extract title, policy codes, and category heuristics from text."""
        title = Path(filename).stem.replace("_", " ").title() if filename else "Accounting Policy"
        policy_id = ""
        category = "GENERAL"

        # Look for Markdown H1
        h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()

        # Look for Policy ID (e.g. Policy ACC-001, SOP-102, POL-REC-01)
        pid_match = re.search(r"(?:Policy|SOP|Rule|POL)[:\s]+([A-Z]{2,5}-\d{2,4})", text, re.IGNORECASE)
        if pid_match:
            policy_id = pid_match.group(1).upper()

        # Heuristic category determination
        text_lower = text.lower()
        if "reconciliation" in text_lower or "bank" in text_lower:
            category = "BANK_RECONCILIATION"
        elif "accrual" in text_lower or "expense matching" in text_lower:
            category = "ACCRUAL"
        elif "depreciation" in text_lower or "fixed asset" in text_lower:
            category = "DEPRECIATION"

        return {
            "title": title,
            "policy_id": policy_id,
            "category": category,
        }

    def _split_into_chunks(
        self,
        text: str,
        base_metadata: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Split text into semantic chunks respecting section headers and paragraph breaks."""
        # Split by markdown sections (## or ###)
        sections = re.split(r"(?=(?:^|\n)##?\s+)", text)
        chunks: List[Dict[str, Any]] = []

        for sec in sections:
            sec_clean = sec.strip()
            if not sec_clean:
                continue

            # Extract section name if present
            sec_heading = "General"
            heading_match = re.match(r"^##?\s+(.+)$", sec_clean, re.MULTILINE)
            if heading_match:
                sec_heading = heading_match.group(1).strip()

            # If section fits in single chunk
            if len(sec_clean) <= self.chunk_size:
                chunks.append({
                    "text": sec_clean,
                    "section": sec_heading,
                })
            else:
                # Sub-split long section by paragraphs or lines
                paragraphs = sec_clean.split("\n\n")
                current_chunk = ""

                for p in paragraphs:
                    p_str = p.strip()
                    if not p_str:
                        continue

                    if len(current_chunk) + len(p_str) + 2 <= self.chunk_size:
                        current_chunk = f"{current_chunk}\n\n{p_str}" if current_chunk else p_str
                    else:
                        if current_chunk:
                            chunks.append({
                                "text": current_chunk.strip(),
                                "section": sec_heading,
                            })
                        # Handle very long paragraph by character sliding window
                        if len(p_str) > self.chunk_size:
                            step = self.chunk_size - self.chunk_overlap
                            for start in range(0, len(p_str), step):
                                sub_p = p_str[start : start + self.chunk_size]
                                if sub_p.strip():
                                    chunks.append({
                                        "text": sub_p.strip(),
                                        "section": sec_heading,
                                    })
                            current_chunk = ""
                        else:
                            current_chunk = p_str

                if current_chunk:
                    chunks.append({
                        "text": current_chunk.strip(),
                        "section": sec_heading,
                    })

        # Attach metadata to each chunk
        total_chunks = len(chunks)
        results: List[Dict[str, Any]] = []
        ingested_at = datetime.now(timezone.utc).isoformat()

        for idx, chk in enumerate(chunks):
            chunk_text = chk["text"]
            chunk_meta = {
                **base_metadata,
                "section": chk["section"],
                "chunk_index": idx,
                "total_chunks": total_chunks,
                "char_count": len(chunk_text),
                "ingested_at": ingested_at,
            }
            results.append({
                "chunk_id": f"{base_metadata['doc_id']}_chunk_{idx}",
                "text": chunk_text,
                "metadata": chunk_meta,
            })

        return results

    # ----------------------------------------------------------------------
    # Public Ingestion APIs
    # ----------------------------------------------------------------------

    def ingest_text(
        self,
        text: str,
        doc_id: str,
        filename: str = "",
        metadata_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ingest raw text or markdown string into ChromaDB with deduplication."""
        if not text or not text.strip():
            return {
                "doc_id": doc_id,
                "status": "FAILED",
                "chunks_count": 0,
                "message": "Empty document text.",
            }

        extracted_meta = self._extract_policy_metadata(text, filename)
        base_meta = {
            "doc_id": doc_id,
            "filename": filename or f"{doc_id}.txt",
            **extracted_meta,
            **(metadata_override or {}),
        }

        # Deduplication: remove existing chunks for this doc_id
        self.vectorstore_manager.delete_by_doc_id(doc_id, self.collection_name)

        # Generate new chunks
        chunks = self._split_into_chunks(text, base_meta)
        if not chunks:
            return {
                "doc_id": doc_id,
                "status": "EMPTY",
                "chunks_count": 0,
                "message": "No chunks generated from document.",
            }

        # Index in ChromaDB
        collection = self.vectorstore_manager.get_or_create_collection(self.collection_name)
        collection.add(
            ids=[c["chunk_id"] for c in chunks],
            documents=[c["text"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
        )

        return {
            "doc_id": doc_id,
            "filename": base_meta["filename"],
            "title": base_meta["title"],
            "policy_id": base_meta.get("policy_id", ""),
            "category": base_meta.get("category", "GENERAL"),
            "chunks_count": len(chunks),
            "status": "INGESTED",
        }

    def ingest_file(
        self,
        file_path: str,
        metadata_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ingest a single policy document from file path."""
        path = Path(file_path)
        if not path.exists():
            return {
                "file_path": file_path,
                "status": "FILE_NOT_FOUND",
                "chunks_count": 0,
            }

        doc_id = path.stem.lower().replace(" ", "_")
        text = self.extract_text_from_file(file_path)

        res = self.ingest_text(
            text=text,
            doc_id=doc_id,
            filename=path.name,
            metadata_override=metadata_override,
        )
        res["file_path"] = str(path.resolve())
        return res

    def ingest_directory(
        self,
        directory_path: str,
        glob_pattern: str = "*.*",
    ) -> List[Dict[str, Any]]:
        """Batch ingest all supported policy documents from a directory."""
        dir_p = Path(directory_path)
        if not dir_p.exists() or not dir_p.is_dir():
            return []

        results: List[Dict[str, Any]] = []
        supported_extensions = {".md", ".txt", ".markdown", ".pdf", ".docx", ".doc"}

        for p in dir_p.glob(glob_pattern):
            if p.is_file() and p.suffix.lower() in supported_extensions:
                res = self.ingest_file(str(p))
                results.append(res)

        return results

    def delete_document(self, doc_id: str) -> int:
        """Delete a document by doc_id from ChromaDB."""
        return self.vectorstore_manager.delete_by_doc_id(doc_id, self.collection_name)
