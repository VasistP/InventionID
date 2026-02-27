export interface ProgressMessage {
  stage: number;
  stage_name: string;
  status: 'running' | 'completed' | 'error';
  error?: string;
  result_key?: string;
  detail?: string;
  duration_seconds?: number;
}

export interface PatentAnalysis {
  patent_number: string;
  classification: string;
  relevance_score: number;
  overlap_areas?: string[];
  key_differences?: string[];
  similarities?: string[];
  differences?: string[];
  analysis?: string;
  risk_level?: string;
}

export interface Patent {
  patent_number: string;
  title: string;
  abstract: string;
  url: string;
  filing_date: string;
  inventors: string;
  assignee: string;
  analysis?: PatentAnalysis;
}

export interface Invention {
  invention_name: string;
  technical_description: string;
  problem_statement: string;
  solution_approach: string;
  key_technical_features: string[];
  domain_classification: string;
  statutory_category: string;
  inventor_keywords: string[];
}

export interface PipelineReport {
  invention: Invention;
  patents_found: number;
  patents_analyzed: number;
  blocking: number;
  relevant: number;
  related: number;
  patents: Patent[];
}

export interface AnalysisSession {
  id: string;
  filename: string;
  s3Key: string;
  startedAt: Date;
  status: 'uploading' | 'running' | 'completed' | 'error';
  progress: ProgressMessage[];
  report?: PipelineReport;
  resultKey?: string;
  error?: string;
  durationSeconds?: number;
}

export const STAGE_LABELS: Record<number, string> = {
  0: 'Extracting text from PDF',
  1: 'Extracting invention details',
  2: 'Generating search queries',
  3: 'Searching patents',
  4: 'Fetching patent details',
  5: 'Analyzing patents',
  6: 'Generating final report',
  7: 'Complete',
};

export const TOTAL_STAGES = 7;
