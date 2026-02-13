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
import copy
from datetime import datetime
from prompt_templates import PromptTemplates, get_invention_description
from invention_agent_cached import InventionExtractionAgentCached
from parallel_search import parallel_search_queries
from textractChunkingv2 import extract_text_from_s3_by_sections, normalize_textract_chunks
from summarization import summarize_sections, summarize_sections_parallel, add_embeddings_parallel, build_section_summary_items
# Initialize clients
bedrock = boto3.client('bedrock-runtime', region_name='us-east-2')
s3 = boto3.client('s3')

BUCKET = "patent-pdf-input-786827631714"

# Model IDs
MODEL_SONNET = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # For agent
MODEL_OPUS = "us.anthropic.claude-opus-4-20250514-v1:0"        # For analysis


# ============================================================
# PATENT SEARCHER (SerpAPI) — unchanged from original
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
                "before": "publication:20220101"
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


# ============================================================
# RATE LIMITER — unchanged
# ============================================================

class RateLimiter:
    def __init__(self, min_interval=2.0):
        self.min_interval = min_interval
        self.last_request = 0

    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()


# ============================================================
# INITIALIZE COMPONENTS
# ============================================================

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
if not SERPAPI_KEY:
    print("WARNING: SERPAPI_KEY not set. Set with: export SERPAPI_KEY='your_key'")

patent_searcher = PatentSearcher(api_key=SERPAPI_KEY, delay=0.5)
rate_limiter = RateLimiter(min_interval=2.0)

# *** This is the key change: use the cached agent ***
invention_agent = InventionExtractionAgentCached(bedrock, MODEL_OPUS, max_iterations=4)


# ============================================================
# LLM CALL FUNCTIONS — unchanged
# ============================================================

def call_bedrock(prompt, max_tokens=4000, model_id=MODEL_OPUS):
    """Call Bedrock with rate limiting"""
    rate_limiter.wait()
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = bedrock.invoke_model(
        modelId=model_id,
        contentType='application/json',
        accept='application/json',
        body=json.dumps(request_body)
    )
    result = json.loads(response['body'].read())
    return result['content'][0]['text']


def parse_json(text):
    """Extract JSON from LLM response"""
    try:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return json.loads(match.group(1))
        match = re.search(r'[\[{].*[\]}]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None



# ============================================================
# PIPELINE STAGES
# ============================================================

def stage_1_extract_invention(sections):
    """Stage 1: Extract invention using cached ReAct agent (section-wise chunks)"""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION (ReAct Agent + Prompt Caching)")
    print("="*60)

    result = invention_agent.run(sections)

    # Save agent logs
    log_file = invention_agent.save_logs()
    print(f"  Agent logs saved: {log_file}")

    if result["success"]:
        invention = result["invention"]
        return {"1": invention}

    return None


def stage_2_generate_queries(invention):
    """Stage 2: Generate search queries (using Sonnet)"""
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)

    prompt = PromptTemplates.generate_search_queries(invention, num_queries=10)
    response = call_bedrock(prompt, max_tokens=500, model_id=MODEL_OPUS)
    queries = parse_json(response)

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

    target_queries = queries[:3]
    all_patents = []
    seen = set()

    results_by_query = parallel_search_queries(
        patent_searcher,
        target_queries,
        max_results_per_query=5,
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


def stage_4_fetch_details(patents):
    """Stage 4: Fetch patent details"""
    print("\n" + "="*60)
    print("STAGE 4: FETCH PATENT DETAILS")
    print("="*60)

    if not patents:
        return []

    detailed_patents = []
    for p in patents[:10]:
        patent_num = p.get('patent_number', '')
        if p.get('abstract') and len(p.get('abstract', '')) > 50:
            print(f"  Using cached: {patent_num}")
            detailed_patents.append(p)
        elif patent_num:
            print(f"  Fetching: {patent_num}")
            details = patent_searcher.get_patent_details(patent_num)
            merged = {**p, **details}
            detailed_patents.append(merged)

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
    prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:5])
    response = call_bedrock(prompt, max_tokens=3000, model_id=MODEL_OPUS)
    analysis = parse_json(response)

    if analysis:
        print(f"  Analyzed {len(analysis)} patents:")
        for a in analysis:
            print(f"    {a.get('patent_number')}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis or []


def stage_6_generate_report(invention, patents, analysis):
    """Stage 6: Generate final report"""
    print("\n" + "="*60)
    print("STAGE 6: FINAL REPORT")
    print("="*60)

    analysis_map = {a['patent_number']: a for a in analysis}

    results = []
    for p in patents:
        num = p.get('patent_number')
        result = {**p}
        if num in analysis_map:
            result['analysis'] = analysis_map[num]
        results.append(result)

    report = {
        "invention": invention,
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

def run_pipeline(bucket, pdf_key):
    """Run complete pipeline"""
    print("\n" + "#"*60)
    print("PATENT PRIOR ART SEARCH PIPELINE (Prompt-Cached)")
    print("#"*60)
    print(f"Input: s3://{bucket}/{pdf_key}")
    print(f"Models: Sonnet (agent w/ caching), Opus (analysis)")

    # Extract text as section-wise chunks using Textract Layout
    print("  Starting Textract Layout extraction (section-wise)...")
    chunks = extract_text_from_s3_by_sections(bucket, pdf_key)
    if not chunks:
        return {"error": "Textract Layout extraction failed"}
    sections = normalize_textract_chunks(chunks)
    if not sections:
        return {"error": "No sections extracted from document"}
    print(f"  Extracted {len(sections)} sections")



    new_section = summarize_sections_parallel(sections)
    new_section = add_embeddings_parallel(new_section, concurrency=5)       # Titan embeddings step
    section_summary_items = build_section_summary_items(new_section)

    # Example: get Methods section summary
    # methods_summary = section_summary_items["S3"]
    with open("sections_with_summary_and_embedding.json", "w") as f:
        json.dump(new_section, f, indent=2)

    # Save per-section rolling summaries
    with open("section_summary_items.json", "w") as f:
        json.dump(section_summary_items, f, indent=2)

    print("Saved:")
    print(" - sections_with_summary_and_embedding.json")
    print(" - section_summary_items.json")

    exit()

    # Stage 1: Extract invention (cached ReAct agent — section-wise chunks)
    inventions = stage_1_extract_invention(sections)
    if not inventions:
        return {"error": "No inventions found"}

    invention = list(inventions.values())[0]

    # Stage 2: Generate queries
    queries = stage_2_generate_queries(invention)

    # Stage 3: Search patents
    patents = stage_3_search_patents(queries)

    # Stage 4: Fetch details
    detailed = stage_4_fetch_details(patents)

    # Stage 5: Analyze
    analysis = stage_5_analyze_patents(invention, detailed)

    # Stage 6: Report
    report = stage_6_generate_report(invention, detailed, analysis)

    # Save to S3
    output_key = pdf_key.replace('input/', 'results/').replace('.pdf', '_report.json')
    s3.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=json.dumps(report, indent=2),
        ContentType='application/json'
    )
    print(f"\nReport saved: s3://{bucket}/{output_key}")

    return report


if __name__ == "__main__":
    import sys

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
