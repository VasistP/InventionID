"""
Full Patent Search Pipeline using Prompt Templates
"""
import boto3
import json
import re
import time
import os
from prompt_templates import PromptTemplates, get_invention_description

# Initialize clients
textract = boto3.client('textract')
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
s3 = boto3.client('s3')

BUCKET = "patent-pdf-input-786827631714"


class PatentSearcher:
    """Search Google Patents via SerpAPI"""
    
    def __init__(self, api_key: str, delay=0.5):
        self.api_key = api_key
        self.delay = delay
        # Import serpapi library
        try:
            from serpapi import GoogleSearch
            self.GoogleSearch = GoogleSearch
        except ImportError:
            print("ERROR: serpapi library not installed. Run: pip install google-search-results --break-system-packages")
            self.GoogleSearch = None
    
    def search(self, query: str, max_results: int = 10) -> list:
        """Search Google Patents via SerpAPI"""
        if not self.GoogleSearch:
            return []
        
        try:
            params = {
                "engine": "google_patents",
                "q": query,
                "api_key": self.api_key
            }
            
            time.sleep(self.delay)
            search = self.GoogleSearch(params)
            results = search.get_dict()
            
            return self._parse_results(results, max_results)
        except Exception as e:
            print(f"    SerpAPI error: {e}")
            return []
    
    def _extract_patent_number(self, patent_id: str) -> str:
        """Extract patent number from path like 'patent/EP2264377A2/en'"""
        if not patent_id:
            return ""
        parts = patent_id.split("/")
        if len(parts) >= 2:
            return parts[1] if parts[0] == "patent" else parts[0]
        return patent_id
    
    def _parse_results(self, data: dict, max_results: int) -> list:
        """Parse SerpAPI Google Patents response"""
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
                "pdf_url": result.get("pdf", ""),
            }
            if patent_number:
                patents.append(patent)
        
        return patents
    
    def get_patent_details(self, patent_number: str) -> dict:
        """Fetch patent details via SerpAPI"""
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
                    "grant_date": r.get("grant_date", ""),
                    "inventors": r.get("inventor", ""),
                    "assignee": r.get("assignee", ""),
                    "claim_1": ""
                }
            return {"patent_number": patent_number, "error": "Not found"}
        except Exception as e:
            print(f"    SerpAPI error for {patent_number}: {e}")
            return {"patent_number": patent_number, "error": str(e)}


# Initialize with API key from environment
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

if not SERPAPI_KEY:
    print("WARNING: SERPAPI_KEY not set. Set it with: export SERPAPI_KEY='your_key_here'")

patent_searcher = PatentSearcher(api_key=SERPAPI_KEY, delay=0.5)

class RateLimiter:
    def __init__(self, min_interval=2.0):
        self.min_interval = min_interval
        self.last_request = 0
    
    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()

rate_limiter = RateLimiter(min_interval=2.0)

def call_bedrock(prompt, max_tokens=4000):
    """Call Bedrock with rate limiting (no web search - using direct scraping instead)"""
    rate_limiter.wait()
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    
    response = bedrock.invoke_model(
        modelId='us.anthropic.claude-sonnet-4-5-20250929-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps(request_body)
    )
    
    result = json.loads(response['body'].read())
    return result['content'][0]['text']

def parse_json(text):
    """Extract JSON from LLM response"""
    try:
        # Try to find JSON in code blocks
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            return json.loads(match.group(1))
        # Try to find raw JSON
        match = re.search(r'[\[{].*[\]}]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None

def extract_text_from_s3(bucket, key):
    """Extract text from PDF using Textract"""
    print(f"  Starting Textract...")
    response = textract.start_document_text_detection(
        DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}}
    )
    job_id = response['JobId']
    
    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        if result['JobStatus'] in ['SUCCEEDED', 'FAILED']:
            break
        time.sleep(3)
    
    if result['JobStatus'] == 'FAILED':
        return None
    
    text = "\n".join([b['Text'] for b in result.get('Blocks', []) if b['BlockType'] == 'LINE'])
    print(f"  Extracted {len(text)} chars")
    return text

