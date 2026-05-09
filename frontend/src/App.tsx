import { usePipeline } from './hooks/usePipeline';
import { Sidebar } from './components/Sidebar';
import { UploadArea } from './components/UploadArea';
import { ProgressTracker } from './components/ProgressTracker';
import { ResultsDisplay } from './components/ResultsDisplay';

export default function App() {
  const { sessions, activeSession, startAnalysis, rerunWithKeywords, selectSession, newAnalysis } = usePipeline();

  const isRunning = activeSession?.status === 'running' || activeSession?.status === 'uploading';
  const showUpload = !activeSession && !isRunning;
  const showProgress = isRunning && activeSession;
  const showResults = activeSession?.status === 'completed' && activeSession.report;
  const showError = activeSession?.status === 'error';

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar
        sessions={sessions}
        activeId={activeSession?.id ?? null}
        onSelect={selectSession}
        onNew={newAnalysis}
      />

      <main className="flex-1 overflow-y-auto p-8">
        {showUpload && (
          <UploadArea onUpload={startAnalysis} />
        )}

        {showProgress && (
          <div className="max-w-2xl mx-auto mt-12 space-y-6">
            <ProgressTracker progress={activeSession.progress} />
          </div>
        )}

        {showResults && (
          <ResultsDisplay
            report={activeSession.report!}
            progress={activeSession.progress}
            durationSeconds={activeSession.durationSeconds}
            onRerun={(req, opt) => rerunWithKeywords(activeSession!, req, opt)}
          />
        )}

        {showError && (
          <div className="max-w-2xl mx-auto mt-12 space-y-4">
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
              Analysis failed: {activeSession.error || 'Unknown error'}
            </div>
            {activeSession.progress.length > 0 && (
              <ProgressTracker progress={activeSession.progress} defaultExpanded={true} />
            )}
            <button
              onClick={newAnalysis}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm"
            >
              Try Again
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
