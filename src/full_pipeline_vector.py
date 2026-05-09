"""
Full Patent Search Pipeline — Vector-Ranked Variant

Identical to full_pipeline_cached.py except for Stage 3b:
after SerpAPI returns all candidates, every patent and paper is
embedded with Amazon Titan Embed v2 and scored against the invention
description via FAISS cosine similarity.  Only the top-ranked
candidates proceed to Stage 4 (detail fetch) and Stage 5 (LLM analysis),
replacing the previous arrival-order slice.

Embeddings are saved to a local temp directory and deleted immediately
after ranking — nothing extra is uploaded to S3.

To switch the backend to this version, change one line in
backend/pipeline_runner.py:
    from full_pipeline_vector import run_pipeline   # ← this file
    # from full_pipeline_cached import run_pipeline  # ← arrival-order
Then: sudo systemctl restart patent-agent-api
"""
import boto3
import json
import re
import time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dotenv import load_dotenv
from prompt_templates import PromptTemplates, get_invention_description
from invention_agent_cached import InventionExtractionAgentCached
from utils.parallel_search import parallel_search_queries, parallel_scholar_queries
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
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
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

    def search(self, query: str, max_results: int = 10) -> tuple:
        """Returns (results_list, total_count) where total_count is Google Patents' total hit count."""
        if not self.GoogleSearch:
            return [], 0
        try:
            params = {
                "engine": "google_patents",
                "q": query,
                "api_key": self.api_key,
                "num": min(max_results, 100),
            }
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            data = search.get_dict()
            total = data.get("search_information", {}).get("total_results", 0)
            return self._parse_results(data, max_results), total
        except Exception as e:
            print(f"    SerpAPI error: {e}")
            return [], 0

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
                "patent_id": patent_id,
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

    def get_patent_details(self, patent_number: str, patent_id: str = "") -> dict:
        if not self.GoogleSearch:
            return {"patent_number": patent_number, "error": "serpapi not installed"}
        try:
            pid = patent_id or f"patent/{patent_number}/en"
            params = {
                "engine": "google_patents_details",
                "patent_id": pid,
                "api_key": self.api_key,
            }
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            data = search.get_dict()
            if not data.get("title"):
                return {"patent_number": patent_number, "error": "Not found"}
            claims = data.get("claims", [])
            claim_1 = ""
            if claims:
                first = claims[0]
                if isinstance(first, dict):
                    claim_1 = first.get("text") or first.get("claim_text", "")
                elif isinstance(first, str):
                    claim_1 = first
            inventors = data.get("inventors", "")
            if isinstance(inventors, list):
                inventors = ", ".join(i.get("name", str(i)) if isinstance(i, dict) else str(i) for i in inventors)
            assignees = data.get("assignees", "")
            if isinstance(assignees, list):
                assignees = ", ".join(a.get("name", str(a)) if isinstance(a, dict) else str(a) for a in assignees)
            return {
                "patent_number": patent_number,
                "patent_id": pid,
                "title": data.get("title", ""),
                "abstract": data.get("abstract") or data.get("snippet", ""),
                "url": f"https://patents.google.com/{pid}",
                "filing_date": data.get("filing_date", ""),
                "publication_date": data.get("publication_date", ""),
                "inventors": inventors,
                "assignee": assignees,
                "claim_1": claim_1,
            }
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
            }
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            results = search.get_dict()
            return self._parse_results_paper(results, max_results)
        except Exception as e:
            print(f"    SerpAPI error: {e}")
            return []

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


# ============================================================
# LLM CALL FUNCTIONS
# ============================================================


class JsonParseExhaustedError(Exception):
    """Raised when all JSON-parse retry attempts are exhausted."""


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
    """Stage 1: Extract invention using cached ReAct agent."""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION (ReAct Agent + Prompt Caching)")
    print("="*60)

    result = invention_agent.run(sections)

    log_file = invention_agent.save_logs()
    print(f"  Agent logs saved: {log_file}")

    if result["success"]:
        invention = result["invention"]
        patentability = result.get("patentability")
        return {"1": invention}, log_file, patentability

    return None, log_file, None


