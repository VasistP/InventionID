import { API_BASE } from '../config';
import type { PipelineReport } from '../types';

export class UnauthorizedError extends Error {
  constructor() {
    super('Unauthorized');
  }
}

function authHeaders(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function checkUnauthorized(res: Response): Promise<void> {
  if (res.status === 401) throw new UnauthorizedError();
}

export async function uploadPdf(
  file: File,
  userInventionInput: string = '',
  token: string | null,
): Promise<{ s3_key: string; filename: string }> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_invention_input', userInventionInput);

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    headers: authHeaders(token),
    body: formData,
  });

  await checkUnauthorized(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export async function fetchResults(
  resultKey: string,
  token: string | null,
): Promise<PipelineReport> {
  const res = await fetch(`${API_BASE}/results/${resultKey}`, {
    headers: authHeaders(token),
  });
  await checkUnauthorized(res);
  if (!res.ok) throw new Error('Report not found');
  return res.json();
}

export async function checkStatus(token: string | null): Promise<{
  busy: boolean;
  s3_key?: string;
  result_key?: string;
  status?: string;
  progress?: any[];
}> {
  const res = await fetch(`${API_BASE}/status`, { headers: authHeaders(token) });
  await checkUnauthorized(res);
  return res.json();
}

export async function requestRerun(
  resultKey: string,
  requiredKeywords: string[],
  optionalKeywords: string[],
  token: string | null,
): Promise<{ rerun_id: string }> {
  const res = await fetch(`${API_BASE}/rerun`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({
      result_key: resultKey,
      required_keywords: requiredKeywords,
      optional_keywords: optionalKeywords,
    }),
  });
  await checkUnauthorized(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Rerun request failed' }));
    throw new Error(err.detail || 'Rerun request failed');
  }
  return res.json();
}
