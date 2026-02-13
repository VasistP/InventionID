import { useState, useRef, type DragEvent } from 'react';

interface UploadAreaProps {
  onUpload: (file: File) => void;
  disabled?: boolean;
}

export function UploadArea({ onUpload, disabled }: UploadAreaProps) {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file?.name.toLowerCase().endsWith('.pdf')) {
      setSelectedFile(file);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) setSelectedFile(file);
  }

  function handleSubmit() {
    if (selectedFile && !disabled) {
      onUpload(selectedFile);
      setSelectedFile(null);
    }
  }

  return (
    <div className="flex flex-col items-center justify-center h-full max-w-xl mx-auto">
      <h2 className="text-2xl font-semibold text-gray-800 mb-2">Patent Prior Art Analysis</h2>
      <p className="text-gray-500 mb-8 text-center">
        Upload a research paper or patent document (PDF) to analyze for prior art and patentability.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`w-full border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-colors ${
          dragOver
            ? 'border-blue-400 bg-blue-50'
            : 'border-gray-300 hover:border-gray-400 bg-white'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          onChange={handleFileSelect}
          className="hidden"
        />
        <div className="text-gray-400 mb-2">
          <svg className="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
        </div>
        <p className="text-gray-600 font-medium">
          {selectedFile ? selectedFile.name : 'Drop a PDF here or click to browse'}
        </p>
        {selectedFile && (
          <p className="text-sm text-gray-400 mt-1">
            {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
          </p>
        )}
      </div>

      {selectedFile && (
        <button
          onClick={handleSubmit}
          disabled={disabled}
          className="mt-6 px-8 py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-400 text-white rounded-lg font-medium transition-colors"
        >
          Analyze Document
        </button>
      )}
    </div>
  );
}
