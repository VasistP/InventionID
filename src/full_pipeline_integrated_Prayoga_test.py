"""
Full Patent Search Pipeline with RAG-based Invention Agent

Drop-in replacement for full_pipeline_cached.py.
Key changes:
  - Stage 0: Textract → Summarize → Embed sections
  - Stage 1: RAG agent with validate/refine/judge loop
  - Stages 2-6: Identical to full_pipeline_cached.py

Integrates: lazy init, rate-limiter, circuit breaker, JSON parse retry,
pipeline-level retry, progress callbacks, parallel patent detail fetching.
"""
import boto3
import json
import re
import time
import os
import copy
from datetime import datetime
from botocore.config import Config
from prompt_templates import PromptTemplates, get_invention_description
from invention_agent_cached import InventionExtractionAgentCached
from invention_agent_rag import InventionExtractionAgentRAG
from utils.rate_limiter import BedrockRateLimiter, CircuitBreaker, invoke_bedrock_with_retry
from parallel_search import parallel_search_queries, parallel_scholar_queries
from textractChunkingv2_Prayoga import extract_text_from_s3_by_sections, normalize_textract_chunks
from summarization import summarize_sections_parallel, add_embeddings_parallel

BUCKET = "patent-pdf-input-786827631714"

# Model IDs
MODEL_SONNET = "us.anthropic.claude-sonnet-4-6"
# MODEL_SONNET = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # For lightweight tasks (query gen)
# MODEL_OPUS = "us.anthropic.claude-opus-4-20250514-v1:0"        # For analysis
MODEL_OPUS = "us.anthropic.claude-opus-4-6-v1"

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
    bedrock = boto3.client(
        'bedrock-runtime',
        region_name='us-east-2',
        config=Config(max_pool_connections=10),
    )
    s3 = boto3.client('s3')

    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    if not serpapi_key:
        print("WARNING: SERPAPI_KEY not set. Set with: export SERPAPI_KEY='your_key'")

    patent_searcher = PatentSearcher(api_key=serpapi_key, delay=0.5)
    rate_limiter = BedrockRateLimiter(min_interval=2.0)
    circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
    invention_agent = InventionExtractionAgentCached(
        bedrock, MODEL_SONNET, max_iterations=4,
        # bedrock, MODEL_OPUS, max_iterations=4,
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
                # "before": "publication:20220101"
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
                "q": patent_number,
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
    
    def search_scholar(self, query: str, max_results: int = 10) -> list:
        if not self.GoogleSearch:
            return []
        try:
            params = {
                "engine": "google_scholar",
                "q": query,
                "api_key": self.api_key,
                "as_yhi": "2022"
            }
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            results = search.get_dict()
            return self._parse_results_paper(results, max_results)
        except Exception as e:
            print(f"    SerpAPI error: {e}")
            return []

    # def _extract_patent_number(self, patent_id: str) -> str:
    #     if not patent_id:
    #         return ""
    #     parts = patent_id.split("/")
    #     if len(parts) >= 2:
    #         return parts[1] if parts[0] == "patent" else parts[0]
    #     return patent_id

    def _parse_results_paper(self, data: dict, max_results: int) -> list:
        papers = []
        for result in data.get("organic_results", [])[:max_results]:
            title = result.get("title", "")
            if not title:
                continue
            paper = {
                "title": title,
                "url": result.get("link", ""),
                "publication_info": result.get("publication_info", {}).get("summary", ""),
                "abstract": "",  # fetched later by scrapper_2
            }
            papers.append(paper)
        return papers

    def get_paper_details(self, patent_number: str) -> dict:
        if not self.GoogleSearch:
            return {"patent_number": patent_number, "error": "serpapi not installed"}
        try:
            params = {
                "engine": "google_patents",
                "q": patent_number,
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


def call_bedrock_json(prompt, max_tokens=4000, model_id=MODEL_OPUS, max_parse_retries=3):
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
            "temperature": 0.1,
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

def stage_1_extract_invention_rag(sections):
    """Stage 1: Extract invention using RAG agent with validate/refine/judge loop"""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION (RAG + Validate/Refine/Judge)")
    print("="*60)

    rag_agent = InventionExtractionAgentRAG(
        bedrock_client=bedrock,
        # model_id=MODEL_SONNET,
        model_id=MODEL_OPUS,
        sections=sections,
        k=4,
        max_iterations=3,
        patentability_mode="",
    )

    result = rag_agent.run()

    # Save agent logs
    log_file = rag_agent.save_logs()
    print(f"  Agent logs saved: {log_file}")

    if result["success"]:
        return {
            "invention": result["invention"],
            "patentability": result.get("patentability"),
            "final_confidence": result.get("final_confidence", 0.0),
            "stop_reason": result.get("stop_reason", ""),
            "log_file": log_file,
        }

    return None


def stage_1_extract_invention(sections):
    """Stage 1 (legacy): Extract invention using cached ReAct agent"""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION (ReAct Agent + Prompt Caching)")
    print("="*60)

    result = invention_agent.run(sections)

    log_file = invention_agent.save_logs()
    print(f"  Agent logs saved: {log_file}")

    if result["success"]:
        invention = result["invention"]
        return {"1": invention}, log_file

    return None, log_file


def stage_2_generate_queries(invention):
    """Stage 2: Generate search queries (using Sonnet)"""
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)

    prompt = PromptTemplates.generate_search_queries(invention, num_queries=15)
    print("promtpt:",prompt)
    queries = call_bedrock_json(prompt, max_tokens=5000, model_id=MODEL_OPUS)

    if queries:
        print(f"  Generated {len(queries)} queries:")
        for q in queries:
            print(f"    - {q}")

    return queries or []


def stage_3_search_patents(queries, max_concurrent: int = 5):
    """Stage 3: Search patents via SerpAPI (parallel)."""
    print("\n" + "="*60)
    print("STAGE 3: PATENT SEARCH (SerpAPI, parallel)")
    print("="*60)

    all_patents = []
    seen = set()

    results_by_query = parallel_search_queries(
        patent_searcher,
        queries,
        max_results_per_query=10,
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


def stage_3_search_scholar(queries, max_concurrent: int = 5):
    """Stage 3: Search Google Scholar via SerpAPI (parallel)."""
    print("\n" + "="*60)
    print("STAGE 3: SCHOLAR SEARCH (SerpAPI, parallel)")
    print("="*60)

    all_papers = []
    seen_titles: set = set()

    results_by_query = parallel_scholar_queries(
        patent_searcher,
        queries,
        max_results_per_query=10,
        max_concurrent=max_concurrent,
    )

    for query, results in results_by_query:
        print(f"  Merging results for: {query!r}")
        for p in results:
            t = p.get("title", "").lower()
            if t and t not in seen_titles:
                seen_titles.add(t)
                all_papers.append(p)

    print(f"  Total unique papers: {len(all_papers)}")
    return all_papers


def stage_4_fetch_details(patents, max_concurrent: int = 5):
    """Stage 4: Fetch patent details (parallel)"""
    print("\n" + "="*60)
    print("STAGE 4: FETCH PATENT DETAILS (parallel)")
    print("="*60)

    if not patents:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = patents[:10]
    to_fetch = []

    for p in candidates:
        patent_num = p.get('patent_number', '')
        if p.get('abstract') and len(p.get('abstract', '')) > 50:
            print(f"  Using cached: {patent_num}")
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


def _fetch_scholar_paper_abstract(paper: dict) -> dict:
    """Fetch abstract for a single Scholar paper using scrapper_2's fallback chain."""
    import requests
    from tools.scrapper_2 import (
        extract_doi, extract_abstract,
        _fetch_abstract_crossref, _fetch_abstract_ss_by_title,
    )

    url = paper.get("url", "")
    title = paper.get("title", "")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        )
    }

    doi = None
    abstract = None

    # 1) Try fetching the page directly
    if url:
        try:
            r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            if r.ok:
                doi = extract_doi(r.url, r.text)
                abstract = extract_abstract(r.text)
        except requests.RequestException:
            pass

    # 2) Crossref fallback (needs DOI)
    if not abstract and doi:
        abstract = _fetch_abstract_crossref(doi)

    # 3) Semantic Scholar by title
    if not abstract:
        abstract = _fetch_abstract_ss_by_title(title)

    return {**paper, "abstract": abstract or "", "doi": doi or ""}


