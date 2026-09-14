/**
 * Policy & SOP RAG API Service.
 *
 * Communicates with FastAPI /api/v1/rag endpoints for:
 * - Uploading policy/SOP documents (.md, .txt, .pdf, .docx)
 * - Ingesting raw policy text/markdown
 * - Querying semantic context from ChromaDB
 * - Listing all indexed policy documents
 * - Deleting indexed documents
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export async function uploadPolicyFile({ file, category, policyId, signal }) {
  if (!file) {
    throw new Error('Please select a policy document to upload.');
  }

  const url = `${BASE_URL}/rag/upload`;
  const formData = new FormData();
  formData.append('file', file);
  if (category) formData.append('category', category);
  if (policyId) formData.append('policy_id', policyId);

  const response = await fetch(url, {
    method: 'POST',
    body: formData,
    signal,
  });

  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = data.detail || '';
    } catch {
      detail = await response.text().catch(() => '');
    }
    throw new Error(detail || `Policy upload failed (${response.status})`);
  }

  return await response.json();
}

export async function ingestPolicyText({ docId, text, filename, metadata = {}, signal }) {
  if (!docId || !text) {
    throw new Error('docId and text are required');
  }

  const url = `${BASE_URL}/rag/ingest/text`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      doc_id: docId,
      text,
      filename: filename || `${docId}.md`,
      metadata,
    }),
    signal,
  });

  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = data.detail || '';
    } catch {
      detail = await response.text().catch(() => '');
    }
    throw new Error(detail || `Policy text ingestion failed (${response.status})`);
  }

  return await response.json();
}

export async function fetchPolicyDocuments({ signal } = {}) {
  const url = `${BASE_URL}/rag/documents`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch policy documents (${response.status})`);
  }

  return await response.json();
}

export async function deletePolicyDocument(docId, { signal } = {}) {
  if (!docId) {
    throw new Error('docId is required');
  }

  const url = `${BASE_URL}/rag/documents/${encodeURIComponent(docId)}`;
  const response = await fetch(url, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = data.detail || '';
    } catch {
      detail = await response.text().catch(() => '');
    }
    throw new Error(detail || `Delete failed (${response.status})`);
  }

  return await response.json();
}

export async function queryPolicyContext({ query, category, topK = 3, signal } = {}) {
  if (!query) {
    throw new Error('query is required');
  }

  const url = `${BASE_URL}/rag/query`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      query,
      category: category || null,
      top_k: Number(topK) || 3,
    }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Policy query failed (${response.status})`);
  }

  return await response.json();
}
