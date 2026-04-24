"""
Full Patent Search Pipeline with Prompt-Cached Invention Agent

Drop-in replacement for full_pipeline_integrated_Pranav.py.
Key change: Stage 1 uses InventionExtractionAgentCached which
  - caches the entire document as a system prompt prefix (no chunking)
  - accumulates ReAct reasoning across iterations in multi-turn conversation
  - uses Claude prompt caching via the Bedrock API

All other stages (2-6) are identical to the original pipeline.
"""
import boto3
import json
import re
import time
import os
from datetime import datetime
from prompt_templates import PromptTemplates, get_invention_description
from invention_agent_cached import InventionExtractionAgentCached
from utils.parallel_search import parallel_search_queries
from utils.rate_limiter import BedrockRateLimiter, CircuitBreaker, invoke_bedrock_with_retry
from textractChunkingv2 import extract_text_from_s3_by_sections, normalize_textract_chunks
from pipeline_config import (
    MODEL_EXTRACTION, MODEL_QUERY_GEN, MODEL_ANALYSIS,
    NUM_SEARCH_QUERIES, MAX_RESULTS_PER_QUERY, MAX_SEARCH_CONCURRENT, SERPAPI_DELAY,
    MAX_PATENTS_TO_FETCH, MAX_PATENTS_TO_ANALYZE,
    AGENT_MAX_ITERATIONS,
    BEDROCK_MIN_INTERVAL, CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
)

BUCKET = "patent-pdf-input-786827631714"

# Lazy-initialized components (populated by _init_components())
bedrock: "boto3.client" = None  # type: ignore[assignment]
s3: "boto3.client" = None  # type: ignore[assignment]
patent_searcher: "PatentSearcher" = None  # type: ignore[assignment]
rate_limiter: "BedrockRateLimiter" = None  # type: ignore[assignment]
circuit_breaker: "CircuitBreaker" = None  # type: ignore[assignment]
invention_agent: "InventionExtractionAgentCached" = None  # type: ignore[assignment]
_initialized = False


def _init_components():
    """Initialize all clients and shared components on first use."""
    global bedrock, s3, patent_searcher, rate_limiter, circuit_breaker, invention_agent, _initialized
    if _initialized:
        return
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-2')
    s3 = boto3.client('s3')

    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        print("WARNING: SERPAPI_KEY not set. Set with: export SERPAPI_KEY='your_key'")

    patent_searcher = PatentSearcher(api_key=serpapi_key, delay=SERPAPI_DELAY)
    rate_limiter = BedrockRateLimiter(min_interval=BEDROCK_MIN_INTERVAL)
    circuit_breaker = CircuitBreaker(failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD, recovery_timeout=CIRCUIT_BREAKER_RECOVERY_TIMEOUT)
    invention_agent = InventionExtractionAgentCached(
        bedrock, MODEL_EXTRACTION, max_iterations=AGENT_MAX_ITERATIONS,
        rate_limiter=rate_limiter, circuit_breaker=circuit_breaker,
    )
    _initialized = True


# ============================================================
# PATENT SEARCHER (SerpAPI) 
# ============================================================

