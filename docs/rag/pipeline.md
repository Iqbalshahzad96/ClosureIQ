# RAG Pipeline Specification

## Overview
Grounds AI Agent recommendations with verified corporate accounting policies and Standard Operating Procedures (SOPs).

## Architecture
1. **Document Storage**: Markdown policy documents in `data/policies/`.
2. **Ingestion**: Recursive text chunking with metadata (policy ID, category, effective date).
3. **Embedding & Vector Store**: Local persistent ChromaDB instance in `chroma_data/`.
4. **Retrieval**: Top-k semantic similarity search attached to prompt contexts for Exception Analysis Agent.
