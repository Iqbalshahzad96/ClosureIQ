/**
 * Upload service for Financial File Upload.
 *
 * Implements the raw-body HTTP contract:
 * POST /api/v1/imports/upload?filename=...&adapter_key=...
 * Body: Raw file bytes (NOT FormData, NOT JSON).
 * Header: Content-Type: safe MIME type
 * Header: X-Import-Options: internally generated JSON string
 */

import {
  getDocumentTypeConfig,
  buildImportOptions,
  normalizeImportResponse,
  sanitizeDiagnosticMessage,
} from './uploadNormalizers';

export const MAX_FILE_BYTES = 25 * 1024 * 1024; // 25 MiB
export const SUPPORTED_EXTENSIONS = ['.csv', '.xlsx', '.xls'];

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

/**
 * Validates a file before sending over the wire.
 * Returns an error message string if invalid, or null if valid.
 */
export function validateFileClientSide(file) {
  if (!file) {
    return 'Please select a financial file to upload.';
  }

  const name = typeof file.name === 'string' ? file.name : '';
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();

  if (!SUPPORTED_EXTENSIONS.includes(ext)) {
    return `Unsupported file format (${ext || 'unknown'}). Please upload a .csv, .xlsx, or .xls file.`;
  }

  const size = typeof file.size === 'number' ? file.size : 0;
  if (size <= 0) {
    return 'The selected file is empty (0 bytes). Please select a valid document.';
  }

  if (size > MAX_FILE_BYTES) {
    return `The selected file (${(size / (1024 * 1024)).toFixed(1)} MiB) exceeds the 25 MiB upload limit.`;
  }

  return null;
}

/**
 * Determine safe Content-Type MIME based on file extension.
 */
export function getContentTypeForFile(filename) {
  const name = typeof filename === 'string' ? filename : '';
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();

  switch (ext) {
    case '.csv':
      return 'text/csv';
    case '.xlsx':
      return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    case '.xls':
      return 'application/vnd.ms-excel';
    default:
      return 'application/octet-stream';
  }
}

/**
 * Uploads a financial document as raw bytes to the ingestion endpoint.
 */
export async function uploadFinancialFile({
  file,
  documentType,
  financeOptions = {},
  signal,
}) {
  // 1. Client-side preflight validation
  const validationError = validateFileClientSide(file);
  if (validationError) {
    throw new Error(validationError);
  }

  // 2. Resolve document type adapter config
  const config = getDocumentTypeConfig(documentType);

  // 3. Build query parameters safely
  const queryParams = new URLSearchParams();
  queryParams.set('filename', file.name);
  queryParams.set('adapter_key', config.adapterKey);

  // 4. Build headers
  const importOptions = buildImportOptions(documentType, financeOptions);
  const contentType = getContentTypeForFile(file.name);

  const url = `${BASE_URL}/imports/upload?${queryParams.toString()}`;

  const requestOptions = {
    method: 'POST',
    headers: {
      'Content-Type': contentType,
      'X-Import-Options': JSON.stringify(importOptions),
    },
    // Raw file bytes sent as the body directly—never FormData and never JSON
    body: file,
    signal,
  };

  let response;
  try {
    response = await fetch(url, requestOptions);
  } catch (err) {
    if (err.name === 'AbortError') {
      throw err;
    }
    throw new Error('Unable to connect to the server. Please check your network and try again.');
  }

  // 5. Handle HTTP status codes
  if (!response.ok) {
    let errorText = '';
    try {
      errorText = await response.text();
    } catch {
      errorText = '';
    }

    if (response.status === 413) {
      throw new Error('File exceeds the 25 MiB upload limit.');
    }
    if (response.status === 422) {
      throw new Error('Invalid import options provided for this document type.');
    }
    if (response.status === 400) {
      const sanitized = sanitizeDiagnosticMessage(errorText);
      throw new Error(`File validation failed: ${sanitized}`);
    }
    // Generic sanitized error for 500 and other unexpected status codes
    throw new Error('The server could not complete the import. Please check the file and try again.');
  }

  // 6. Parse and normalize response JSON
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('The server returned an unreadable response. Please retry.');
  }

  return normalizeImportResponse(data);
}