class PatentSearcher:
    """Search Google Patents via SerpAPI"""

    def __init__(self, api_key: str, delay=0.5):
        self.api_key = api_key
        self.delay = delay
        try:
            from serpapi import GoogleSearch
            self.GoogleSearch = GoogleSearch
        except ImportError:
            print("ERROR: serpapi not installed. Run: pip install google-search-results --break-system-packages")
            self.GoogleSearch = None

    def search(self, query: str, max_results: int = 10) -> list:
        if not self.GoogleSearch:
            return []
        try:
            params = {
                "engine": "google_patents",
                "q": query,
                "api_key": self.api_key,
            }
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            results = search.get_dict()
            return self._parse_results(results, max_results)
        except Exception as e:
            print(f"    SerpAPI error: {e}")
            return []

    def _extract_patent_number(self, patent_id: str) -> str:
        if not patent_id:
            return ""
        parts = patent_id.split("/")
        if len(parts) >= 2:
            return parts[1] if parts[0] == "patent" else parts[0]
        return patent_id

    def _parse_results(self, data: dict, max_results: int) -> list:
        patents = []
        for result in data.get("organic_results", [])[:max_results]:
            patent_id = result.get("patent_id", "")
            patent_number = self._extract_patent_number(patent_id)
            patent = {
                "patent_number": patent_number,
                "title": result.get("title", ""),
                "url": f"https://patents.google.com/{patent_id}" if patent_id else "",
                "abstract": result.get("snippet", ""),
                "filing_date": result.get("filing_date", ""),
                "publication_date": result.get("publication_date", ""),
                "grant_date": result.get("grant_date", ""),
                "inventors": result.get("inventor", ""),
                "assignee": result.get("assignee", ""),
            }
            if patent_number:
                patents.append(patent)
        return patents

    def get_patent_details(self, patent_number: str) -> dict:
        if not self.GoogleSearch:
            return {"patent_number": patent_number, "error": "serpapi not installed"}
        try:
            params = {
                "engine": "google_patents",
                "q": f"patent/{patent_number}/en",
                "api_key": self.api_key
            }
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            data = search.get_dict()
            results = data.get("organic_results", [])
            if results:
                r = results[0]
                patent_id = r.get("patent_id", "")
                return {
                    "patent_number": self._extract_patent_number(patent_id) or patent_number,
                    "title": r.get("title", ""),
                    "abstract": r.get("snippet", ""),
                    "url": f"https://patents.google.com/{patent_id}" if patent_id else "",
                    "filing_date": r.get("filing_date", ""),
                    "publication_date": r.get("publication_date", ""),
                    "inventors": r.get("inventor", ""),
                    "assignee": r.get("assignee", ""),
                    "claim_1": ""
                }
            return {"patent_number": patent_number, "error": "Not found"}
        except Exception as e:
            print(f"    SerpAPI error for {patent_number}: {e}")
            return {"patent_number": patent_number, "error": str(e)}


# ============================================================
# LLM CALL FUNCTIONS
# ============================================================


class JsonParseExhaustedError(Exception):
    """Raised when all JSON-parse retry attempts are exhausted."""
    pass


def parse_json(text):
    """Extract JSON from LLM response."""
    try:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return json.loads(match.group(1))
        match = re.search(r'[\[{].*[\]}]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def call_bedrock_json(prompt, max_tokens=4000, model_id=MODEL_ANALYSIS, max_parse_retries=3):
    """
    Call Bedrock and parse the response as JSON.

    If parsing fails, sends a follow-up message asking the LLM to fix its
    output, up to `max_parse_retries` attempts. Raises JsonParseExhaustedError
    if all attempts fail.
    """
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, max_parse_retries + 1):
        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": messages,
        })
        result = invoke_bedrock_with_retry(
            bedrock,
            model_id=model_id,
            body=request_body,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
        )
        content = result.get('content')
        if not content or not isinstance(content, list) or not content[0].get('text'):
            raise RuntimeError(f"Bedrock returned unexpected response structure: {result!r:.500}")
        response_text = content[0]['text']

        parsed = parse_json(response_text)
        if parsed is not None:
            return parsed

        print(f"  JSON parse failed (attempt {attempt}/{max_parse_retries}), requesting fix...")

        # Build a multi-turn conversation so the LLM sees its bad output
        messages.append({"role": "assistant", "content": response_text})
        messages.append({
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "Return ONLY a valid JSON object or array — no markdown "
                "fences, no commentary, no text before or after the JSON."
            ),
        })

    raise JsonParseExhaustedError(
        f"Failed to get valid JSON after {max_parse_retries} attempts"
    )



# ============================================================
# PIPELINE STAGES
# ============================================================

