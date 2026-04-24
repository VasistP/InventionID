import { useState } from 'react';
import type { ConceptMap } from '../types';

const GROUP_COLORS: Record<string, string> = {
  'Materials/Components':   'bg-blue-50 text-blue-700 border-blue-200',
  'Structure/Architecture': 'bg-purple-50 text-purple-700 border-purple-200',
  'Process/Method':         'bg-orange-50 text-orange-700 border-orange-200',
  'Properties/Function':    'bg-green-50 text-green-700 border-green-200',
  'Problem/Field':          'bg-gray-50 text-gray-600 border-gray-200',
};

const SPECIFICITY_STYLES: Record<string, string> = {
  'Well-placed':  'bg-green-50 text-green-700 border-green-200',
  'Too Specific': 'bg-orange-50 text-orange-600 border-orange-200',
  'Too Generic':  'bg-gray-100 text-gray-500 border-gray-200',
};

function groupColor(group: string): string {
  return GROUP_COLORS[group] ?? 'bg-gray-50 text-gray-600 border-gray-200';
}

interface ConceptMapPanelProps {
  conceptMap: ConceptMap;
}

export function ConceptMapPanel({ conceptMap }: ConceptMapPanelProps) {
  const [open, setOpen] = useState(false);
  const concepts = conceptMap.concepts ?? [];
  const anchors = conceptMap.top_3_anchors ?? [];
  if (!concepts.length && !conceptMap.statutory_category) return null;

  const wellPlaced = concepts.filter(c => c.specificity === 'Well-placed').length;

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left transition-colors"
      >
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-700">Concept Map</span>
          {conceptMap.statutory_category && (
            <span className="px-1.5 py-0.5 text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200 rounded">
              {conceptMap.statutory_category}
            </span>
          )}
          <span className="text-xs text-gray-400">
            {concepts.length} concepts · {wellPlaced} well-placed · {anchors.length} anchors
          </span>
        </div>
        <svg
          className={`w-4 h-4 text-gray-400 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="px-4 py-3 space-y-4">
          {/* WHAT / HOW axes */}
          {(conceptMap.what_axis || conceptMap.how_axis) && (
            <div className="space-y-1.5">
              {conceptMap.what_axis && (
                <div className="flex gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-gray-500 w-12">WHAT</span>
                  <span className="text-gray-700">{conceptMap.what_axis}</span>
                </div>
              )}
              {conceptMap.how_axis && (
                <div className="flex gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-gray-500 w-12">HOW</span>
                  <span className="text-gray-700">{conceptMap.how_axis}</span>
                </div>
              )}
            </div>
          )}

          {/* Novelty / Known */}
          {(conceptMap.novelty_focus || conceptMap.known_aspects) && (
            <div className="space-y-1 border-t border-gray-100 pt-3">
              {conceptMap.novelty_focus && (
                <div className="flex gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-green-600 w-12">Novel</span>
                  <span className="text-gray-700">{conceptMap.novelty_focus}</span>
                </div>
              )}
              {conceptMap.known_aspects && (
                <div className="flex gap-2 text-xs">
                  <span className="shrink-0 font-semibold text-gray-400 w-12">Known</span>
                  <span className="text-gray-500">{conceptMap.known_aspects}</span>
                </div>
              )}
            </div>
          )}

          {/* Top-3 anchors */}
          {anchors.length > 0 && (
            <div className="border-t border-gray-100 pt-3">
              <p className="text-xs font-medium text-gray-500 mb-2">Top-3 Anchor Keywords</p>
              <div className="flex flex-wrap gap-2">
                {anchors.map((a, i) => (
                  <div key={i} className="group relative">
                    <span className="px-2 py-1 text-xs font-semibold bg-indigo-100 text-indigo-800 rounded-full border border-indigo-200 font-mono cursor-default">
                      {i + 1}. {a.term}
                    </span>
                    <div className="absolute bottom-full mb-1 left-0 hidden group-hover:block bg-gray-800 text-white text-xs rounded px-2 py-1 w-48 z-10 whitespace-normal">
                      {a.reason}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Concepts table */}
          {concepts.length > 0 && (
            <div className="border-t border-gray-100 pt-3">
              <p className="text-xs font-medium text-gray-500 mb-2">Extracted Concepts</p>
              <div className="space-y-2">
                {concepts.map((c, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className={`shrink-0 px-1.5 py-0.5 text-xs rounded border ${groupColor(c.group)}`}>
                      {c.group}
                    </span>
                    {c.specificity && (
                      <span className={`shrink-0 px-1.5 py-0.5 text-xs rounded border ${SPECIFICITY_STYLES[c.specificity] ?? 'bg-gray-50 text-gray-500 border-gray-200'}`}>
                        {c.specificity}
                      </span>
                    )}
                    <div className="flex-1 flex flex-wrap gap-1 items-center min-w-0">
                      <span className="text-xs font-semibold text-gray-700">{c.name}</span>
                      {c.drafter_synonym && (
                        <span className="text-xs px-1.5 py-0.5 bg-indigo-50 text-indigo-700 rounded border border-indigo-100 font-mono" title="Patent-drafter synonym">
                          ≈ {c.drafter_synonym}
                        </span>
                      )}
                      {c.synonyms.length > 0 && (
                        <>
                          <span className="text-xs text-gray-300">→</span>
                          {c.synonyms.map((s, j) => (
                            <span key={j} className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded font-mono">
                              {s}
                            </span>
                          ))}
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
