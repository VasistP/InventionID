import { useState } from 'react';

interface QueryCountsPanelProps {
  queryCounts: Record<string, number>;
}

function calibrationLabel(n: number): { label: string; color: string } {
  if (n > 100_000) return { label: 'Too broad', color: 'text-red-600' };
  if (n > 10_000)  return { label: 'Getting closer', color: 'text-orange-500' };
  if (n > 1_000)   return { label: 'Close', color: 'text-yellow-600' };
  if (n > 100)     return { label: 'Dialed in', color: 'text-green-600' };
  if (n > 10)      return { label: 'Very specific', color: 'text-green-700' };
  return            { label: 'Too specific', color: 'text-orange-500' };
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

export function QueryCountsPanel({ queryCounts }: QueryCountsPanelProps) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(queryCounts);
  if (!entries.length) return null;

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left transition-colors"
      >
        <span className="text-sm font-medium text-gray-700">
          Search Query Calibration ({entries.length} queries)
        </span>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="divide-y divide-gray-100">
          {entries.map(([query, count], i) => {
            const { label, color } = calibrationLabel(count);
            return (
              <div key={i} className="px-4 py-2.5 flex items-start gap-3">
                <span className="shrink-0 text-xs font-mono text-gray-400 w-5 text-right mt-0.5">
                  {i + 1}
                </span>
                <span className="flex-1 text-xs text-gray-700 font-mono leading-relaxed">
                  {query}
                </span>
                <div className="shrink-0 flex items-center gap-1.5 mt-0.5">
                  <span className={`text-xs font-semibold ${color}`}>
                    {count > 0 ? formatCount(count) : '—'}
                  </span>
                  {count > 0 && (
                    <span className={`text-xs ${color}`}>· {label}</span>
                  )}
                </div>
              </div>
            );
          })}
          <div className="px-4 py-2 bg-gray-50">
            <p className="text-xs text-gray-400">
              Result counts from Google Patents. &gt;100K = too broad · &lt;100 = dialed in · &lt;10 = likely too specific
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