def stage_2_generate_queries(invention, user_invention_input="", optional_keywords=None):
    """Stage 2: Generate search queries using a two-call approach.

    Call 1 extracts concepts, synonym chains, and novelty axes into a
    structured scratchpad (verifiable intermediate output).
    Call 2 uses that scratchpad as grounded context to produce the final
    query list, replacing silent internal reasoning with explicit output.

    optional_keywords: list of keyword hints the LLM may incorporate into queries.

    Returns (queries, scratchpad) — scratchpad is the concept extraction
    dict or {} if Call 1 failed (fallback to single-call mode).
    """
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)

    # --- Call 1: concept extraction scratchpad ---
    scratchpad = {}
    try:
        print("  Step 2a: Extracting concepts and synonym chains...")
        scratchpad_prompt = PromptTemplates.generate_concept_scratchpad(
            invention, user_invention_input=user_invention_input, optional_keywords=optional_keywords
        )
        scratchpad = call_bedrock_json(scratchpad_prompt, max_tokens=1200, model_id=MODEL_QUERY_GEN) or {}
        if scratchpad:
            print(f"  Statutory category: {scratchpad.get('statutory_category', '?')}")
            print(f"  WHAT axis: {scratchpad.get('what_axis', '?')}")
            if scratchpad.get('how_axis'):
                print(f"  HOW axis: {scratchpad.get('how_axis')}")
            print(f"  Concepts extracted: {len(scratchpad.get('concepts', []))}")
        else:
            print("  WARNING: Scratchpad call returned empty — falling back to single-call mode")
    except Exception as e:
        print(f"  WARNING: Scratchpad call failed ({e}) — falling back to single-call mode")

    # --- Call 2: generate queries ---
    queries = None
    if scratchpad and scratchpad.get("concepts"):
        try:
            print("  Step 2b: Generating queries from extracted concepts...")
            query_prompt = PromptTemplates.generate_queries_from_scratchpad(
                invention, scratchpad, num_queries=NUM_SEARCH_QUERIES, optional_keywords=optional_keywords
            )
            queries = call_bedrock_json(query_prompt, max_tokens=1500, model_id=MODEL_QUERY_GEN)
        except Exception as e:
            print(f"  WARNING: Two-call query generation failed ({e}) — falling back to single-call mode")
            queries = None

    # --- Fallback: original single-call approach ---
    if not queries:
        print("  Using single-call fallback...")
        prompt = PromptTemplates.generate_search_queries(invention, num_queries=NUM_SEARCH_QUERIES)
        queries = call_bedrock_json(prompt, max_tokens=1500, model_id=MODEL_QUERY_GEN)

    if queries:
        print(f"  Generated {len(queries)} queries:")
        for q in queries:
            print(f"    - {q}")

    return queries or [], scratchpad


def apply_required_keywords(queries: list, required_keywords: list) -> list:
    """Append each required keyword to every query using AND logic.

    Single-word keyword → AND keyword
    Multi-word phrase   → AND "multi word phrase"
    """
    for kw in required_keywords:
        kw = kw.strip()
        if not kw:
            continue
        term = f'"{kw}"' if ' ' in kw else kw
        queries = [f'{q} AND {term}' for q in queries]
    return queries


def stage_3_search_patents(queries, max_concurrent: int = MAX_SEARCH_CONCURRENT):
    """Stage 3: Search patents via SerpAPI (parallel).

    Returns (patents_list, query_counts) where query_counts is a dict mapping
    each query string to Google Patents' total hit count for that query.
    """
    print("\n" + "="*60)
    print("STAGE 3: PATENT SEARCH (SerpAPI, parallel)")
    print("="*60)

    all_patents = []
    seen = set()
    query_counts: dict = {}

    results_by_query = parallel_search_queries(
        patent_searcher,
        queries,
        max_results_per_query=MAX_RESULTS_PER_QUERY,
        max_concurrent=max_concurrent,
    )

    for query, results, total in results_by_query:
        query_counts[query] = total
        print(f"  Merging results for: {query!r}")
        for p in results:
            num = p.get("patent_number", "")
            if num and num not in seen:
                seen.add(num)
                all_patents.append(p)

    print(f"  Total unique patents: {len(all_patents)}")
    return all_patents, query_counts


