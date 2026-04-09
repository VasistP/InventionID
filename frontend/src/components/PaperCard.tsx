import { useState } from 'react';
import type { ScholarPaper } from '../types';

interface PaperCardProps {
  paper: ScholarPaper;
  animationIndex?: number;
}

const classificationColors: Record<string, string> = {
  blocking: 'bg-red-100 text-red-700 border-red-200',
  relevant: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  related:  'bg-blue-100 text-blue-700 border-blue-200',
};

export function PaperCard({ paper, animationIndex = 0 }: PaperCardProps) {
  const [expanded, setExpanded] = useState(false);
  const analysis = paper.analysis;
  const classification = analysis?.classification ?? 'unknown';
  const badgeColor = classificationColors[classification] ?? 'bg-gray-100 text-gray-600 border-gray-200';

  const similarities = analysis?.similarities ?? [];
  const differences = analysis?.differences ?? [];
  const analysisText = analysis?.analysis;
  const hasDetails = similarities.length > 0 || differences.length > 0 || !!analysisText;

  return (
    <div
      className="bg-white rounded-lg border border-gray-200 shadow-sm p-5 animate-fade-in-up"
      style={{ animationDelay: `${animationIndex * 60}ms`, animationFillMode: 'both' }}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h3 className="font-medium text-gray-800 text-sm leading-snug">
            {paper.title || 'Untitled Paper'}
          </h3>
          {paper.publication_info && (
            <p className="text-xs text-gray-400 mt-0.5">{paper.publication_info}</p>
          )}
        </div>
        {analysis && (
          <span className={`shrink-0 px-2 py-0.5 text-xs font-medium rounded border ${badgeColor}`}>
            {classification}
          </span>
        )}
      </div>

      {paper.abstract && (
        <p className="text-sm text-gray-600 mb-3 line-clamp-3">{paper.abstract}</p>
      )}

      {analysis && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Relevance</span>
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-purple-500 rounded-full"
                style={{ width: `${(analysis.relevance_score ?? 0) * 100}%` }}
              />
            </div>
            <span className="text-xs text-gray-500">
              {((analysis.relevance_score ?? 0) * 100).toFixed(0)}%
            </span>
          </div>

          {hasDetails && (
            <div className="mt-2">
              <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between px-3 py-2 text-left bg-gray-50 hover:bg-gray-100 rounded-md transition-colors"
              >
                <span className="text-xs font-medium text-gray-600">Detailed Analysis</span>
                <svg
                  className={`w-4 h-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {expanded && (
                <div className="mt-2 space-y-3 px-1">
                  {similarities.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-gray-500 mb-1">Similarities</p>
                      <ul className="text-xs text-gray-600 space-y-1">
                        {similarities.map((item, i) => (
                          <li key={i} className="flex gap-1.5">
                            <span className="text-green-500 shrink-0">&#8226;</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {differences.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-gray-500 mb-1">Differences</p>
                      <ul className="text-xs text-gray-600 space-y-1">
                        {differences.map((item, i) => (
                          <li key={i} className="flex gap-1.5">
                            <span className="text-red-400 shrink-0">&#8226;</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {analysisText && (
                    <div>
                      <p className="text-xs font-medium text-gray-500 mb-1">Analysis</p>
                      <p className="text-xs text-gray-600 leading-relaxed">{analysisText}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400">
        {paper.doi && <span>DOI: {paper.doi}</span>}
        {paper.url && (
          <a href={paper.url} target="_blank" rel="noopener noreferrer"
            className="text-purple-500 hover:text-purple-600 ml-auto">
            View Paper
          </a>
        )}
      </div>
    </div>
  );
}
