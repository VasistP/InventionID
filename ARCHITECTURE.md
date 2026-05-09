# Patent Agent — Architecture Review

## Overview

The patent agent is an end-to-end pipeline that ingests a PDF from S3, extracts a structured invention description using a ReAct-based LLM agent, searches for prior art (patents + academic papers), analyzes each result for relevance, and produces a final JSON report saved back to S3.

The system is designed around three cross-cutting concerns:
- **Correctness** — multi-turn self-correction with schema validation and independent judge scoring
- **Resilience** — rate limiting, circuit breaking, and exponential backoff on all Bedrock calls
- **Cost efficiency** — prompt caching (ephemeral cache blocks) to reuse the full document context across agent iterations

---

## Pipeline Stages

| Stage | Description | Model |
|-------|-------------|-------|
| 1 | Invention extraction (ReAct agent, up to 4 iterations) | Claude Sonnet (cached) |
| 2 | Search query generation (2-step scratchpad → queries) | Claude Sonnet |
| 3 | Patent + Scholar search (parallel SerpAPI calls) | — |
| 4 | Fetch patent details + paper abstracts (parallel) | — |
| 5 | Analyze patents + papers vs. invention | Claude Sonnet |
| 6 | Aggregate and generate final report | — |

---

## Component Diagram

```mermaid
graph TD
    subgraph Input
        S3_IN[S3 PDF\nbucket/key]
    end

    subgraph Extraction["Stage 1 — Invention Extraction (full_pipeline_cached + invention_agent_cached)"]
        TEXTRACT[textractChunkingv2\nPDF → section chunks]
        AGENT[InventionExtractionAgentCached\nReAct loop, max 4 iterations]
        SCHEMA[schema_validator\nrequired-field check]
        PAT_CLASS[patentability_classifier\n3-facet rubric A/B/C]
        JUDGE[judgeBot\nMeta Llama 3.1 70B\nindependent confidence]
        CONF[Confidence Calibration\n0.4 × self + 0.6 × judge]
    end

    subgraph QueryGen["Stage 2 — Query Generation (PromptTemplates)"]
        SCRATCHPAD[generate_concept_scratchpad\nWHAT/HOW axes, synonym chains]
        QUERY_BUILD[generate_queries_from_scratchpad\n7-15 queries, 3 tiers]
    end

    subgraph Search["Stage 3 — Parallel Search (parallel_search.py + PatentSearcher)"]
        PAT_SEARCH[parallel_search_queries\nThreadPoolExecutor\nGoogle Patents via SerpAPI]
        SCH_SEARCH[parallel_scholar_queries\nThreadPoolExecutor\nGoogle Scholar via SerpAPI]
    end

    subgraph Fetch["Stage 4 — Fetch Details (parallel)"]
        PAT_DETAIL[get_patent_details\nabstract, dates, inventors, assignee]
        SCH_ABSTRACT[fetch paper abstracts\nCrossref / Semantic Scholar fallback]
    end

    subgraph Analysis["Stage 5 — Analysis (PromptTemplates + Bedrock)"]
        PAT_ANALYZE[analyze_patents_batch\nrelevance score + blocking/relevant/related]
        SCH_ANALYZE[analyze scholar papers\nrelevance score + classification]
    end

    subgraph Report["Stage 6 — Report Generation"]
        MERGE[merge + sort results\nblocking → relevant → related]
        REPORT[JSON report\ninvention + prior art + metadata]
    end

    subgraph Output
        S3_REPORT[S3 results/\nJSON report]
        S3_LOGS[S3 logs/\nagent conversation logs]
    end

    subgraph Resilience["Cross-cutting — Resilience (utils/rate_limiter.py)"]
        RL[BedrockRateLimiter\nmin interval, slot reservation]
        CB[CircuitBreaker\nCLOSED → OPEN → HALF_OPEN]
        RETRY[invoke_bedrock_with_retry\nexponential backoff + jitter]
    end

    subgraph Config["Config & Templates"]
        CFG[pipeline_config.py\nmodels, limits, thresholds]
        TMPL[prompt_templates.py\nall LLM prompt builders]
    end

    %% Main data flow
    S3_IN --> TEXTRACT
    TEXTRACT --> AGENT
    AGENT --> SCHEMA
    SCHEMA -->|errors as tool observation| AGENT
    AGENT --> PAT_CLASS
    PAT_CLASS -->|facet scores| AGENT
    AGENT --> JUDGE
    JUDGE --> CONF
    CONF -->|confidence < 0.85 → refine| AGENT
    CONF -->|confident| SCRATCHPAD

    SCRATCHPAD --> QUERY_BUILD
    QUERY_BUILD --> PAT_SEARCH
    QUERY_BUILD --> SCH_SEARCH

    PAT_SEARCH --> PAT_DETAIL
    SCH_SEARCH --> SCH_ABSTRACT

    PAT_DETAIL --> PAT_ANALYZE
    SCH_ABSTRACT --> SCH_ANALYZE

    PAT_ANALYZE --> MERGE
    SCH_ANALYZE --> MERGE
    MERGE --> REPORT
    REPORT --> S3_REPORT
    AGENT -->|conversation history| S3_LOGS

    %% Resilience layer (all Bedrock calls route through)
    AGENT -.->|all Bedrock calls| RETRY
    PAT_ANALYZE -.->|all Bedrock calls| RETRY
    SCH_ANALYZE -.->|all Bedrock calls| RETRY
    QUERY_BUILD -.->|all Bedrock calls| RETRY
    RETRY --> RL
    RETRY --> CB

    %% Config wires into everything
    CFG -.-> AGENT
    CFG -.-> PAT_SEARCH
    CFG -.-> PAT_ANALYZE
    TMPL -.-> QUERY_BUILD
    TMPL -.-> PAT_ANALYZE
    TMPL -.-> SCH_ANALYZE
```