def stage_3_search_scholar(queries, max_concurrent: int = MAX_SEARCH_CONCURRENT):
    """Stage 3: Search Google Scholar via SerpAPI (parallel)."""
    print("\n" + "="*60)
    print("STAGE 3: SCHOLAR SEARCH (SerpAPI, parallel)")
    print("="*60)

    all_papers = []
    seen_titles: set = set()

    results_by_query = parallel_scholar_queries(
        patent_searcher,
        queries,
        max_results_per_query=5,
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


def stage_3b_rank_by_similarity(invention, patents, papers):
    """
    Stage 3b: Re-rank all SerpAPI candidates by cosine similarity to the
    invention description before deciding which ones to fetch/analyze.

    Uses Amazon Titan Embed v2 (same model as the RAG pipeline) with
    faiss.IndexFlatIP on L2-normalized vectors, which equals cosine similarity.

    Embeddings are written to a local OS temp directory and deleted in the
    finally block — nothing is sent to S3 and no files persist after this stage.

    Returns (ranked_patents, ranked_papers) sorted highest-similarity first,
    each item having a new 'similarity_score' field added.
    """
    import numpy as np
    import faiss
    import tempfile
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    from summarization import embed_text_titan

    print("\n" + "="*60)
    print("STAGE 3b: VECTOR SIMILARITY RANKING")
    print("="*60)

    tmp_dir = tempfile.mkdtemp(prefix="patent_embeddings_")
    try:
        # Build a rich invention query string from all extracted fields
        inv_text = " ".join(filter(None, [
            invention.get("invention_name", ""),
            invention.get("technical_description", ""),
            invention.get("solution_approach", ""),
            " ".join(invention.get("key_technical_features", [])),
            " ".join(invention.get("inventor_keywords", [])),
        ]))

        print(f"  Embedding invention description...")
        inv_vec = np.array([embed_text_titan(inv_text)], dtype=np.float32)
        np.save(os.path.join(tmp_dir, "invention.npy"), inv_vec)

        def _rank(items, text_fn, label):
            """Embed items, score against invention vector, return sorted list."""
            if not items:
                return items

            print(f"  Embedding {len(items)} {label} candidates (parallel)...")

            def embed_one(item):
                text = text_fn(item).strip()
                if not text:
                    text = label  # fallback so embed call never gets empty string
                return embed_text_titan(text)

            with ThreadPoolExecutor(max_workers=MAX_SEARCH_CONCURRENT) as executor:
                vecs = list(executor.map(embed_one, items))

            mat = np.array(vecs, dtype=np.float32)
            np.save(os.path.join(tmp_dir, f"{label}.npy"), mat)

            # IndexFlatIP on normalized vectors = cosine similarity
            index = faiss.IndexFlatIP(mat.shape[1])
            index.add(mat)
            scores, indices = index.search(inv_vec, len(items))

            for score, idx in zip(scores[0], indices[0]):
                items[idx]["similarity_score"] = round(float(score), 4)

            ranked = sorted(items, key=lambda x: x.get("similarity_score", 0.0), reverse=True)

            print(f"  Top 5 {label}s by similarity score:")
            for item in ranked[:5]:
                ident = item.get("patent_number") or item.get("title", "")[:55]
                print(f"    [{item['similarity_score']:.4f}] {ident}")

            return ranked

        ranked_patents = _rank(
            patents,
            lambda p: f"{p.get('title', '')}. {p.get('abstract', '')}",
            "patent",
        )
        ranked_papers = _rank(
            papers,
            lambda p: f"{p.get('title', '')}. {p.get('abstract', '')}",
            "paper",
        )

        print(f"  Ranking complete — {len(ranked_patents)} patents, {len(ranked_papers)} papers")
        # Return inv_vec so Stage 4b can reuse it without a second embed call
        return ranked_patents, ranked_papers, inv_vec

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"  Local embeddings deleted.")


