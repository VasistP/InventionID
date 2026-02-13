import type { PipelineReport, ProgressMessage } from '../types';
import { SummaryHeader } from './SummaryHeader';
import { PatentCard } from './PatentCard';
import { ProgressTracker } from './ProgressTracker';

interface ResultsDisplayProps {
  report: PipelineReport;
  progress: ProgressMessage[];
}

export function ResultsDisplay({ report, progress }: ResultsDisplayProps) {
  const handleDownloadPdf = () => {
    window.print();
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex justify-end print:hidden">
        <button
          onClick={handleDownloadPdf}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-md shadow-sm hover:bg-gray-50 hover:text-gray-800 transition-colors cursor-pointer"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5m0 0l5-5m-5 5V3" />
          </svg>
          Download PDF
        </button>
      </div>

      {progress.length > 0 && (
        <ProgressTracker progress={progress} defaultExpanded={false} />
      )}

      <SummaryHeader report={report} />

      {report.patents.length > 0 && (
        <div>
          <h3 className="text-lg font-medium text-gray-800 mb-3">
            Patent Results ({report.patents.length})
          </h3>
          <div className="grid gap-4">
            {report.patents.map((patent, i) => (
              <PatentCard key={patent.patent_number || i} patent={patent} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
