import type { Patent } from '../types';

interface PatentCardProps {
  patent: Patent;
}

const classificationColors: Record<string, string> = {
  blocking: 'bg-red-100 text-red-700 border-red-200',
  relevant: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  related: 'bg-blue-100 text-blue-700 border-blue-200',
};

export function PatentCard({ patent }: PatentCardProps) {
  const analysis = patent.analysis;
  const classification = analysis?.classification ?? 'unknown';
  const badgeColor = classificationColors[classification] ?? 'bg-gray-100 text-gray-600 border-gray-200';

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-5">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <h3 className="font-medium text-gray-800 text-sm leading-snug">
            {patent.title || 'Untitled Patent'}
          </h3>
          <p className="text-xs text-gray-400 mt-0.5">{patent.patent_number}</p>
        </div>
        {analysis && (
          <span className={`shrink-0 px-2 py-0.5 text-xs font-medium rounded border ${badgeColor}`}>
            {classification}
          </span>
        )}
      </div>

      {patent.abstract && (
        <p className="text-sm text-gray-600 mb-3 line-clamp-3">{patent.abstract}</p>
      )}

      {analysis && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Relevance</span>
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full"
                style={{ width: `${(analysis.relevance_score ?? 0) * 100}%` }}
              />
            </div>
            <span className="text-xs text-gray-500">
              {((analysis.relevance_score ?? 0) * 100).toFixed(0)}%
            </span>
          </div>

          {analysis.overlap_areas && analysis.overlap_areas.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Overlap Areas</p>
              <div className="flex flex-wrap gap-1">
                {analysis.overlap_areas.map((area, i) => (
                  <span key={i} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                    {area}
                  </span>
                ))}
              </div>
            </div>
          )}

          {analysis.key_differences && analysis.key_differences.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Key Differences</p>
              <ul className="text-xs text-gray-600 space-y-0.5">
                {analysis.key_differences.map((diff, i) => (
                  <li key={i}>- {diff}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400">
        {patent.filing_date && <span>Filed: {patent.filing_date}</span>}
        {patent.assignee && <span>Assignee: {patent.assignee}</span>}
        {patent.url && (
          <a href={patent.url} target="_blank" rel="noopener noreferrer"
            className="text-blue-500 hover:text-blue-600 ml-auto">
            View Patent
          </a>
        )}
      </div>
    </div>
  );
}
