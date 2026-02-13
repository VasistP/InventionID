import { useState } from 'react';
import type { ProgressMessage } from '../types';
import { STAGE_LABELS, TOTAL_STAGES } from '../types';

interface ProgressTrackerProps {
  progress: ProgressMessage[];
  defaultExpanded?: boolean;
}

function StageIcon({ state }: { state: 'completed' | 'running' | 'pending' | 'error' }) {
  switch (state) {
    case 'completed':
      return (
        <div className="w-6 h-6 rounded-full bg-green-500 flex items-center justify-center">
          <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
          </svg>
        </div>
      );
    case 'running':
      return (
        <div className="w-6 h-6 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
      );
    case 'error':
      return (
        <div className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center">
          <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
      );
    default:
      return <div className="w-6 h-6 rounded-full bg-gray-200" />;
  }
}

export function ProgressTracker({ progress, defaultExpanded = true }: ProgressTrackerProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const latestMsg = progress[progress.length - 1];
  const currentStage = latestMsg?.stage ?? -1;
  const isError = latestMsg?.status === 'error';
  const isDone = latestMsg?.status === 'completed';

  // Build stage list 0-6
  const stages = Array.from({ length: TOTAL_STAGES }, (_, i) => {
    const stageProgress = progress.filter((p) => p.stage === i);
    const detail = stageProgress.find((p) => p.detail)?.detail;
    let state: 'completed' | 'running' | 'pending' | 'error';

    if (isError && currentStage === i) {
      state = 'error';
    } else if (i < currentStage || isDone) {
      state = 'completed';
    } else if (i === currentStage) {
      state = 'running';
    } else {
      state = 'pending';
    }

    return { stage: i, label: STAGE_LABELS[i], detail, state };
  });

  const headerText = isDone
    ? 'Analysis Complete'
    : isError
      ? 'Pipeline Error'
      : `Stage ${currentStage + 1} of ${TOTAL_STAGES}: ${STAGE_LABELS[currentStage] ?? 'Starting...'}`;

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {isDone ? (
            <StageIcon state="completed" />
          ) : isError ? (
            <StageIcon state="error" />
          ) : (
            <StageIcon state="running" />
          )}
          <span className="font-medium text-gray-800">{headerText}</span>
        </div>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-100">
          <div className="mt-3 space-y-3">
            {stages.map(({ stage, label, detail, state }) => (
              <div key={stage} className="flex items-start gap-3">
                <div className="mt-0.5">
                  <StageIcon state={state} />
                </div>
                <div>
                  <p className={`text-sm font-medium ${
                    state === 'pending' ? 'text-gray-400' : 'text-gray-700'
                  }`}>
                    {label}
                  </p>
                  {detail && (
                    <p className="text-xs text-gray-400 mt-0.5">{detail}</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {isError && latestMsg?.error && (
            <div className="mt-3 p-3 bg-red-50 rounded text-sm text-red-700">
              {latestMsg.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
