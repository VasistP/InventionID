import { WS_BASE } from '../config';
import type { ProgressMessage } from '../types';

export function connectPipeline(
  s3Key: string,
  onMessage: (msg: ProgressMessage) => void,
  onError: (error: string) => void,
  onClose: () => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/pipeline/${s3Key}`);

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
  onMessage: (msg: ProgressMessage) => void,
  onError: (error: string) => void,
  onClose: () => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/rerun/${rerunId}`);

  ws.onmessage = (event) => {
    const data: ProgressMessage = JSON.parse(event.data);
    onMessage(data);
  };

  ws.onerror = () => onError('WebSocket connection failed');
  ws.onclose = onClose;

  return ws;
}
