import { WS_BASE } from '../config';
import type { ProgressMessage } from '../types';

export function connectPipeline(
  s3Key: string,
  token: string,
  onMessage: (msg: ProgressMessage) => void,
  onError: (error: string) => void,
  onClose: () => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/pipeline/${s3Key}?token=${encodeURIComponent(token)}`);

  ws.onmessage = (event) => {
    const data: ProgressMessage = JSON.parse(event.data);
    onMessage(data);
  };

  ws.onerror = () => onError('WebSocket connection failed');
  ws.onclose = onClose;

  return ws;
}

export function connectRerun(
  rerunId: string,
  token: string,
  onMessage: (msg: ProgressMessage) => void,
  onError: (error: string) => void,
  onClose: () => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/rerun/${rerunId}?token=${encodeURIComponent(token)}`);

  ws.onmessage = (event) => {
    const data: ProgressMessage = JSON.parse(event.data);
    onMessage(data);
  };

  ws.onerror = () => onError('WebSocket connection failed');
  ws.onclose = onClose;

  return ws;
}