def stage_4_fetch_scholar_details(papers: list, max_concurrent: int = 5) -> list:
    """Stage 4 (papers): Fetch abstracts for Google Scholar results in parallel."""
    print("\n" + "="*60)
    print("STAGE 4 (PAPERS): FETCH SCHOLAR ABSTRACTS (parallel)")
    print("="*60)

    if not papers:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_paper = {
            executor.submit(_fetch_scholar_paper_abstract, p): p for p in papers
        }
        for future in as_completed(future_to_paper):
            result = future.result()
            status = "✅" if result.get("abstract") else "⚠️"
            print(f"  {status} {result.get('title', '')[:60]}")
            results.append(result)

    print(f"  Abstracts fetched: {sum(1 for r in results if r.get('abstract'))}/{len(results)}")
    return results


def stage_5_analyze_scholar_papers(invention, papers):# MIGHT PETITION FOR CONCURRENCY INSTEAD OF SERIES
    """Stage 5 (papers): Analyze Google Scholar papers for prior art relevance (using Opus)."""
    print("\n" + "="*60)
    print("STAGE 5 (PAPERS): SCHOLAR PAPER ANALYSIS (Opus)")
    print("="*60)

    if not papers:
        return []

    inv_desc = get_invention_description(invention)

    papers_text = "\n".join(
        f"\nPaper {i}:\n"
        f"Title: {p.get('title', 'N/A')}\n"
        f"Publication Info: {p.get('publication_info', 'N/A')}\n"
        f"Abstract: {p.get('abstract', 'N/A')}..."
        for i, p in enumerate(papers[:5], 1)
    )

    prompt = f"""Analyze these academic papers' relevance to the invention as prior art.

INVENTION:
{inv_desc}

PAPERS TO ANALYZE:
{papers_text}

For EACH paper, provide:
1. Relevance score (0.0 to 1.0)
2. Classification: "blocking" (very similar, published before), "relevant" (overlapping techniques), or "related" (same domain but different approach)
3. Key similarities
4. Key differences
5. Brief analysis (2-3 sentences)

IMPORTANT: Return ONLY a JSON array with no other text. One object per paper in the same order.
Keys per object: "title", "relevance_score", "classification", "similarities", "differences", "analysis"
"""

    analysis = call_bedrock_json(prompt, max_tokens=3000, model_id=MODEL_OPUS)

    if analysis:
        print(f"  Analyzed {len(analysis)} papers:")
        for a in analysis:
            print(f"    {a.get('title', '')[:60]}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis or []


def stage_5_analyze_patents(invention, patents):
    """Stage 5: Analyze patents (using Opus)"""
    print("\n" + "="*60)
    print("STAGE 5: PATENT ANALYSIS (Opus)")
    print("="*60)

    if not patents:
        return []

    inv_desc = get_invention_description(invention)
    prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:5])
    analysis = call_bedrock_json(prompt, max_tokens=3000, model_id=MODEL_OPUS)

    if analysis:
        print(f"  Analyzed {len(analysis)} patents:")
        for a in analysis:
            print(f"    {a.get('patent_number')}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis or []


def stage_6_generate_report(invention, patents, analysis, detailed_papers=None, analysis_papers=None):
    """Stage 6: Generate final report"""
    print("\n" + "="*60)
    print("STAGE 6: FINAL REPORT")
    print("="*60)

    detailed_papers = detailed_papers or []
    analysis_papers = analysis_papers or []

    # --- Patents ---
    analysis_map = {a['patent_number']: a for a in analysis if a.get('patent_number')}
    patent_results = []
    for p in patents:
        num = p.get('patent_number')
        result = {**p}
        if num in analysis_map:
            result['analysis'] = analysis_map[num]
        patent_results.append(result)

    # --- Scholar papers ---
    paper_analysis_map = {a['title']: a for a in analysis_papers if a.get('title')}
    paper_results = []
    for p in detailed_papers:
        title = p.get('title', '')
        result = {**p}
        if title in paper_analysis_map:
            result['analysis'] = paper_analysis_map[title]
        paper_results.append(result)

    report = {
        "invention": invention,
        "patents_found": len(patents),
        "patents_analyzed": len(analysis),
        "blocking": len([a for a in analysis if a.get('classification') == 'blocking']),
        "relevant": len([a for a in analysis if a.get('classification') == 'relevant']),
        "related": len([a for a in analysis if a.get('classification') == 'related']),
        "patents": patent_results,
        "scholar_papers_found": len(detailed_papers),
        "scholar_papers_analyzed": len(analysis_papers),
        "scholar_papers": paper_results,
    }

    print(f"  Summary:")
    print(f"    Patents found: {report['patents_found']}")
    print(f"    Blocking: {report['blocking']}")
    print(f"    Relevant: {report['relevant']}")
    print(f"    Related: {report['related']}")
    print(f"    Scholar papers found: {report['scholar_papers_found']}")
    print(f"    Scholar papers analyzed: {report['scholar_papers_analyzed']}")

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
    print("PATENT PRIOR ART SEARCH PIPELINE (RAG + Prompt-Cached)")
    print("#"*60)
    print(f"Input: s3://{bucket}/{pdf_key}")
    print(f"Models: Sonnet (query gen), Opus (extraction + analysis)")

    # Stage 0: Extract text as section-wise chunks using Textract Layout
    _t0 = time.time()
    _emit(0, "Extracting text from PDF")
    print("  Starting Textract Layout extraction (section-wise)...")
    chunks = extract_text_from_s3_by_sections(bucket, pdf_key)
    if not chunks:
        _emit(-1, "Textract extraction failed", status="error", error="Textract Layout extraction failed")
        return {"error": "Textract Layout extraction failed"}
    sections = normalize_textract_chunks(chunks)
    if not sections:
        _emit(-1, "No sections extracted", status="error", error="No sections extracted from document")
        return {"error": "No sections extracted from document"}
    print(f"  Extracted {len(sections)} sections")

    # Stage 0b: Summarize + Embed sections for RAG
    _emit(0, "Summarizing and embedding sections")
    new_section = summarize_sections_parallel(sections, concurrency=8)
    new_section = add_embeddings_parallel(new_section, concurrency=8)
    print(f"  Summarized and embedded {len(new_section)} sections")

    # Stage 1: Extract invention (RAG agent with validate/refine/judge)

    _emit(1, "Extracting invention details (RAG)")
    stage1_result = stage_1_extract_invention_rag(new_section)
    print(f"  [TIMER] Stage 1 elapsed: {time.time() - _t0:.1f}s")
    # exit()
    agent_log_file = stage1_result.get("log_file") if stage1_result else None

    if not stage1_result:
        _emit(-1, "No inventions found", status="error", error="No inventions found")
        return {"error": "No inventions found"}

    invention = stage1_result["invention"]
    patentability = stage1_result.get("patentability")

    if patentability:
        print(f"\n  Patentability: {patentability.get('classification')} "
              f"(score: {patentability.get('total_score')}/6)")
        print(f"  Confidence: {stage1_result.get('final_confidence', 0):.2f}")
        print(f"  Stop reason: {stage1_result.get('stop_reason', '')}")

    

    # Stage 2: Generate queries
    _emit(2, "Generating search queries")
    try:
        print(invention)
        queries = stage_2_generate_queries(invention)
    except JsonParseExhaustedError:
        raise  # let pipeline retry wrapper handle it
    except Exception as e:
        print(f"  Stage 2 failed: {e}")
        queries = []

    patents = []
    detailed = []
    analysis = []
    papers = []
    detailed_papers = []
    analysis_arxiv = []
    
    if not queries:
        print("  WARNING: No search queries generated — skipping patent search stages")
    else:
        exit()
        # Stage 3: Search patents + arxiv papers
        _emit(3, "Searching patents and papers", detail=f"{len(queries)} queries")
        try:
            patents = stage_3_search_patents(queries)
            for p in patents:
                print(f"  {p.get('patent_number', 'N/A')}: {p.get('title', 'N/A')}")
            # exit()
        except Exception as e:
            print(f"  Stage 3 patent search failed: {e}")
        try:
            papers = stage_3_search_scholar(queries)
        except Exception as e:
            print(f"  Stage 3 scholar search failed: {e}")

        if not patents and not papers:
            print("  WARNING: No patents or papers found — skipping analysis stages")
        else:
            # Stage 4: Fetch patent details + filter arxiv papers
            _emit(4, "Fetching details and filtering", detail=f"{len(patents)} patents, {len(papers)} papers")
            try:
                detailed = stage_4_fetch_details(patents)
            except Exception as e:
                print(f"  Stage 4 patent details failed: {e}")
                detailed = patents
            try:
                detailed_papers = stage_4_fetch_scholar_details(papers)
            except Exception as e:
                print(f"  Stage 4 scholar detail fetch failed: {e}")
                detailed_papers = papers

            # Stage 5: Analyze patents + arxiv papers
            _emit(5, "Analyzing prior art", detail=f"{len(detailed)} patents, {len(detailed_papers)} papers")
            # invention_desc = (
            #     f"Name: {invention.get('invention_name', '')}\n"
            #     f"Description: {invention.get('technical_description', '')}\n"
            #     f"Problem: {invention.get('problem_statement', '')}\n"
            #     f"Solution: {invention.get('solution_approach', '')}\n"
            #     f"Features: {', '.join(invention.get('key_technical_features', []))}"
            # )
            try:
                analysis = stage_5_analyze_patents(invention, detailed)
            except JsonParseExhaustedError:
                raise
            except Exception as e:
                print(f"  Stage 5 patent analysis failed: {e}")
            try:
                analysis_arxiv = stage_5_analyze_scholar_papers(invention, detailed_papers)
            except JsonParseExhaustedError:
                raise
            except Exception as e:
                print(f"  Stage 5 paper analysis failed: {e}")

    # Stage 6: Report (always runs — produces partial report with whatever we have)
    _emit(6, "Generating final report")
    report = stage_6_generate_report(
        invention,
        detailed or patents,
        analysis,
        detailed_papers=detailed_papers,
        analysis_papers=analysis_arxiv,
    )

    # Add patentability to report
    if patentability:
        report["patentability"] = patentability
        report["final_confidence"] = stage1_result.get("final_confidence", 0.0)

    # Save report to S3
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
    if agent_log_file:
        log_key = pdf_key.replace('input/', 'logs/').replace('.pdf', '_agent_logs_Testing.json')
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
    start_time = time.time()

    _init_components()
    if len(sys.argv) < 2:
        print("Available PDFs in S3:")
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix='input/')
        for obj in response.get('Contents', []):
            print(f"  {obj['Key']}")
        print(f"\nUsage: python3 full_pipeline_integrated_Prayoga.py <pdf_key>")
    else:
        pdf_key = sys.argv[1]
        report = run_pipeline(BUCKET, pdf_key)
        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
    print(f"  Total time: {time.time()-start_time:.1f}s")