# ============================================================
# PIPELINE STAGES
# ============================================================

def stage_1_extract_invention(document_text):
    """Stage 1: Extract invention from document"""
    print("\n" + "="*60)
    print("STAGE 1: INVENTION EXTRACTION")
    print("="*60)
    
    prompt = PromptTemplates.get_inventions()
    prompt = prompt + f"\n\nDOCUMENT:\n{document_text[:15000]}"
    
    response = call_bedrock(prompt)
    inventions = parse_json(response)
    
    if inventions:
        print(f"  Found {len(inventions)} invention(s)")
        for key, inv in inventions.items():
            print(f"    {key}: {inv.get('invention_name', 'Unknown')}")
    else:
        print("  No inventions found")
    
    return inventions

def stage_2_generate_queries(invention):
    """Stage 2: Generate search queries"""
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)
    
    prompt = PromptTemplates.generate_search_queries(invention, num_queries=5)
    response = call_bedrock(prompt, max_tokens=500)
    queries = parse_json(response)
    
    if queries:
        print(f"  Generated {len(queries)} queries:")
        for q in queries:
            print(f"    - {q}")
    
    return queries or []

def stage_3_search_patents(queries):
    """Stage 3: Search for patents using SerpAPI"""
    print("\n" + "="*60)
    print("STAGE 3: PATENT SEARCH (SerpAPI)")
    print("="*60)
    
    all_patents = []
    seen = set()
    
    for query in queries[:3]:  # Limit to 3 queries
        print(f"  Searching: {query}")
        
        # Use direct scraping instead of LLM web search
        results = patent_searcher.search(query, max_results=5)
        
        for p in results:
            num = p.get('patent_number', '')
            if num and num not in seen:
                seen.add(num)
                all_patents.append(p)
                print(f"    Found: {num} - {p.get('title', '')[:50]}")
    
    print(f"  Total unique patents: {len(all_patents)}")
    return all_patents

def stage_4_fetch_details(patents):
    """Stage 4: Fetch patent details (skip if already have abstract from SerpAPI)"""
    print("\n" + "="*60)
    print("STAGE 4: FETCH PATENT DETAILS")
    print("="*60)
    
    if not patents:
        return []
    
    detailed_patents = []
    for p in patents[:10]:
        patent_num = p.get('patent_number', '')
        
        # Skip API call if we already have abstract from search
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
    """Stage 5: Analyze patents against invention (LLM analysis, no web search needed)"""
    print("\n" + "="*60)
    print("STAGE 5: PATENT ANALYSIS")
    print("="*60)
    
    if not patents:
        return []
    
    inv_desc = get_invention_description(invention)
    
    # Batch analyze using LLM (no web search - we already have patent data)
    prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:5])
    response = call_bedrock(prompt, max_tokens=3000)
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
    
    # Merge analysis with patent data
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
    """Run complete pipeline on a PDF"""
    print("\n" + "#"*60)
    print("PATENT PRIOR ART SEARCH PIPELINE")
    print("#"*60)
    print(f"Input: s3://{bucket}/{pdf_key}")
    
    # Extract text
    text = extract_text_from_s3(bucket, pdf_key)
    if not text:
        return {"error": "Textract failed"}
    
    # Stage 1: Extract invention
    inventions = stage_1_extract_invention(text)
    if not inventions:
        return {"error": "No inventions found"}
    
    # Use first invention
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
        # List available PDFs
        print("Available PDFs in S3:")
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix='input/')
        for obj in response.get('Contents', []):
            print(f"  {obj['Key']}")
        print(f"\nUsage: python3 full_pipeline.py <pdf_key>")
        print(f"Example: python3 full_pipeline.py input/paper.pdf")
    else:
        pdf_key = sys.argv[1]
        report = run_pipeline(BUCKET, pdf_key)
        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
