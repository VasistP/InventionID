import React, { useMemo, useState } from 'react';
import type { PipelineReport, Patent, ScholarPaper, ProgressMessage } from '../types';
import { SummaryHeader } from './SummaryHeader';
import { PatentCard } from './PatentCard';
import { PaperCard } from './PaperCard';
import { ProgressTracker } from './ProgressTracker';
import { QueryCountsPanel } from './QueryCountsPanel';
import { ConceptMapPanel } from './ConceptMapPanel';

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
  blocking: { label: 'Potentially Blocking', color: 'text-red-700' },
  relevant: { label: 'Relevant', color: 'text-yellow-700' },
  related:  { label: 'Related',  color: 'text-blue-700' },
};

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
      fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

function CollapsibleGroup({
  label, color, count, defaultOpen, children,
}: {
  label: string; color: string; count: number; defaultOpen: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 w-full text-left mb-2 group"
      >
        <h4 className={`text-sm font-semibold ${color}`}>{label} ({count})</h4>
        <span className="ml-auto"><ChevronIcon open={open} /></span>
      </button>
      {open && <div className="grid gap-4">{children}</div>}
    </div>
  );
}

export function ResultsDisplay({ report, progress, durationSeconds }: ResultsDisplayProps) {
  const handleDownloadPdf = () => {
    window.print();
  };

  const paperGroups = useMemo(() => {
    const papers = report.scholar_papers ?? [];
    const byClass: Record<string, ScholarPaper[]> = {};
    for (const p of papers) {
      const cls = p.analysis?.classification ?? 'other';
      (byClass[cls] ??= []).push(p);
    }
    for (const papers of Object.values(byClass)) {
      papers.sort((a, b) =>
        (b.analysis?.relevance_score ?? 0) - (a.analysis?.relevance_score ?? 0)
      );
    }
    const result: { key: string; label: string; color: string; papers: ScholarPaper[] }[] = [];
    for (const cls of GROUP_ORDER) {
      if (byClass[cls]?.length) {
        const style = groupStyles[cls];
        result.push({ key: cls, label: style.label, color: style.color, papers: byClass[cls] });
        delete byClass[cls];
      }
    }
    for (const [cls, papers] of Object.entries(byClass)) {
      if (papers.length) {
        result.push({ key: cls, label: cls.charAt(0).toUpperCase() + cls.slice(1), color: 'text-gray-600', papers });
      }
    }
    return result;
  }, [report.scholar_papers]);

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

      {report.run_metadata?.query_counts && Object.keys(report.run_metadata.query_counts).length > 0 && (
        <QueryCountsPanel queryCounts={report.run_metadata.query_counts} />
      )}

      {report.run_metadata?.concept_map && (
        <ConceptMapPanel conceptMap={report.run_metadata.concept_map} />
      )}

      {report.patents.length > 0 && (
        <div>
          <h3 className="text-lg font-medium text-gray-800 mb-3">
            Patent Results ({report.patents.length})
          </h3>
          <div className="space-y-6">
            {patentGroups.map((group) => (
              <CollapsibleGroup
                key={group.key}
                label={group.label}
                color={group.color}
                count={group.patents.length}
                defaultOpen={(GROUP_ORDER as readonly string[]).includes(group.key)}
              >
                {group.patents.map((patent, i) => (
                  <PatentCard key={patent.patent_number || i} patent={patent} animationIndex={i} />
                ))}
              </CollapsibleGroup>
            ))}
          </div>
        </div>
      )}

      {paperGroups.length > 0 && (
        <div>
          <h3 className="text-lg font-medium text-gray-800 mb-3">
            Academic Papers ({report.scholar_papers?.length ?? 0})
          </h3>
          <div className="space-y-6">
            {paperGroups.map((group) => (
              <CollapsibleGroup
                key={group.key}
                label={group.label}
                color={group.color}
                count={group.papers.length}
                defaultOpen={(GROUP_ORDER as readonly string[]).includes(group.key)}
              >
                {group.papers.map((paper, i) => (
                  <PaperCard key={paper.url || paper.title || i} paper={paper} animationIndex={i} />
                ))}
              </CollapsibleGroup>
            ))}
          </div>
        </div>
      )}

      {durationSeconds !== undefined && (
        <p className="text-xs text-gray-400 text-center pt-2">
          Analysis completed in {formatDuration(durationSeconds)}
        </p>
      )}

      {report.run_metadata && (
        <details className="text-center">
          <summary className="text-xs text-gray-300 cursor-pointer hover:text-gray-400 select-none">
            Run info
          </summary>
          <p className="text-xs text-gray-300 mt-1">
            v{report.run_metadata.pipeline_version} &middot; {new Date(report.run_metadata.timestamp).toLocaleString()}
          </p>
          <p className="text-xs text-gray-300">
            {Object.entries(report.run_metadata.models).map(([k, v]) => `${k}: ${v.split('.').pop()}`).join(' · ')}
          </p>
        </details>
      )}
    </div>
  );
}