def stage_1_extract_invention(sections):
    """Stage 1: Extract invention using cached ReAct agent (section-wise chunks)"""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION (ReAct Agent + Prompt Caching)")
    print("="*60)

    result = invention_agent.run(sections)

    # Save agent logs locally
    log_file = invention_agent.save_logs()
    print(f"  Agent logs saved: {log_file}")

    if result["success"]:
        invention = result["invention"]
        patentability = result.get("patentability")
        return {"1": invention}, log_file, patentability

    return None, log_file, None


def stage_2_generate_queries(invention):
    """Stage 2: Generate search queries (using Sonnet)"""
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)

    prompt = PromptTemplates.generate_search_queries(invention, num_queries=NUM_SEARCH_QUERIES)
    print(prompt)
    queries = call_bedrock_json(prompt, max_tokens=500, model_id=MODEL_QUERY_GEN)

    if queries:
        print(f"  Generated {len(queries)} queries:")
        for q in queries:
            print(f"    - {q}")

    return queries or []


def stage_3_search_patents(queries, max_concurrent: int = MAX_SEARCH_CONCURRENT):
    """Stage 3: Search patents via SerpAPI (parallel)."""
    print("\n" + "="*60)
    print("STAGE 3: PATENT SEARCH (SerpAPI, parallel)")
    print("="*60)

    target_queries = queries
    all_patents = []
    seen = set()

    results_by_query = parallel_search_queries(
        patent_searcher,
        target_queries,
        max_results_per_query=MAX_RESULTS_PER_QUERY,
        max_concurrent=max_concurrent,
    )

    for query, results in results_by_query:
        print(f"  Merging results for: {query!r}")
        for p in results:
            num = p.get("patent_number", "")
            if num and num not in seen:
                seen.add(num)
                all_patents.append(p)

    print(f"  Total unique patents: {len(all_patents)}")
    return all_patents


def stage_4_fetch_details(patents, max_concurrent: int = MAX_SEARCH_CONCURRENT):
    """Stage 4: Fetch patent details (parallel)"""
    print("\n" + "="*60)
    print("STAGE 4: FETCH PATENT DETAILS (parallel)")
    print("="*60)

    if not patents:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = patents[:MAX_PATENTS_TO_FETCH]
    cached = []
    to_fetch = []

    for p in candidates:
        patent_num = p.get('patent_number', '')
        if p.get('abstract') and len(p.get('abstract', '')) > 50:
            print(f"  Using cached: {patent_num}")
            cached.append(p)
        elif patent_num:
            to_fetch.append(p)

    def fetch_one(p):
        patent_num = p.get('patent_number', '')
        print(f"  Fetching: {patent_num}")
        try:
            details = patent_searcher.get_patent_details(patent_num)
            return {**p, **details}
        except Exception as e:
            print(f"  Fetch error for {patent_num}: {e}")
            return p

    fetched = []
    if to_fetch:
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_patent = {executor.submit(fetch_one, p): p for p in to_fetch}
            for future in as_completed(future_to_patent):
                fetched.append(future.result())

    # Preserve original order
    fetched_map = {p.get('patent_number', ''): p for p in fetched}
    detailed_patents = []
    for p in candidates:
        patent_num = p.get('patent_number', '')
        if patent_num in fetched_map:
            detailed_patents.append(fetched_map[patent_num])
        else:
            detailed_patents.append(p)

    print(f"  Got details for {len(detailed_patents)} patents")
    return detailed_patents


