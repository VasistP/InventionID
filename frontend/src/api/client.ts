import { API_BASE } from '../config';
import type { PipelineReport } from '../types';

export async function uploadPdf(file: File, userInventionInput: string = ""): Promise<{ s3_key: string; filename: string }> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('user_invention_input', userInventionInput);

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}

export async function fetchResults(resultKey: string): Promise<PipelineReport> {
  const res = await fetch(`${API_BASE}/results/${resultKey}`);
  if (!res.ok) throw new Error('Report not found');
  return res.json();
}

export async function checkStatus(): Promise<{
  busy: boolean;
  s3_key?: string;
  result_key?: string;
  status?: string;
  progress?: any[];
}> {
  const res = await fetch(`${API_BASE}/status`);
  return res.json();
}