---

## Sequence Diagram — Invention Extraction (Stage 1)

```mermaid
sequenceDiagram
    participant P as full_pipeline_cached
    participant TX as textractChunkingv2
    participant A as InventionAgent
    participant B as Bedrock (Sonnet)
    participant SV as schema_validator
    participant PC as patentability_classifier
    participant J as judgeBot (Llama 3.1)

    P->>TX: extract_sections(s3_bucket, key)
    TX-->>P: section_chunks[]

    P->>A: run(section_chunks)
    Note over A: Cache full doc as ephemeral system block

    loop Up to 4 iterations
        A->>B: EXTRACT turn (cached context)
        B-->>A: invention JSON

        A->>SV: validate_schema(invention)
        SV-->>A: (is_valid, errors[])
        Note over A: Inject errors as tool observation

        A->>B: SCHEMA_VALIDATION turn
        B-->>A: corrected invention JSON

        A->>PC: build_patentability_prompt(invention)
        A->>B: PATENTABILITY_CHECK turn
        B-->>A: facet scores A/B/C + classification

        A->>B: VALIDATE turn (self-score)
        B-->>A: confidence 0.0–1.0

        alt confidence >= 0.85
            Note over A: Exit loop
        else confidence < 0.85
            A->>B: REFINE turn
            B-->>A: refined invention JSON
        end
    end

    A->>J: run_judge(invention)
    J-->>A: judge_confidence, rationales

    Note over A: final_conf = 0.4×self + 0.6×judge
    A-->>P: invention, confidence, agent_logs
```

---

## Sequence Diagram — Search & Analysis (Stages 2–6)

```mermaid
sequenceDiagram
    participant P as full_pipeline_cached
    participant B as Bedrock (Sonnet)
    participant SERP as SerpAPI
    participant EXT as External APIs

    P->>B: Stage 2 — generate_concept_scratchpad(invention)
    B-->>P: scratchpad (concepts, synonyms, axes)

    P->>B: Stage 2 — generate_queries_from_scratchpad(scratchpad)
    B-->>P: queries[] (7–15 queries, 3 tiers)

    par Stage 3a — Patent Search
        P->>SERP: parallel_search_queries(queries, max=5 workers)
        SERP-->>P: patent_results[]
    and Stage 3b — Scholar Search
        P->>SERP: parallel_scholar_queries(queries, max=5 workers)
        SERP-->>P: paper_results[]
    end

    par Stage 4a — Patent Detail Fetch
        P->>SERP: get_patent_details() for each patent
        SERP-->>P: enriched_patents[] (abstract, dates, inventors)
    and Stage 4b — Abstract Fetch
        P->>EXT: fetch abstracts (Crossref / Semantic Scholar)
        EXT-->>P: papers_with_abstracts[]
    end

    par Stage 5a — Analyze Patents
        P->>B: analyze_patents_batch(invention, patents[])
        B-->>P: scored_patents[] (relevance, blocking/relevant/related)
    and Stage 5b — Analyze Papers
        P->>B: analyze_scholar_papers(invention, papers[])
        B-->>P: scored_papers[] (relevance, classification)
    end

    P->>P: Stage 6 — merge + sort (blocking → relevant → related)
    P->>P: attach run metadata (models, config, timestamps)
    P->>P: save report + logs to S3
```

---

## Key Architectural Patterns

### 1. ReAct Loop with Prompt Caching
The invention agent maintains a multi-turn conversation where the full PDF is cached once as an ephemeral system block. Each iteration (extract → validate → patentability check → refine) reuses this cache, cutting token costs significantly across up to 4 loops.

### 2. Tool Observations as Conversation Turns
Schema validation errors and patentability classifier output are injected back into the multi-turn conversation as "tool observation" user turns. This lets the LLM see and self-correct its own failures without breaking the cached context.

### 3. Dual-Confidence Calibration
Self-reported confidence (from the agent's own VALIDATE turn) is blended with an independent judge score from Meta Llama 3.1 70B (run via Bedrock on a separate model). The weighted blend `0.4 × self + 0.6 × judge` prevents the agent from over-trusting its own output.

### 4. Parallel Fan-Out
Stages 3, 4, and 5 all use `ThreadPoolExecutor` to run patent and scholar pipelines concurrently, with configurable `max_concurrent` worker limits.

### 5. Layered Resilience
All Bedrock calls route through `invoke_bedrock_with_retry()`, which enforces:
- Minimum call interval (BedrockRateLimiter, slot reservation)
- Circuit breaker state machine (CLOSED → OPEN → HALF_OPEN)
- Exponential backoff with jitter on retryable errors

### 6. Config-Driven Thresholds
All limits (max iterations, confidence threshold, max patents to analyze, worker counts, model IDs) live in `pipeline_config.py`, keeping business logic separate from tunable parameters.

---

## Known Limitations

| Issue | Location | Status |
|-------|----------|--------|
| SerpAPI `before: 20220101` hardcoded date cutoff | `PatentSearcher.search()` | Unfixed — missing 3+ years of prior art |
| Greedy JSON regex `[\[{].*[\]}]` can overcapture | `full_pipeline_cached.py`, `invention_agent_cached.py` | Unfixed |
| Max 2 pipeline restart attempts on `JsonParseExhaustedError` | `full_pipeline_cached.py` | By design |