def stage_5_analyze_patents(invention, patents):
    """Stage 5: Analyze patents (using Opus)"""
    print("\n" + "="*60)
    print("STAGE 5: PATENT ANALYSIS (Opus)")
    print("="*60)

    if not patents:
        return []

    inv_desc = get_invention_description(invention)
    prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:MAX_PATENTS_TO_ANALYZE])
    analysis = call_bedrock_json(prompt, max_tokens=3000, model_id=MODEL_ANALYSIS)

    if analysis:
        print(f"  Analyzed {len(analysis)} patents:")
        for a in analysis:
            print(f"    {a.get('patent_number')}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis or []


def stage_6_generate_report(invention, patents, analysis, patentability=None):
    """Stage 6: Generate final report"""
    print("\n" + "="*60)
    print("STAGE 6: FINAL REPORT")
    print("="*60)

    analysis_map = {a['patent_number']: a for a in analysis if a.get('patent_number')}

    results = []
    for p in patents:
        num = p.get('patent_number')
        result = {**p}
        if num in analysis_map:
            result['analysis'] = analysis_map[num]
        results.append(result)

    # Sort by classification priority then relevance_score descending
    _CLASSIFICATION_ORDER = {"blocking": 0, "relevant": 1, "related": 2}
    results.sort(key=lambda p: (
        _CLASSIFICATION_ORDER.get(p.get("analysis", {}).get("classification", "other"), 3),
        -(p.get("analysis", {}).get("relevance_score", 0))
    ))

    # Embed patentability assessment into invention
    invention_out = {**invention}
    if patentability:
        invention_out["patentability_assessment"] = patentability

    report = {
        "invention": invention_out,
        "patents_found": len(patents),
        "patents_analyzed": len(analysis),
        "blocking": len([a for a in analysis if a.get('classification') == 'blocking']),
        "relevant": len([a for a in analysis if a.get('classification') == 'relevant']),
        "related": len([a for a in analysis if a.get('classification') == 'related']),
        "patents": results
    }

    print(f"  Summary:")
    print(f"    Patents found: {report['patents_found']}")
    print(f"    Blocking: {report['blocking']}")
    print(f"    Relevant: {report['relevant']}")
    print(f"    Related: {report['related']}")

    return report


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline(bucket, pdf_key, max_pipeline_retries=2, progress_callback=None):
    """
    Run the pipeline with automatic restart on persistent JSON parse failures.

    If a stage exhausts all JSON-parse retries, the entire pipeline is
    restarted from scratch (up to `max_pipeline_retries` total attempts).

    Parameters
    ----------
    progress_callback : callable, optional
        If provided, called with a dict at each stage boundary:
        {"stage": int, "stage_name": str, "status": str, ...}
    """
    _init_components()
    for attempt in range(1, max_pipeline_retries + 1):
        try:
            if attempt > 1:
                print(f"\n  RESTARTING PIPELINE (attempt {attempt}/{max_pipeline_retries})")
            return _run_pipeline_once(bucket, pdf_key, progress_callback=progress_callback)
        except JsonParseExhaustedError as e:
            print(f"\n  Pipeline attempt {attempt} failed: {e}")
            if attempt == max_pipeline_retries:
                print("  All pipeline retries exhausted.")
                return {"error": str(e)}
    return {"error": "Pipeline failed unexpectedly"}


def _run_pipeline_once(bucket, pdf_key, progress_callback=None):
    """Run complete pipeline (single attempt)."""
    def _emit(stage, stage_name, status="running", **extra):
        if progress_callback:
            progress_callback({"stage": stage, "stage_name": stage_name, "status": status, **extra})

    print("\n" + "#"*60)
    print("PATENT PRIOR ART SEARCH PIPELINE (Prompt-Cached)")
    print("#"*60)
    print(f"Input: s3://{bucket}/{pdf_key}")
    print(f"Models: Sonnet (agent w/ caching), Opus (analysis)")

    # Extract text as section-wise chunks using Textract Layout
    _emit(0, "Extracting text from PDF")
    print("  Starting Textract Layout extraction (section-wise)...")
    _t0 = time.time()
    chunks = extract_text_from_s3_by_sections(bucket, pdf_key)
    if not chunks:
        _emit(-1, "Textract extraction failed", status="error", error="Textract Layout extraction failed")
        return {"error": "Textract Layout extraction failed"}
    sections = normalize_textract_chunks(chunks)
    if not sections:
        _emit(-1, "No sections extracted", status="error", error="No sections extracted from document")
        return {"error": "No sections extracted from document"}
    print(f"  Extracted {len(sections)} sections")

    # Stage 1: Extract invention (cached ReAct agent — section-wise chunks)
    _emit(1, "Extracting invention details", detail=f"{len(sections)} sections")
    inventions, agent_log_file, patentability = stage_1_extract_invention(sections)
    print(f"  [TIMER] Stage 1 elapsed: {time.time() - _t0:.1f}s")

    if not inventions:
        _emit(-1, "No inventions found", status="error", error="No inventions found")
        return {"error": "No inventions found"}

    invention = list(inventions.values())[0]

    queries = []
    patents = []
    detailed = []
    analysis = []

    # Stage 2: Generate queries
    _emit(2, "Generating search queries")
    try:
        queries = stage_2_generate_queries(invention)
    except JsonParseExhaustedError:
        raise  # let pipeline retry wrapper handle it
    except Exception as e:
        print(f"  Stage 2 failed: {e}")

    if not queries:
        print("  WARNING: No search queries generated — skipping patent search stages")
    else:
        # exit()
        # Stage 3: Search patents
        _emit(3, "Searching patents", detail=f"{len(queries)} queries")
        try:
            patents = stage_3_search_patents(queries)
            for p in patents:
                print(f"  {p.get('patent_number', 'N/A')}: {p.get('title', 'N/A')}")
        except Exception as e:
            print(f"  Stage 3 failed: {e}")

        if not patents:
            print("  WARNING: No patents found — skipping analysis stages")
        else:
            # Stage 4: Fetch details
            exit()
            _emit(4, "Fetching patent details", detail=f"{len(patents)} patents")
            try:
                detailed = stage_4_fetch_details(patents)
            except Exception as e:
                print(f"  Stage 4 failed: {e}")
                detailed = patents  # fall back to basic patent info

            # Stage 5: Analyze
            _emit(5, "Analyzing patents", detail=f"{len(detailed)} patents")
            try:
                analysis = stage_5_analyze_patents(invention, detailed)
            except JsonParseExhaustedError:
                raise  # let pipeline retry wrapper handle it
            except Exception as e:
                print(f"  Stage 5 failed: {e}")

    # Stage 6: Report (always runs — produces partial report with whatever we have)
    _emit(6, "Generating final report")
    report = stage_6_generate_report(invention, detailed or patents, analysis, patentability=patentability)

    # Attach run metadata
    report["run_metadata"] = {
        "pipeline_version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "models": {
            "extraction": MODEL_EXTRACTION,
            "query_generation": MODEL_QUERY_GEN,
            "patent_analysis": MODEL_ANALYSIS,
        },
        "retrieval_config": {
            "max_patents_fetched": MAX_PATENTS_TO_FETCH,
            "max_patents_analyzed": MAX_PATENTS_TO_ANALYZE,
            "max_search_queries": NUM_SEARCH_QUERIES,
        },
    }

    # Save to S3
    output_key = pdf_key.replace('input/', 'results/').replace('.pdf', '_report.json')
    try:
        s3.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=json.dumps(report, indent=2),
            ContentType='application/json'
        )
        print(f"\nReport saved: s3://{bucket}/{output_key}")
    except Exception as e:
        print(f"  Failed to save report to S3: {e}")

    # Upload agent logs to S3
    log_key = pdf_key.replace('input/', 'logs/').replace('.pdf', '_agent_logs.json')
    try:
        with open(agent_log_file, 'r') as f:
            log_content = f.read()
        s3.put_object(
            Bucket=bucket,
            Key=log_key,
            Body=log_content,
            ContentType='application/json'
        )
        print(f"Agent logs saved: s3://{bucket}/{log_key}")
    except Exception as e:
        print(f"  Failed to save agent logs to S3: {e}")

    _emit(7, "Complete", status="completed", result_key=output_key)
    return report


if __name__ == "__main__":
    import sys

    _init_components()
    if len(sys.argv) < 2:
        print("Available PDFs in S3:")
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix='input/')
        for obj in response.get('Contents', []):
            print(f"  {obj['Key']}")
        print(f"\nUsage: python3 full_pipeline_cached.py <pdf_key>")
    else:
        pdf_key = sys.argv[1]
        report = run_pipeline(BUCKET, pdf_key)
        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
