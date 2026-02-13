import type { AnalysisSession } from '../types';

interface SidebarProps {
  sessions: AnalysisSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

function StatusIcon({ status }: { status: AnalysisSession['status'] }) {
  switch (status) {
    case 'uploading':
    case 'running':
      return (
        <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
      );
    case 'completed':
      return <span className="inline-block w-2 h-2 rounded-full bg-green-400" />;
    case 'error':
      return <span className="inline-block w-2 h-2 rounded-full bg-red-400" />;
  }
}

export function Sidebar({ sessions, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <aside className="w-64 min-w-[16rem] bg-gray-900 text-gray-100 flex flex-col border-r border-gray-700">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-lg font-semibold mb-3">Patent Analysis</h1>
        <button
          onClick={onNew}
          className="w-full py-2 px-3 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium transition-colors"
        >
          + New Analysis
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        {sessions.length === 0 && (
          <p className="text-gray-500 text-sm text-center mt-8">No analyses yet</p>
        )}
        {sessions.map((session) => (
          <button
            key={session.id}
            onClick={() => onSelect(session.id)}
            className={`w-full text-left px-3 py-2 rounded mb-1 text-sm transition-colors ${
              session.id === activeId
                ? 'bg-gray-700 text-white'
                : 'hover:bg-gray-800 text-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <StatusIcon status={session.status} />
              <span className="truncate">{session.filename}</span>
            </div>
            <div className="text-xs text-gray-500 mt-0.5 ml-4">
              {session.startedAt.toLocaleTimeString()}
            </div>
          </button>
        ))}
      </nav>
    </aside>
  );
}
