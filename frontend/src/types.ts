export interface ProgressMessage {
  stage: number;
  stage_name: string;
  status: 'running' | 'completed' | 'error';
  error?: string;
  result_key?: string;
  detail?: string;
  duration_seconds?: number;
}

export interface PatentabilityFacet {
  facet_id: string;
  facet_name: string;
  score: number;
  reasoning: string;
  evidence_quote?: string;
}

export interface PatentabilityAssessment {
  classification: string;
  total_score: number;
  facets_detail: PatentabilityFacet[];
  justification: string;
  recommendation: string;
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
  evidence_snippet?: string;
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
  patentability_assessment?: PatentabilityAssessment;
}

export interface AnchorEntry {
  term: string;
  reason: string;
}

export interface ConceptEntry {
  name: string;
  group: string;
  specificity?: 'Too Specific' | 'Well-placed' | 'Too Generic';
  drafter_synonym?: string;
  synonyms: string[];
}

export interface ConceptMap {
  statutory_category?: string;
  what_axis?: string;
  how_axis?: string | null;
  concepts?: ConceptEntry[];
  top_3_anchors?: AnchorEntry[];
  novelty_focus?: string;
  known_aspects?: string;
}

export interface RunMetadata {
  pipeline_version: string;
  timestamp: string;
  models: Record<string, string>;
  retrieval_config: Record<string, number>;
  query_counts?: Record<string, number>;
  concept_map?: ConceptMap;
}

export interface ScholarPaperAnalysis {
  title: string;
  classification: string;
  relevance_score: number;
  similarities?: string[];
  differences?: string[];
  analysis?: string;
}

export interface ScholarPaper {
  title: string;
  url: string;
  publication_info: string;
  abstract: string;
  doi?: string;
  analysis?: ScholarPaperAnalysis;
}

export interface UserInputAnalysis {
  user_invention_input: string;
  verdict: 'is_invention' | 'not_invention' | 'partial_invention';
  reasoning: string;
  alignment: string;
  gaps: string[];
  recommendation: string;
}

export interface PipelineReport {
  invention: Invention;
  patents_found: number;
  patents_analyzed: number;
  blocking: number;
  relevant: number;
  related: number;
  patents: Patent[];
  scholar_papers_found?: number;
  scholar_papers_analyzed?: number;
  scholar_papers?: ScholarPaper[];
  run_metadata?: RunMetadata;
  user_input_analysis?: UserInputAnalysis;
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
  isRerun?: boolean;
  originalResultKey?: string;
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
