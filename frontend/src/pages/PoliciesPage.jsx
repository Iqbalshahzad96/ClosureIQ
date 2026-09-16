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
  Sparkles,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import {
  uploadPolicyFile,
  fetchPolicyDocuments,
  deletePolicyDocument,
  answerPolicyQuestion,
} from '../services/policyService';

export default function PoliciesPage() {
  const [documents, setDocuments] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [updatingId, setUpdatingId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [expandedDocIds, setExpandedDocIds] = useState(() => new Set());
  const [selectedFile, setSelectedFile] = useState(null);
  const [category, setCategory] = useState('RECONCILIATION');
  const [policyId, setPolicyId] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [error, setError] = useState(null);

  // Policy chat state
  const [searchQuery, setSearchQuery] = useState('');
  const [queryCategory, setQueryCategory] = useState('');
  const [chatMessages, setChatMessages] = useState([]);
  const [querying, setQuerying] = useState(false);

  const fileInputRef = useRef(null);
  const updateInputRefs = useRef({});

  const loadDocuments = async () => {
    setLoadingDocs(true);
    setError(null);
    try {
      const data = await fetchPolicyDocuments();
      const rawDocs = Array.isArray(data)
        ? data
        : Array.isArray(data?.documents)
        ? data.documents
        : [];
      const docs = rawDocs.filter((d) => d && typeof d === 'object');
      setDocuments(docs);
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

      setUploadSuccess(`Policy document "${selectedFile.name}" successfully indexed into ChromaDB (${res.chunks_indexed || res.chunks_created || res.chunks_count || 'chunks indexed'}).`);
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

  const toggleExpanded = (docId) => {
    setExpandedDocIds((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        next.add(docId);
      }
      return next;
    });
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

  const handleUpdateFile = async (doc, file) => {
    const docId = doc.doc_id || doc.id;
    if (!docId || !file) return;

    setUpdatingId(docId);
    setError(null);
    setUploadSuccess(null);
    try {
      const res = await uploadPolicyFile({
        file,
        docId,
        category: doc.category || undefined,
        policyId: doc.policy_id || undefined,
      });
      setUploadSuccess(`Policy file "${doc.filename || docId}" replaced with "${file.name}" (${res.chunks_indexed || res.chunks_created || res.chunks_count || 'chunks indexed'}).`);
      await loadDocuments();
    } catch (err) {
      setError(err.message || 'Failed to update policy document');
    } finally {
      setUpdatingId(null);
      const input = updateInputRefs.current[docId];
      if (input) input.value = '';
    }
  };

  const handleQuery = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setQuerying(true);
    setError(null);
    const question = searchQuery.trim();
    const nextMessages = [...chatMessages, { role: 'user', content: question }];
    setChatMessages(nextMessages);
    setSearchQuery('');

    try {
      const res = await answerPolicyQuestion({
        question,
        history: chatMessages,
        category: queryCategory || undefined,
        topK: 2,
      });
      setChatMessages([
        ...nextMessages,
        {
          role: 'assistant',
          content: res.answer || 'No answer was generated.',
          citations: res.citations || [],
        },
      ]);
    } catch (err) {
      setChatMessages(chatMessages);
      setSearchQuery(question);
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

        {/* Policy Chat Card */}
        <div className="card" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Sparkles size={20} color="var(--accent-amber)" />
            <h3 style={{ fontSize: '1.05rem', fontWeight: 600 }}>Policy & SOP Chatbot</h3>
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
                  aria-label="Ask policy question"
                  style={{ padding: '0.5rem 1rem' }}
                >
                  <Search size={16} className={querying ? 'spin' : ''} />
                </button>
              </div>
            </div>
          </form>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', maxHeight: '260px', overflowY: 'auto' }}>
            {chatMessages.length === 0 ? (
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Ask a question about the indexed policies.</p>
            ) : (
              chatMessages.map((message, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '90%',
                    padding: '0.7rem',
                    background: message.role === 'user' ? 'rgba(59, 130, 246, 0.12)' : 'var(--bg-primary)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-color)',
                  }}
                >
                  <p style={{ color: 'var(--text-primary)', fontSize: '0.82rem', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                    {message.content}
                  </p>
                  {Array.isArray(message.citations) && message.citations.length > 0 && (
                    <div style={{ marginTop: '0.55rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Citations</span>
                      {message.citations.map((citation, cIdx) => (
                        <span key={cIdx} style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                          {citation.citation || citation.policy_id || citation.policy_name || `Citation ${cIdx + 1}`}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
            {querying && (
              <div
                style={{
                  alignSelf: 'flex-start',
                  padding: '0.7rem',
                  background: 'var(--bg-primary)',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-muted)',
                  fontSize: '0.82rem',
                }}
              >
                Answering...
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Current Policy Files */}
      <div className="card" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <BookOpen size={18} color="var(--primary)" />
            Current Policy Files ({documents.length})
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
            <p>No policy files found. Upload SOP markdown/text files above.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Filename</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Policy ID / Title</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Category</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Chunks</th>
                  <th style={{ padding: '0.75rem 0.5rem' }}>Indexed At</th>
                  <th style={{ padding: '0.75rem 0.5rem', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc, idx) => {
                  if (!doc || typeof doc !== 'object') return null;
                  const docId = doc.doc_id || doc.id || `doc-${idx}`;
                  const isDeleting = deletingId === docId;
                  const isUpdating = updatingId === docId;
                  const isExpanded = expandedDocIds.has(docId);
                  return (
                    <React.Fragment key={docId}>
                      <tr style={{ borderBottom: isExpanded ? 'none' : '1px solid var(--border-color)' }}>
                        <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-secondary)', fontFamily: 'monospace', fontSize: '0.8rem' }}>
                          <button
                            type="button"
                            className="button button-ghost"
                            onClick={() => toggleExpanded(docId)}
                            title={isExpanded ? 'Collapse file details' : 'Expand file details'}
                            style={{ padding: '0.2rem', marginRight: '0.4rem', verticalAlign: 'middle' }}
                          >
                            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          </button>
                          {doc.filename || `${docId}.md`}
                        </td>
                        <td style={{ padding: '0.75rem 0.5rem', fontWeight: 600 }}>
                          {doc.policy_name || doc.title || doc.policy_id || docId}
                        </td>
                        <td style={{ padding: '0.75rem 0.5rem' }}>
                          <span className="badge badge-neutral" style={{ textTransform: 'uppercase', fontSize: '0.75rem' }}>
                            {doc.category || 'RECONCILIATION'}
                          </span>
                        </td>
                        <td style={{ padding: '0.75rem 0.5rem' }}>
                          {doc.chunk_count || doc.chunks_count || doc.chunks || 1}
                        </td>
                        <td style={{ padding: '0.75rem 0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                          {doc.created_at || doc.last_ingested ? new Date(doc.created_at || doc.last_ingested).toLocaleDateString() : 'Active'}
                        </td>
                        <td style={{ padding: '0.75rem 0.5rem', textAlign: 'right' }}>
                          <input
                            type="file"
                            accept=".md,.txt,.pdf,.docx,.markdown"
                            ref={(el) => {
                              updateInputRefs.current[docId] = el;
                            }}
                            onChange={(e) => handleUpdateFile(doc, e.target.files?.[0])}
                            style={{ display: 'none' }}
                          />
                          <button
                            type="button"
                            className="button button-outline"
                            style={{ padding: '0.25rem 0.5rem', marginRight: '0.4rem' }}
                            onClick={() => updateInputRefs.current[docId]?.click()}
                            disabled={isUpdating || isDeleting}
                            title="Upload an updated file and replace this policy"
                          >
                            <UploadCloud size={16} className={isUpdating ? 'spin' : ''} />
                            <span style={{ marginLeft: '0.35rem' }}>{isUpdating ? 'Updating...' : 'Update'}</span>
                          </button>
                          <button
                            className="button button-ghost"
                            style={{ color: 'var(--accent-rose)', padding: '0.25rem 0.5rem' }}
                            onClick={() => handleDelete(docId)}
                            disabled={isDeleting || isUpdating}
                            title="Delete policy from ChromaDB"
                          >
                            <Trash2 size={16} className={isDeleting ? 'spin' : ''} />
                          </button>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                          <td colSpan={6} style={{ padding: '0 0.5rem 0.9rem 2.5rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.6rem', padding: '0.75rem', background: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
                              <span><strong style={{ color: 'var(--text-primary)' }}>Document ID:</strong> {docId}</span>
                              <span><strong style={{ color: 'var(--text-primary)' }}>Policy ID:</strong> {doc.policy_id || 'N/A'}</span>
                              <span><strong style={{ color: 'var(--text-primary)' }}>Title:</strong> {doc.policy_name || doc.title || 'N/A'}</span>
                              <span><strong style={{ color: 'var(--text-primary)' }}>Filename:</strong> {doc.filename || `${docId}.md`}</span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
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