def stage_4b_rerank_by_full_text(invention, patents, cached_inv_vec=None):
    """
    Stage 4b: Re-rank fetched patents by cosine similarity using full text
    (title + full abstract + claim_1) rather than the SerpAPI snippet used in Stage 3b.

    cached_inv_vec: numpy array (1, D) from Stage 3b — skips re-embedding the invention.
    Operates on the ~40 patents returned by Stage 4 (already enriched with claim text).
    Returns the list sorted highest-similarity first, with similarity_score updated.
    Falls back to the original order on any error.
    """
    import numpy as np
    import faiss
    import tempfile
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    from summarization import embed_text_titan

    if not patents:
        return patents

    print("\n" + "="*60)
    print("STAGE 4b: FULL-TEXT VECTOR RE-RANKING")
    print("="*60)

    tmp_dir = tempfile.mkdtemp(prefix="patent_fulltext_embeddings_")
    try:
        inv_text = " ".join(filter(None, [
            invention.get("invention_name", ""),
            invention.get("technical_description", ""),
            invention.get("solution_approach", ""),
            " ".join(invention.get("key_technical_features", [])),
            " ".join(invention.get("inventor_keywords", [])),
        ]))

        if cached_inv_vec is not None:
            print(f"  Reusing invention embedding from Stage 3b.")
            inv_vec = cached_inv_vec
        else:
            print(f"  Embedding invention description...")
            inv_vec = np.array([embed_text_titan(inv_text)], dtype=np.float32)
        np.save(os.path.join(tmp_dir, "invention_fulltext.npy"), inv_vec)

        print(f"  Embedding {len(patents)} patents by full text (title + abstract + claim_1)...")

        def embed_one(p):
            text = " ".join(filter(None, [
                p.get("title", ""),
                p.get("abstract", ""),
                p.get("claim_1", ""),
            ])).strip() or "patent"
            return embed_text_titan(text)

        with ThreadPoolExecutor(max_workers=MAX_SEARCH_CONCURRENT) as executor:
            vecs = list(executor.map(embed_one, patents))

        mat = np.array(vecs, dtype=np.float32)
        np.save(os.path.join(tmp_dir, "patents_fulltext.npy"), mat)

        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)
        scores, indices = index.search(inv_vec, len(patents))

        for score, idx in zip(scores[0], indices[0]):
            patents[idx]["similarity_score"] = round(float(score), 4)

        ranked = sorted(patents, key=lambda p: p.get("similarity_score", 0.0), reverse=True)

        print(f"  Top 5 patents by full-text similarity:")
        for p in ranked[:5]:
            ident = p.get("patent_number") or p.get("title", "")[:55]
            has_claim = "✓ claim_1" if p.get("claim_1") else "  snippet only"
            print(f"    [{p['similarity_score']:.4f}] {ident}  ({has_claim})")

        return ranked

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"  Local embeddings deleted.")


def stage_4_fetch_details(patents, max_concurrent: int = MAX_SEARCH_CONCURRENT):
    """Stage 4: Fetch patent details (parallel)."""
    print("\n" + "="*60)
    print("STAGE 4: FETCH PATENT DETAILS (parallel)")
    print("="*60)

    if not patents:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # After Stage 3b the list is similarity-sorted; slice gives top-ranked patents
    candidates = patents[:MAX_PATENTS_TO_FETCH]
    cached = []
    to_fetch = []

    for p in candidates:
        patent_num = p.get('patent_number', '')
        if p.get('claim_1') and p.get('abstract') and len(p.get('abstract', '')) > 150:
            print(f"  Using cached: {patent_num}")
            cached.append(p)
        elif patent_num:
            to_fetch.append(p)

    def fetch_one(p):
        patent_num = p.get('patent_number', '')
        patent_id = p.get('patent_id', '')
        print(f"  Fetching: {patent_num}")
        try:
            details = patent_searcher.get_patent_details(patent_num, patent_id)
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

    # Preserve original (similarity) order
    fetched_map = {p.get('patent_number', ''): p for p in fetched}
    detailed_patents = []
    for p in candidates:
        patent_num = p.get('patent_number', '')
        if patent_num in fetched_map:
            detailed_patents.append(fetched_map[patent_num])
        else:
            detailed_patents.append(p)

    claim_count = sum(1 for p in detailed_patents if p.get("claim_1"))
    print(f"  Got details for {len(detailed_patents)} patents — claim_1 populated for {claim_count}/{len(detailed_patents)}.")
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

    if url:
        try:
            r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            if r.ok:
                doi = extract_doi(r.url, r.text)
                abstract = extract_abstract(r.text)
        except requests.RequestException:
            pass

    if not abstract and doi:
        abstract = _fetch_abstract_crossref(doi)

    if not abstract:
        abstract = _fetch_abstract_ss_by_title(title)

    return {**paper, "abstract": abstract or "", "doi": doi or ""}


def stage_4_fetch_scholar_details(papers: list, max_concurrent: int = MAX_SEARCH_CONCURRENT) -> list:
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
            status = "OK" if result.get("abstract") else "NO ABSTRACT"
            print(f"  [{status}] {result.get('title', '')[:60]}")
            results.append(result)

    print(f"  Abstracts fetched: {sum(1 for r in results if r.get('abstract'))}/{len(results)}")
    return results


