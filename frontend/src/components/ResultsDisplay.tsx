import { useMemo } from 'react';
import type { PipelineReport, Patent, ProgressMessage } from '../types';
import { SummaryHeader } from './SummaryHeader';
import { PatentCard } from './PatentCard';
import { ProgressTracker } from './ProgressTracker';

interface ResultsDisplayProps {
  report: PipelineReport;
  progress: ProgressMessage[];
  durationSeconds?: number;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

const GROUP_ORDER = ['blocking', 'relevant', 'related'] as const;

const groupStyles: Record<string, { label: string; color: string }> = {
  blocking: { label: 'Blocking', color: 'text-red-700' },
  relevant: { label: 'Relevant', color: 'text-yellow-700' },
  related:  { label: 'Related',  color: 'text-blue-700' },
};

export function ResultsDisplay({ report, progress, durationSeconds }: ResultsDisplayProps) {
  const handleDownloadPdf = () => {
    window.print();
  };

  const patentGroups = useMemo(() => {
    const byClass: Record<string, Patent[]> = {};
    for (const p of report.patents) {
      const cls = p.analysis?.classification ?? 'other';
      (byClass[cls] ??= []).push(p);
    }
    // Sort each group by relevance_score descending
    for (const patents of Object.values(byClass)) {
      patents.sort((a, b) =>
        (b.analysis?.relevance_score ?? 0) - (a.analysis?.relevance_score ?? 0)
      );
    }
    // Emit groups in priority order, then any remaining
    const result: { key: string; label: string; color: string; patents: Patent[] }[] = [];
    for (const cls of GROUP_ORDER) {
      if (byClass[cls]?.length) {
        const style = groupStyles[cls];
        result.push({ key: cls, label: style.label, color: style.color, patents: byClass[cls] });
        delete byClass[cls];
      }
    }
    // Any leftover classifications (e.g. "other", "unknown")
    for (const [cls, patents] of Object.entries(byClass)) {
      if (patents.length) {
        result.push({ key: cls, label: cls.charAt(0).toUpperCase() + cls.slice(1), color: 'text-gray-600', patents });
      }
    }
    return result;
  }, [report.patents]);

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
          <div className="space-y-6">
            {patentGroups.map((group) => (
              <div key={group.key}>
                <h4 className={`text-sm font-semibold ${group.color} mb-2`}>
                  {group.label} ({group.patents.length})
                </h4>
                <div className="grid gap-4">
                  {group.patents.map((patent, i) => (
                    <PatentCard key={patent.patent_number || i} patent={patent} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {durationSeconds !== undefined && (
        <p className="text-xs text-gray-400 text-center pt-2">
          Analysis completed in {formatDuration(durationSeconds)}
        </p>
      )}
    </div>
  );
}
