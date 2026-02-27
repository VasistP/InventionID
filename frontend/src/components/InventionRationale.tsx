import { useState } from 'react';
import type { PatentabilityAssessment, PatentabilityFacet } from '../types';

interface InventionRationaleProps {
  assessment: PatentabilityAssessment;
}

function classificationStyle(classification: string): { badge: string; border: string } {
  const lower = classification.toLowerCase();
  if (lower.includes('potential') || lower.includes('patentable')) {
    return { badge: 'bg-green-100 text-green-800', border: 'border-green-200' };
  }
  if (lower.includes('borderline')) {
    return { badge: 'bg-yellow-100 text-yellow-800', border: 'border-yellow-200' };
  }
  return { badge: 'bg-red-100 text-red-800', border: 'border-red-200' };
}

function scoreDot(score: number) {
  if (score >= 2) return <span className="inline-block w-2 h-2 rounded-full bg-green-500 mt-1 shrink-0" />;
  if (score === 1) return <span className="inline-block w-2 h-2 rounded-full bg-yellow-500 mt-1 shrink-0" />;
  return <span className="inline-block w-2 h-2 rounded-full bg-red-400 mt-1 shrink-0" />;
}

function FacetRow({ facet }: { facet: PatentabilityFacet }) {
  return (
    <li className="flex gap-2 text-sm">
      {scoreDot(facet.score)}
      <div>
        <span className="font-medium text-gray-700">{facet.facet_name}</span>
        {facet.reasoning && (
          <p className="text-gray-500 mt-0.5">{facet.reasoning}</p>
        )}
        {facet.evidence_quote && (
          <blockquote className="mt-1 border-l-2 border-gray-300 pl-2 text-xs text-gray-400 italic">
            &ldquo;{facet.evidence_quote}&rdquo;
          </blockquote>
        )}
      </div>
    </li>
  );
}

export function InventionRationale({ assessment }: InventionRationaleProps) {
  const [open, setOpen] = useState(false);
  const style = classificationStyle(assessment.classification);

  const strongFacets = assessment.facets_detail.filter(f => f.score >= 1);
  const weakFacets = assessment.facets_detail.filter(f => f.score < 2);

  return (
    <div className={`rounded-lg border ${style.border} overflow-hidden`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-white hover:bg-gray-50 transition-colors text-left"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${style.badge}`}>
            {assessment.classification}
          </span>
          <span className="text-xs text-gray-500">
            Patentability assessment · {assessment.total_score}/6
          </span>
        </div>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 bg-white border-t border-gray-100 space-y-4">
          {strongFacets.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Why this may be an invention
              </p>
              <ul className="space-y-3">
                {strongFacets.map(f => <FacetRow key={f.facet_id} facet={f} />)}
              </ul>
            </div>
          )}

          {weakFacets.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Concerns
              </p>
              <ul className="space-y-3">
                {weakFacets.map(f => <FacetRow key={f.facet_id} facet={f} />)}
              </ul>
            </div>
          )}

          {assessment.justification && (
            <p className="text-xs text-gray-400 italic border-t border-gray-100 pt-3">
              {assessment.justification}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
