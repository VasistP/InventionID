import type { PipelineReport } from '../types';

interface SummaryHeaderProps {
  report: PipelineReport;
}

function Badge({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className={`px-3 py-1.5 rounded-full text-sm font-medium ${color}`}>
      {count} {label}
    </div>
  );
}

export function SummaryHeader({ report }: SummaryHeaderProps) {
  const { invention, patents_found, patents_analyzed, blocking, relevant, related } = report;

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-6">
      <h2 className="text-xl font-semibold text-gray-800 mb-1">
        {invention.invention_name}
      </h2>
      <p className="text-sm text-gray-500 mb-1">{invention.domain_classification}</p>
      <p className="text-sm text-gray-500 mb-4">{invention.statutory_category}</p>

      <p className="text-gray-600 text-sm mb-4 leading-relaxed">
        {invention.technical_description}
      </p>

      {invention.key_technical_features && invention.key_technical_features.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Key Technical Features</h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            {invention.key_technical_features.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-6 pt-4 border-t border-gray-100">
        <div className="text-sm text-gray-500">
          <span className="font-medium text-gray-700">{patents_found}</span> found
        </div>
        <div className="text-sm text-gray-500">
          <span className="font-medium text-gray-700">{patents_analyzed}</span> analyzed
        </div>
        <div className="flex gap-2">
          {blocking > 0 && <Badge label="blocking" count={blocking} color="bg-red-100 text-red-700" />}
          {relevant > 0 && <Badge label="relevant" count={relevant} color="bg-yellow-100 text-yellow-700" />}
          {related > 0 && <Badge label="related" count={related} color="bg-blue-100 text-blue-700" />}
        </div>
      </div>
    </div>
  );
}
