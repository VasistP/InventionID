import { useState, useCallback, useRef, useEffect } from 'react';
import { uploadPdf, fetchResults, checkStatus } from '../api/client';
import { connectPipeline } from '../api/websocket';
import type { ProgressMessage, AnalysisSession } from '../types';

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function usePipeline() {
  const [sessions, setSessions] = useState<AnalysisSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;

  const updateSession = useCallback((id: string, patch: Partial<AnalysisSession>) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }, []);

  // Poll /api/status when WS disconnects while pipeline is still running
  const startPolling = useCallback(
    (sessionId: string) => {
      if (pollingRef.current) return;
      pollingRef.current = setInterval(async () => {
        try {
          const status = await checkStatus();
          if (!status.busy) {
            // Pipeline finished — try to get results
            if (pollingRef.current) {
              clearInterval(pollingRef.current);
              pollingRef.current = null;
            }
            if (status.result_key) {
              try {
                const report = await fetchResults(status.result_key);
                updateSession(sessionId, { report, status: 'completed', resultKey: status.result_key });
              } catch {
                updateSession(sessionId, { status: 'error', error: 'Pipeline finished but failed to fetch results' });
              }
            } else if (status.status === 'completed' && status.result_key) {
              const report = await fetchResults(status.result_key);
              updateSession(sessionId, { report, status: 'completed' });
            } else {
              updateSession(sessionId, { status: 'error', error: 'Pipeline finished without results' });
            }
          } else if (status.progress) {
            // Update progress from server state
            updateSession(sessionId, { progress: status.progress });
          }
        } catch {
          // Network error — keep polling
        }
      }, 3000);
    },
    [updateSession],
  );

  // On mount: check if a pipeline is already running (page refresh recovery)
  useEffect(() => {
    checkStatus().then((status) => {
      if (status.busy && status.s3_key) {
        const sessionId = generateId();
        const filename = status.s3_key.split('/').pop()?.replace(/^\d+_/, '') ?? 'unknown.pdf';
        const session: AnalysisSession = {
          id: sessionId,
          filename,
          s3Key: status.s3_key,
          startedAt: new Date(),
          status: 'running',
          progress: status.progress ?? [],
        };
        setSessions([session]);
        setActiveSessionId(sessionId);
        startPolling(sessionId);
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startAnalysis = useCallback(
    async (file: File) => {
      const sessionId = generateId();

      const session: AnalysisSession = {
        id: sessionId,
        filename: file.name,
        s3Key: '',
        startedAt: new Date(),
        status: 'uploading',
        progress: [],
      };
      setSessions((prev) => [session, ...prev]);
      setActiveSessionId(sessionId);

      try {
        const { s3_key } = await uploadPdf(file);
        updateSession(sessionId, { s3Key: s3_key, status: 'running' });

        wsRef.current = connectPipeline(
          s3_key,
          (msg: ProgressMessage) => {
            setSessions((prev) =>
              prev.map((s) => {
                if (s.id !== sessionId) return s;
                const newProgress = [...s.progress, msg];

                if (msg.status === 'completed' && msg.result_key) {
                  fetchResults(msg.result_key).then((report) => {
                    updateSession(sessionId, { report, status: 'completed' });
                  }).catch(() => {
                    updateSession(sessionId, {
                      status: 'error',
                      error: 'Failed to fetch results from S3',
                    });
                  });
                  return { ...s, progress: newProgress, resultKey: msg.result_key };
                }

                if (msg.status === 'error') {
                  return { ...s, progress: newProgress, status: 'error', error: msg.error };
                }

                return { ...s, progress: newProgress };
              }),
            );
          },
          (_error) => {
            // WebSocket error — fall back to polling
            startPolling(sessionId);
          },
          () => {
            // WebSocket closed — check if pipeline is still running and poll if so
            checkStatus().then((status) => {
              if (status.busy) {
                startPolling(sessionId);
              }
            }).catch(() => {});
          },
        );
      } catch (err) {
        updateSession(sessionId, {
          status: 'error',
          error: err instanceof Error ? err.message : 'Unknown error',
        });
      }
    },
    [updateSession, startPolling],
  );

  const selectSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const newAnalysis = useCallback(() => {
    setActiveSessionId(null);
  }, []);

  return {
    sessions,
    activeSession,
    startAnalysis,
    selectSession,
    newAnalysis,
  };
}