def stage_5_analyze_patents(invention, patents):
    """Stage 5: Analyze top-ranked patents with LLM."""
    print("\n" + "="*60)
    print("STAGE 5: PATENT ANALYSIS")
    print("="*60)

    if not patents:
        return []

    inv_desc = get_invention_description(invention)
    prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:MAX_PATENTS_TO_ANALYZE])
    analysis = call_bedrock_json(prompt, max_tokens=6000, model_id=MODEL_ANALYSIS)

    if analysis:
        print(f"  Analyzed {len(analysis)} patents:")
        for a in analysis:
            print(f"    {a.get('patent_number')}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis or []


def stage_5_analyze_scholar_papers(invention, papers):
    """Stage 5 (papers): Analyze top-ranked scholar papers for prior art relevance."""
    print("\n" + "="*60)
    print("STAGE 5 (PAPERS): SCHOLAR PAPER ANALYSIS")
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

    analysis = call_bedrock_json(prompt, max_tokens=6000, model_id=MODEL_ANALYSIS)

    if analysis:
        print(f"  Analyzed {len(analysis)} papers:")
        for a in analysis:
            print(f"    {a.get('title', '')[:60]}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis or []


def stage_6_generate_report(invention, patents, analysis, patentability=None, detailed_papers=None, analysis_papers=None, user_invention_input=""):
    """Stage 6: Generate final report."""
    print("\n" + "="*60)
    print("STAGE 6: FINAL REPORT")
    print("="*60)

    detailed_papers = detailed_papers or []
    analysis_papers = analysis_papers or []

    # --- Patents ---
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

    # --- Scholar papers ---
    paper_analysis_map = {a['title']: a for a in analysis_papers if a.get('title')}
    paper_results = []
    for p in detailed_papers:
        result = {**p}
        if p.get('title', '') in paper_analysis_map:
            result['analysis'] = paper_analysis_map[p['title']]
        paper_results.append(result)

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
        "patents": results,
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

    if user_invention_input.strip():
        print("  Evaluating inventor's stated description...")
        user_input_assessment: dict = {}
        try:
            prompt = PromptTemplates.analyze_user_invention_input(
                user_invention_input, invention_out, patentability or {}
            )
            user_input_assessment = call_bedrock_json(prompt, max_tokens=800, model_id=MODEL_QUERY_GEN) or {}
        except Exception as e:
            print(f"  WARNING: User input analysis failed ({e})")
        if user_input_assessment:
            user_input_assessment["user_invention_input"] = user_invention_input
            report["user_input_analysis"] = user_input_assessment
            print(f"  User input verdict: {user_input_assessment.get('verdict', 'unknown')}")

    return report


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline_from_search(bucket, result_key, required_keywords=None, optional_keywords=None, progress_callback=None):
    """Run pipeline stages 2-7 using an existing invention from a completed report.

    Fetches the invention dict from the S3 result_key, then re-runs search
    query generation through report generation with optional keyword overrides.
    Saves the new report under a timestamped rerun key derived from result_key.
    """
    _init_components()
    required_keywords = required_keywords or []
    optional_keywords = optional_keywords or []

    def _emit(stage, stage_name, status="running", **extra):
        if progress_callback:
            progress_callback({"stage": stage, "stage_name": stage_name, "status": status, **extra})

    print("\n" + "#"*60)
    print("PATENT PRIOR ART SEARCH PIPELINE (Keyword Rerun, Stages 2-7)")
    print("#"*60)
    print(f"Original report: s3://{bucket}/{result_key}")

    # Fetch invention from existing report
    try:
        obj = s3.get_object(Bucket=bucket, Key=result_key)
        existing_report = json.loads(obj["Body"].read())
        invention = existing_report.get("invention")
        if not invention:
            _emit(-1, "Invalid report", status="error", error="Existing report has no invention field")
            return {"error": "Existing report has no invention field"}
    except Exception as e:
        _emit(-1, "Failed to load report", status="error", error=str(e))
        return {"error": f"Failed to load existing report: {e}"}

    queries = []
    patents = []
    query_counts: dict = {}
    concept_scratchpad: dict = {}
    cached_inv_vec = None
    detailed = []
    analysis = []
    papers = []
    detailed_papers = []
    analysis_arxiv = []

    # Stage 2: Generate queries with optional keywords, then apply required keywords
    _emit(2, "Generating search queries (refined)")
    try:
        queries, concept_scratchpad = stage_2_generate_queries(
            invention, optional_keywords=optional_keywords or None
        )
    except JsonParseExhaustedError:
        _emit(-1, "Query generation failed", status="error", error="JSON parse exhausted in Stage 2")
        return {"error": "JSON parse exhausted in Stage 2"}
    except Exception as e:
        print(f"  Stage 2 failed: {e}")

    if required_keywords and queries:
        queries = apply_required_keywords(queries, required_keywords)
        print(f"  Applied {len(required_keywords)} required keyword(s) to all {len(queries)} queries")

    if not queries:
        print("  WARNING: No search queries generated — skipping patent search stages")
    else:
        # Stage 3: Patent + scholar searches run simultaneously
        _emit(3, "Searching patents and papers", detail=f"{len(queries)} queries")
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_patents = ex.submit(stage_3_search_patents, queries)
            f_papers  = ex.submit(stage_3_search_scholar, queries)
            try:
                patents, query_counts = f_patents.result()
            except Exception as e:
                print(f"  Stage 3 patent search failed: {e}")
            try:
                papers = f_papers.result()
            except Exception as e:
                print(f"  Stage 3 scholar search failed: {e}")

        if patents or papers:
            _emit(3, "Ranking candidates by vector similarity")
            try:
                patents, papers, cached_inv_vec = stage_3b_rank_by_similarity(invention, patents, papers)
            except Exception as e:
                print(f"  Stage 3b vector ranking failed: {e} — falling back to arrival order.")

        if not patents and not papers:
            print("  WARNING: No patents or papers found — skipping analysis stages")
        else:
            _emit(4, "Fetching details", detail=f"{len(patents)} patents, {len(papers)} papers")
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_detailed        = ex.submit(stage_4_fetch_details, patents)
                f_detailed_papers = ex.submit(stage_4_fetch_scholar_details, papers)
                try:
                    detailed = f_detailed.result()
                except Exception as e:
                    print(f"  Stage 4 patent details failed: {e}")
                    detailed = patents
                try:
                    detailed_papers = f_detailed_papers.result()
                except Exception as e:
                    print(f"  Stage 4 scholar detail fetch failed: {e}")
                    detailed_papers = papers

            _emit(4, "Re-ranking by full text (abstract + claims)")
            try:
                detailed = stage_4b_rerank_by_full_text(invention, detailed, cached_inv_vec=cached_inv_vec)
            except Exception as e:
                print(f"  Stage 4b full-text re-rank failed: {e} — keeping Stage 4 order.")

            _emit(5, "Analyzing prior art", detail=f"{len(detailed)} patents, {len(detailed_papers)} papers")
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_analysis = ex.submit(stage_5_analyze_patents, invention, detailed)
                f_arxiv    = ex.submit(stage_5_analyze_scholar_papers, invention, detailed_papers)
                try:
                    analysis = f_analysis.result()
                except JsonParseExhaustedError:
                    _emit(-1, "Analysis failed", status="error", error="JSON parse exhausted in Stage 5")
                    return {"error": "JSON parse exhausted in Stage 5"}
                except Exception as e:
                    print(f"  Stage 5 patent analysis failed: {e}")
                try:
                    analysis_arxiv = f_arxiv.result()
                except JsonParseExhaustedError:
                    _emit(-1, "Analysis failed", status="error", error="JSON parse exhausted in Stage 5 scholar")
                    return {"error": "JSON parse exhausted in Stage 5 scholar"}
                except Exception as e:
                    print(f"  Stage 5 paper analysis failed: {e}")

    # Stage 6: Report
    _emit(6, "Generating final report")
    report = stage_6_generate_report(
        invention,
        detailed or patents,
        analysis,
        patentability=None,
        detailed_papers=detailed_papers,
        analysis_papers=analysis_arxiv,
        user_invention_input="",
    )

    # Attach run metadata
    report["run_metadata"] = {
        "pipeline_version": "2.0.0-vector-ranked",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "models": {
            "extraction": MODEL_EXTRACTION,
            "query_generation": MODEL_QUERY_GEN,
            "patent_analysis": MODEL_ANALYSIS,
            "embedding": "amazon.titan-embed-text-v2:0",
        },
        "retrieval_config": {
            "max_patents_fetched": MAX_PATENTS_TO_FETCH,
            "max_patents_analyzed": MAX_PATENTS_TO_ANALYZE,
            "max_search_queries": NUM_SEARCH_QUERIES,
            "ranking": "faiss-cosine-similarity",
            "full_text_rerank": True,
        },
        "query_counts": query_counts,
        "concept_map": concept_scratchpad,
        "rerun": True,
        "original_result_key": result_key,
        "required_keywords": required_keywords,
        "optional_keywords": optional_keywords,
    }

    # Preserve patentability and user_input_analysis from original report
    if existing_report.get("run_metadata", {}).get("patentability"):
        pass  # patentability is embedded in invention, already carried through
    if existing_report.get("user_input_analysis"):
        report["user_input_analysis"] = existing_report["user_input_analysis"]

    # Derive output key and save
    ts = int(datetime.utcnow().timestamp())
    if result_key.endswith("_report.json"):
        output_key = result_key[:-len("_report.json")] + f"_rerun_{ts}_report.json"
    else:
        output_key = result_key + f"_rerun_{ts}.json"

    report_body = json.dumps(report, indent=2)
    try:
        s3.put_object(Bucket=bucket, Key=output_key, Body=report_body, ContentType="application/json")
        print(f"\nRerun report saved: s3://{bucket}/{output_key}")
    except Exception as e:
        print(f"  Failed to save rerun report to S3: {e}")

    _emit(7, "Complete", status="completed", result_key=output_key)
    return report


def run_pipeline(bucket, pdf_key, max_pipeline_retries=2, progress_callback=None, user_invention_input=""):
    """
    Run the vector-ranked pipeline with automatic restart on persistent JSON
    parse failures (up to max_pipeline_retries total attempts).
    """
    _init_components()
    for attempt in range(1, max_pipeline_retries + 1):
        try:
            if attempt > 1:
                print(f"\n  RESTARTING PIPELINE (attempt {attempt}/{max_pipeline_retries})")
            return _run_pipeline_once(bucket, pdf_key, progress_callback=progress_callback, user_invention_input=user_invention_input)
        except JsonParseExhaustedError as e:
            print(f"\n  Pipeline attempt {attempt} failed: {e}")
            if attempt == max_pipeline_retries:
                print("  All pipeline retries exhausted.")
                return {"error": str(e)}
    return {"error": "Pipeline failed unexpectedly"}


def _run_pipeline_once(bucket, pdf_key, progress_callback=None, user_invention_input=""):
    """Run complete vector-ranked pipeline (single attempt)."""
    def _emit(stage, stage_name, status="running", **extra):
        if progress_callback:
            progress_callback({"stage": stage, "stage_name": stage_name, "status": status, **extra})

    print("\n" + "#"*60)
    print("PATENT PRIOR ART SEARCH PIPELINE (Vector-Ranked)")
    print("#"*60)
    print(f"Input: s3://{bucket}/{pdf_key}")

    # Extract text as section-wise chunks
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

    # Stage 1: Extract invention
    _emit(1, "Extracting invention details", detail=f"{len(sections)} sections")
    inventions, agent_log_file, patentability = stage_1_extract_invention(sections)
    if not inventions:
        _emit(-1, "No inventions found", status="error", error="No inventions found")
        return {"error": "No inventions found"}

    invention = list(inventions.values())[0]

    queries = []
    patents = []
    query_counts: dict = {}
    concept_scratchpad: dict = {}
    cached_inv_vec = None
    detailed = []
    analysis = []
    papers = []
    detailed_papers = []
    analysis_arxiv = []

    # Stage 2: Generate queries
    _emit(2, "Generating search queries")
    try:
        queries, concept_scratchpad = stage_2_generate_queries(invention, user_invention_input=user_invention_input)
    except JsonParseExhaustedError:
        raise
    except Exception as e:
        print(f"  Stage 2 failed: {e}")

    if not queries:
        print("  WARNING: No search queries generated — skipping patent search stages")
    else:
        # Stage 3: Patent + scholar searches run simultaneously
        _emit(3, "Searching patents and papers", detail=f"{len(queries)} queries")
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_patents = ex.submit(stage_3_search_patents, queries)
            f_papers  = ex.submit(stage_3_search_scholar, queries)
            try:
                patents, query_counts = f_patents.result()
            except Exception as e:
                print(f"  Stage 3 patent search failed: {e}")
            try:
                papers = f_papers.result()
            except Exception as e:
                print(f"  Stage 3 scholar search failed: {e}")

        if patents or papers:
            # Stage 3b: Re-rank all candidates by vector similarity before fetching details
            _emit(3, "Ranking candidates by vector similarity")
            try:
                patents, papers, cached_inv_vec = stage_3b_rank_by_similarity(invention, patents, papers)
            except Exception as e:
                print(f"  Stage 3b vector ranking failed: {e} — falling back to arrival order.")

        if not patents and not papers:
            print("  WARNING: No patents or papers found — skipping analysis stages")
        else:
            # Stage 4: Patent details + scholar abstracts fetched simultaneously
            # patents list is now similarity-sorted; [:MAX_PATENTS_TO_FETCH] gives top-ranked
            _emit(4, "Fetching details", detail=f"{len(patents)} patents, {len(papers)} papers")
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_detailed        = ex.submit(stage_4_fetch_details, patents)
                f_detailed_papers = ex.submit(stage_4_fetch_scholar_details, papers)
                try:
                    detailed = f_detailed.result()
                except Exception as e:
                    print(f"  Stage 4 patent details failed: {e}")
                    detailed = patents
                try:
                    detailed_papers = f_detailed_papers.result()
                except Exception as e:
                    print(f"  Stage 4 scholar detail fetch failed: {e}")
                    detailed_papers = papers

            # Stage 4b: Re-rank by full text, reusing invention embedding from Stage 3b
            _emit(4, "Re-ranking by full text (abstract + claims)")
            try:
                detailed = stage_4b_rerank_by_full_text(invention, detailed, cached_inv_vec=cached_inv_vec)
            except Exception as e:
                print(f"  Stage 4b full-text re-rank failed: {e} — keeping Stage 4 order.")

            # Stage 5: Patent + scholar analysis run simultaneously
            _emit(5, "Analyzing prior art", detail=f"{len(detailed)} patents, {len(detailed_papers)} papers")
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_analysis = ex.submit(stage_5_analyze_patents, invention, detailed)
                f_arxiv    = ex.submit(stage_5_analyze_scholar_papers, invention, detailed_papers)
                try:
                    analysis = f_analysis.result()
                except JsonParseExhaustedError:
                    raise
                except Exception as e:
                    print(f"  Stage 5 patent analysis failed: {e}")
                try:
                    analysis_arxiv = f_arxiv.result()
                except JsonParseExhaustedError:
                    raise
                except Exception as e:
                    print(f"  Stage 5 paper analysis failed: {e}")

    # Stage 6: Report
    _emit(6, "Generating final report")
    report = stage_6_generate_report(
        invention,
        detailed or patents,
        analysis,
        patentability=patentability,
        detailed_papers=detailed_papers,
        analysis_papers=analysis_arxiv,
        user_invention_input=user_invention_input,
    )

    # Attach run metadata
    report["run_metadata"] = {
        "pipeline_version": "2.0.0-vector-ranked",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "models": {
            "extraction": MODEL_EXTRACTION,
            "query_generation": MODEL_QUERY_GEN,
            "patent_analysis": MODEL_ANALYSIS,
            "embedding": "amazon.titan-embed-text-v2:0",
        },
        "retrieval_config": {
            "max_patents_fetched": MAX_PATENTS_TO_FETCH,
            "max_patents_analyzed": MAX_PATENTS_TO_ANALYZE,
            "max_search_queries": NUM_SEARCH_QUERIES,
            "ranking": "faiss-cosine-similarity",
            "full_text_rerank": True,
        },
        "query_counts": query_counts,
        "concept_map": concept_scratchpad,
    }

    # Save report + agent logs to S3 simultaneously
    output_key = pdf_key.replace('input/', 'results/').replace('.pdf', '_report.json')
    log_key    = pdf_key.replace('input/', 'logs/').replace('.pdf', '_agent_logs.json')

    report_body = json.dumps(report, indent=2)
    try:
        with open(agent_log_file, 'r') as f:
            log_body = f.read()
    except Exception as e:
        print(f"  Could not read agent log file: {e}")
        log_body = ""

    def _upload_report():
        s3.put_object(Bucket=bucket, Key=output_key, Body=report_body, ContentType='application/json')
        print(f"\nReport saved: s3://{bucket}/{output_key}")

    def _upload_logs():
        if log_body:
            s3.put_object(Bucket=bucket, Key=log_key, Body=log_body, ContentType='application/json')
            print(f"Agent logs saved: s3://{bucket}/{log_key}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_report = ex.submit(_upload_report)
        f_logs   = ex.submit(_upload_logs)
        for f, name in [(f_report, "report"), (f_logs, "logs")]:
            try:
                f.result()
            except Exception as e:
                print(f"  Failed to save {name} to S3: {e}")

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
        print(f"\nUsage: python3 full_pipeline_vector.py <pdf_key>")
    else:
        pdf_key = sys.argv[1]
        report = run_pipeline(BUCKET, pdf_key)
        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
