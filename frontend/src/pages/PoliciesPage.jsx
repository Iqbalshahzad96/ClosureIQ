import React, { useState, useEffect, useRef } from 'react';
import {
  BookOpen,
  UploadCloud,
  Search,
  Trash2,
  RefreshCw,
  FileText,
  CheckCircle2,
  AlertCircle,
  Layers,
  Sparkles,
  HelpCircle,
} from 'lucide-react';
import {
  uploadPolicyFile,
  fetchPolicyDocuments,
  deletePolicyDocument,
  queryPolicyContext,
} from '../services/policyService';

export default function PoliciesPage() {
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [category, setCategory] = useState('RECONCILIATION');
  const [policyId, setPolicyId] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [error, setError] = useState(null);

  // Semantic query state
  const [searchQuery, setSearchQuery] = useState('');
  const [queryCategory, setQueryCategory] = useState('');
  const [queryResults, setQueryResults] = useState(null);
  const [querying, setQuerying] = useState(false);

  const fileInputRef = useRef(null);

  const loadDocuments = async () => {
    setLoadingDocs(true);
    setError(null);
    try {
      const data = await fetchPolicyDocuments();
      setDocuments(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load policy documents');
    } finally {
      setLoadingDocs(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      if (!policyId) {
        // Auto-populate policy ID from filename
        const baseName = file.name.replace(/\.[^/.]+$/, '').replace(/[^a-zA-Z0-9_-]/g, '_');
        setPolicyId(baseName);
      }
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile) {
      setError('Please select a document file (.md, .txt, .pdf, .docx) to upload.');
      return;
    }

    setUploading(true);
    setError(null);
    setUploadSuccess(null);

    try {
      const res = await uploadPolicyFile({
        file: selectedFile,
        category,
        policyId: policyId || undefined,
      });

      setUploadSuccess(`Policy document "${selectedFile.name}" successfully indexed into ChromaDB (${res.chunks_indexed || res.chunks_created || 'chunks indexed'}).`);
      setSelectedFile(null);
      setPolicyId('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      loadDocuments();
    } catch (err) {
      setError(err.message || 'Failed to upload policy document');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (docId) => {
    if (!confirm(`Are you sure you want to delete policy document "${docId}" from ChromaDB?`)) {
      return;
    }

    setDeletingId(docId);
    setError(null);
    try {
      await deletePolicyDocument(docId);
      setDocuments((prev) => prev.filter((d) => (d.doc_id || d.id) !== docId));
    } catch (err) {
      setError(err.message || 'Failed to delete policy document');
    } finally {
      setDeletingId(null);
    }
  };

  const handleQuery = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setQuerying(true);
    setError(null);
    try {
      const res = await queryPolicyContext({
        query: searchQuery,
        category: queryCategory || undefined,
        topK: 3,
      });
      setQueryResults(res.results || res.documents || res);
    } catch (err) {
      setError(err.message || 'Query failed');
    } finally {
      setQuerying(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700 }}>Accounting Policies & SOP Knowledge Base</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Ingest and manage GAAP / IFRS accounting rules, materiality guidelines, and standard operating procedures for Agent 2 RAG reasoning.
          </p>
        </div>

        <button
          className="button button-outline"
          onClick={loadDocuments}
          disabled={loadingDocs}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={16} className={loadingDocs ? 'spin' : ''} />
          <span>Refresh Knowledge Base</span>
        </button>
      </div>

      {uploadSuccess && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid var(--accent-emerald)', color: 'var(--accent-emerald)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <CheckCircle2 size={18} />
          <span>{uploadSuccess}</span>
        </div>
      )}

      {error && (
        <div style={{ padding: '1rem', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid var(--accent-rose)', color: 'var(--accent-rose)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Grid: Upload & Semantic Search */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '1.5rem' }}>
        {/* Upload Card */}
        <div className="card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <UploadCloud size={20} color="var(--primary)" />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Upload Policy / SOP Document</h3>
          </div>

          <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.825rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Select Document (.md, .txt, .pdf, .docx):
              </label>
              <input
                type="file"
                ref={fileInputRef}
                accept=".md,.txt,.pdf,.docx,.markdown"
                onChange={handleFileChange}
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-color)',
                  background: 'var(--bg-primary)',
                  color: 'var(--text-primary)',
                  fontSize: '0.85rem',
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.825rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Category:
                </label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-color)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)',
                    fontSize: '0.85rem',
                  }}
                >
                  <option value="RECONCILIATION">Reconciliation</option>
                  <option value="ACCRUAL">Accrual SOP</option>
                  <option value="DEPRECIATION">Depreciation SOP</option>
                  <option value="GENERAL_CLOSE">General Close</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.825rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                  Policy Identifier:
                </label>
                <input
                  type="text"
                  placeholder="e.g. SOP-REV-01"
                  value={policyId}
                  onChange={(e) => setPolicyId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-color)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)',
                    fontSize: '0.85rem',
                  }}
                />
              </div>
            </div>

            <button
              type="submit"
              className="button button-primary"
              disabled={uploading || !selectedFile}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', marginTop: '0.5rem' }}
            >
              <UploadCloud size={16} className={uploading ? 'spin' : ''} />
              <span>{uploading ? 'Ingesting into ChromaDB...' : 'Ingest & Index Policy'}</span>
            </button>
          </form>
        </div>

        {/* Semantic Query Tester Card */}
        <div className="card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Sparkles size={20} color="var(--accent-amber)" />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>RAG Semantic Retrieval Tester</h3>
          </div>

          <form onSubmit={handleQuery} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.825rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                Query Accounting SOPs & Guidelines:
              </label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  type="text"
                  placeholder="e.g. What is the accrual threshold for unbilled expenses?"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    flex: 1,
                    padding: '0.5rem 0.75rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-color)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)',
                    fontSize: '0.85rem',
                  }}
                />
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={querying || !searchQuery.trim()}
                  style={{ padding: '0.5rem 1rem' }}
                >
                  <Search size={16} className={querying ? 'spin' : ''} />
                </button>
              </div>
            </div>
          </form>

          {/* Query Results */}
          {queryResults && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '220px', overflowY: 'auto' }}>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                Retrieved Chunks:
              </span>
              {Array.isArray(queryResults) && queryResults.length > 0 ? (
                queryResults.map((chunk, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: '0.6rem',
                      background: 'var(--bg-primary)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.8rem',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.2rem', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{chunk.policy_name || chunk.metadata?.policy_id || `Chunk #${idx + 1}`}</span>
                      {chunk.score !== undefined && (
                        <span style={{ color: 'var(--accent-emerald)', fontSize: '0.75rem' }}>
                          Score: {(1 - Number(chunk.score)).toFixed(2)}
                        </span>
                      )}
                    </div>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.775rem', lineHeight: 1.4 }}>
                      {chunk.text || chunk.content || (typeof chunk === 'string' ? chunk : JSON.stringify(chunk))}
                    </p>
                  </div>
                ))
              ) : (
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No matching chunks found.</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Indexed Documents Table */}
      <div className="card" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <BookOpen size={18} color="var(--primary)" />
            Indexed Policy & SOP Documents ({documents.length})
          </h3>
        </div>

        {loadingDocs ? (
          <div style={{ textAlign: 'center', padding: '2.5rem 1rem' }}>
            <RefreshCw size={28} className="spin" style={{ margin: '0 auto 0.75rem auto', color: 'var(--primary)' }} />
            <p style={{ color: 'var(--text-secondary)' }}>Loading policy documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--text-muted)' }}>
            <FileText size={36} style={{ margin: '0 auto 0.75rem auto', opacity: 0.6 }} />
            <p>No policy documents indexed in ChromaDB yet. Upload SOP markdown/text files above.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Policy ID / Title</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Filename</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Category</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Chunks</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Indexed At</th>
                  <th style={{ padding: '0.75rem 0.5rem', textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc, idx) => {
                  const docId = doc.doc_id || doc.id || `doc-${idx}`;
                  const isDeleting = deletingId === docId;
                  return (
                    <tr key={docId} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>
                        {doc.policy_name || docId}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-secondary)', fontFamily: 'monospace', fontSize: '0.8rem' }}>
                        {doc.filename || `${docId}.md`}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem' }}>
                        <span className="badge badge-neutral" style={{ textTransform: 'uppercase', fontSize: '0.75rem' }}>
                          {doc.category || 'RECONCILIATION'}
                        </span>
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem' }}>
                        {doc.chunk_count || doc.chunks || 1}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : 'Active'}
                      </td>
                      <td style={{ padding: '0.75rem 0.5rem', textAlign: 'right' }}>
                        <button
                          className="button button-ghost"
                          style={{ color: 'var(--accent-rose)', padding: '0.25rem 0.5rem' }}
                          onClick={() => handleDelete(docId)}
                          disabled={isDeleting}
                          title="Delete policy from ChromaDB"
                        >
                          <Trash2 size={16} className={isDeleting ? 'spin' : ''} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
