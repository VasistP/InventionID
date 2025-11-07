# Patent Search POC - Bottleneck Analysis & Fixes

## Executive Summary

The current implementation has **5 critical bottlenecks** preventing it from working:

1. ❌ **Google Patents scraping fails (403 error)** - No patents retrieved
2. ❌ **No CLI argument parsing** - Command-line flags don't work
3. ❌ **Sequential LLM calls** - 15 patents × 3-5 sec = 45-75 sec analysis time
4. ❌ **Missing URL in output** - Prompt doesn't request patent URLs
5. ⚠️ **Inefficient rate limiting** - 21+ seconds of artificial delays

---

## Problem 1: Google Patents Scraping Failure (CRITICAL)

### Current Issue
```python
# patent_search.py:19-52
response = requests.get(search_url, headers=headers, timeout=10)
# Returns: 403 Client Error: Forbidden
```

**Impact**: Zero patents retrieved → No analysis possible → Pipeline fails immediately

### Root Cause
- Google Patents actively blocks web scraping
- Basic User-Agent header insufficient
- No CAPTCHA handling, session management, or proxy rotation

### Solution Options

#### Option A: Use USPTO PatentsView API (RECOMMENDED)
**Free, official, no authentication required**

```python
import requests

class PatentsViewSearcher:
    """Official USPTO PatentsView API"""
    BASE_URL = "https://api.patentsview.org/patents/query"

    def search(self, query: str, max_results: int = 20):
        """Search using PatentsView API"""
        payload = {
            "q": {"_text_any": {"patent_abstract": query}},
            "f": [
                "patent_number", "patent_title", "patent_abstract",
                "patent_date", "inventor_first_name", "inventor_last_name",
                "assignee_organization", "cpc_subgroup_id"
            ],
            "o": {"per_page": max_results}
        }

        response = requests.post(self.BASE_URL, json=payload)
        response.raise_for_status()

        data = response.json()
        patents = data.get('patents', [])

        return [
            {
                'patent_number': p['patent_number'],
                'title': p['patent_title'],
                'abstract': p['patent_abstract'],
                'publication_date': p['patent_date'],
                'inventors': [
                    f"{i['inventor_first_name']} {i['inventor_last_name']}"
                    for i in p.get('inventors', [])
                ],
                'assignee': p.get('assignee_organization', 'N/A'),
                'cpc_codes': [c['cpc_subgroup_id'] for c in p.get('cpcs', [])],
                'url': f"https://patents.google.com/patent/{p['patent_number']}"
            }
            for p in patents
        ]
```

**Pros**:
- ✅ Free and official
- ✅ No authentication needed
- ✅ Returns structured JSON (no HTML parsing)
- ✅ Includes abstract, claims, inventors, assignees
- ✅ Full-text search support
- ✅ Rate limit: 45 requests/minute

**Cons**:
- ⚠️ US patents only (no EP, WO, CN)
- ⚠️ Claims require separate endpoint

#### Option B: EPO OPS API (For European Patents)
**Free tier: 4GB/week**

```python
# Requires registration at: https://developers.epo.org/
# Get consumer_key and consumer_secret

import requests
import base64

class EPOSearcher:
    BASE_URL = "https://ops.epo.org/3.2/rest-services"
    AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"

    def __init__(self, consumer_key: str, consumer_secret: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = self._get_access_token()

    def _get_access_token(self):
        """Get OAuth token"""
        credentials = f"{self.consumer_key}:{self.consumer_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()

        headers = {
            'Authorization': f'Basic {encoded}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        response = requests.post(
            self.AUTH_URL,
            headers=headers,
            data={'grant_type': 'client_credentials'}
        )
        return response.json()['access_token']

    def search(self, query: str, max_results: int = 20):
        """Search EPO database"""
        headers = {'Authorization': f'Bearer {self.access_token}'}

        # Full-text search in abstract
        search_url = f"{self.BASE_URL}/published-data/search"
        params = {
            'q': f'txt={query}',
            'Range': f'1-{max_results}'
        }

        response = requests.get(search_url, headers=headers, params=params)
        # Parse XML response and extract patent details...
```

**Pros**:
- ✅ Includes EP, WO, US, CN, JP, KR patents (global coverage)
- ✅ Official API with high reliability
- ✅ Full-text search in abstracts, claims, descriptions

**Cons**:
- ⚠️ Requires registration and API keys
- ⚠️ Returns XML (need parsing)
- ⚠️ Rate limits stricter than PatentsView

#### Option C: Lens.org API (BEST for Production)
**Free tier: 10k requests/month**

```python
class LensSearcher:
    """Lens.org Scholarly API - Best for production"""
    BASE_URL = "https://api.lens.org/patent/search"

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }

    def search(self, query: str, max_results: int = 20):
        """Search Lens.org database"""
        payload = {
            "query": {
                "match": {
                    "abstract": query
                }
            },
            "size": max_results,
            "include": [
                "lens_id", "doc_number", "title", "abstract",
                "date_published", "inventor", "applicant", "cpc_classifications"
            ]
        }

        response = requests.post(
            self.BASE_URL,
            headers=self.headers,
            json=payload
        )

        data = response.json()
        # Parse and return results...
```

**Pros**:
- ✅ Global coverage (100+ patent offices)
- ✅ Clean JSON API
- ✅ Semantic search support
- ✅ High quality data
- ✅ Generous free tier

**Cons**:
- ⚠️ Requires API key registration

### Recommended Implementation Path

1. **Immediate fix**: Use PatentsView API (no registration needed)
2. **Production**: Switch to Lens.org (better coverage, semantic search)
3. **Future**: Add EPO OPS for European patent-specific searches

---

## Problem 2: No CLI Argument Support

### Current Issue
```bash
$ python src/main.py --llm-web-search --input data/sample_invention.json
# ❌ Flags are ignored - no argparse implementation
```

### Fix: Add CLI Argument Parser

```python
# main.py - Add at top
import argparse

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Patent Prior Art Search using LLM'
    )

    parser.add_argument(
        '--input', '-i',
        type=str,
        required=True,
        help='Path to invention disclosure JSON file'
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default='output/results.json',
        help='Path to output results JSON file'
    )

    parser.add_argument(
        '--max-patents',
        type=int,
        default=15,
        help='Maximum number of patents to analyze (default: 15)'
    )

    parser.add_argument(
        '--max-queries',
        type=int,
        default=3,
        help='Maximum search queries to execute (default: 3)'
    )

    parser.add_argument(
        '--llm-web-search',
        action='store_true',
        help='Enable LLM web search for additional context (not implemented yet)'
    )

    parser.add_argument(
        '--model',
        type=str,
        choices=['gpt-4o-mini', 'gpt-4o', 'claude-sonnet-4', 'claude-opus-4'],
        help='LLM model to use (overrides .env DEFAULT_MODEL)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )

    return parser.parse_args()

# Update main() function
def main():
    """Run the POC"""
    args = parse_args()

    poc = PatentSearchPOC(model=args.model, verbose=args.verbose)

    report = poc.run(
        invention_file=args.input,
        output_file=args.output,
        max_patents=args.max_patents,
        max_queries=args.max_queries
    )

    print("\n✅ POC completed successfully!")

# Update PatentSearchPOC.__init__
def __init__(self, model: str = None, verbose: bool = False):
    """Initialize POC"""
    load_dotenv()
    self.llm = LLMClient(model=model)
    self.searcher = GooglePatentsSearcher()
    self.verbose = verbose

# Update run() method signature
def run(self, invention_file: str, output_file: str = None,
        max_patents: int = 15, max_queries: int = 3):
    # ... rest of implementation
    for query in queries[:max_queries]:  # Use parameter instead of hardcoded 3
        # ...

    for i, patent in enumerate(unique_patents[:max_patents]):  # Use parameter
        # ...
```

**Usage after fix**:
```bash
# Basic usage
python src/main.py --input data/sample_invention.json

# Advanced usage
python src/main.py \
  --input data/sample_invention.json \
  --output results/my_analysis.json \
  --max-patents 20 \
  --max-queries 5 \
  --model gpt-4o \
  --verbose
```

---

## Problem 3: Sequential LLM Calls (Performance Bottleneck)

### Current Issue
```python
# main.py:157-172
for i, patent in enumerate(patents):  # 15 iterations
    analysis = self._analyze_single_patent(invention, patent)  # 3-5 sec each
    patent['analysis'] = analysis
# Total: 45-75 seconds
```

**Impact**: 15 patents × 4 sec average = **60 seconds** of analysis time

### Fix: Parallel LLM Calls

#### Option A: Thread Pool (Simple, 3-5x speedup)

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _analyze_patents(self, invention: Dict, patents: List[Dict]) -> List[Dict]:
    """Analyze patents in parallel using threads"""
    analyzed = []

    # Use thread pool for I/O-bound LLM calls
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all analysis jobs
        future_to_patent = {
            executor.submit(self._analyze_single_patent, invention, patent): patent
            for patent in patents
        }

        # Collect results as they complete
        for i, future in enumerate(as_completed(future_to_patent), 1):
            patent = future_to_patent[future]
            print(f"   Analyzed {i}/{len(patents)} patents", end='\r')

            try:
                analysis = future.result()
                patent['analysis'] = analysis
                analyzed.append(patent)
            except Exception as e:
                print(f"\n   ⚠ Error analyzing {patent.get('patent_number')}: {e}")
                patent['analysis'] = {
                    'relevance_score': 0.0,
                    'classification': 'not_relevant',
                    'analysis': f'Analysis failed: {e}',
                    'key_differences': 'Unknown'
                }
                analyzed.append(patent)

    # Sort by relevance score
    analyzed.sort(key=lambda x: x['analysis'].get('relevance_score', 0), reverse=True)

    return analyzed
```

**Performance**:
- Before: 15 patents × 4 sec = **60 seconds**
- After: 15 patents ÷ 5 workers × 4 sec = **12 seconds** (5x speedup)

#### Option B: Async/Await (Best for APIs that support it)

```python
import asyncio
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

class AsyncLLMClient:
    """Async LLM client for parallel calls"""

    def __init__(self, model: str = None):
        self.model = model or os.getenv('DEFAULT_MODEL', 'gpt-4o-mini')

        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        openai_key = os.getenv('OPENAI_API_KEY')

        if anthropic_key:
            self.anthropic = AsyncAnthropic(api_key=anthropic_key)
        if openai_key:
            self.openai = AsyncOpenAI(api_key=openai_key)

    async def generate(self, prompt: str, max_tokens: int = 4000,
                      temperature: float = 0.3) -> str:
        """Generate completion asynchronously"""
        if 'claude' in self.model.lower():
            message = await self.anthropic.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        elif 'gpt' in self.model.lower():
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response.choices[0].message.content

# Update PatentSearchPOC
async def _analyze_patents_async(self, invention: Dict, patents: List[Dict]) -> List[Dict]:
    """Analyze patents in parallel using async"""
    # Create all tasks
    tasks = [
        self._analyze_single_patent_async(invention, patent)
        for patent in patents
    ]

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    analyzed = []
    for patent, result in zip(patents, results):
        if isinstance(result, Exception):
            patent['analysis'] = {
                'relevance_score': 0.0,
                'classification': 'not_relevant',
                'analysis': f'Analysis failed: {result}',
                'key_differences': 'Unknown'
            }
        else:
            patent['analysis'] = result
        analyzed.append(patent)

    # Sort by relevance
    analyzed.sort(key=lambda x: x['analysis'].get('relevance_score', 0), reverse=True)
    return analyzed

async def _analyze_single_patent_async(self, invention: Dict, patent: Dict) -> Dict:
    """Analyze single patent asynchronously"""
    prompt = f"""..."""  # Same prompt as before

    response = await self.llm.generate(prompt, max_tokens=800, temperature=0.2)
    # Parse and return...
```

**Performance**:
- Before: 15 patents × 4 sec = **60 seconds**
- After: 15 patents in parallel = **~4 seconds** (15x speedup!)

**Recommendation**: Use ThreadPoolExecutor (Option A) for simplest implementation with good performance gains.

---

## Problem 4: Missing URL in LLM Output

### Current Issue
The analysis prompt doesn't request URLs:

```python
# main.py:203-209
Return ONLY valid JSON in this exact format:
{
  "relevance_score": 0.X,
  "classification": "blocking|relevant|related|not_relevant",
  "analysis": "Brief analysis here",
  "key_differences": "Key differences here"
}
# ❌ No "url" field!
```

### Fix Option 1: Don't Ask LLM for URLs (RECOMMENDED)

URLs are already in patent data - just preserve them:

```python
def _analyze_single_patent(self, invention: Dict, patent: Dict) -> Dict:
    """Analyze a single patent against the invention"""
    prompt = f"""
    ... (same prompt) ...

    Return ONLY valid JSON in this exact format:
    {{
      "relevance_score": 0.X,
      "classification": "blocking|relevant|related|not_relevant",
      "analysis": "Brief analysis here",
      "key_differences": "Key differences here"
    }}
    """

    try:
        response = self.llm.generate(prompt, max_tokens=800, temperature=0.2)
        # Parse JSON
        response = response.strip()
        if response.startswith('```'):
            response = response.split('```')[1]
            if response.startswith('json'):
                response = response[4:]

        analysis = json.loads(response)

        # ✅ ADD URL from patent data (don't ask LLM to generate it)
        analysis['url'] = patent.get('url', f"https://patents.google.com/patent/{patent.get('patent_number', '')}")
        analysis['patent_number'] = patent.get('patent_number', 'Unknown')
        analysis['title'] = patent.get('title', 'N/A')

        return analysis

    except Exception as e:
        return {
            'relevance_score': 0.0,
            'classification': 'not_relevant',
            'analysis': 'Analysis failed',
            'key_differences': 'Unknown',
            'url': patent.get('url', ''),  # ✅ Include even on error
            'patent_number': patent.get('patent_number', 'Unknown'),
            'title': patent.get('title', 'N/A')
        }
```

**Why this is better**:
- ✅ No risk of LLM hallucinating URLs
- ✅ Faster (smaller response)
- ✅ More reliable (URLs come from source data)

### Fix Option 2: Ask LLM to Include URL (Not Recommended)

Only if you really want LLM to return it:

```python
prompt = f"""
...

Return ONLY valid JSON in this exact format:
{{
  "patent_number": "{patent.get('patent_number', 'Unknown')}",
  "url": "{patent.get('url', 'N/A')}",
  "relevance_score": 0.X,
  "classification": "blocking|relevant|related|not_relevant",
  "analysis": "Brief analysis here",
  "key_differences": "Key differences here"
}}

IMPORTANT: Use the exact patent_number and url values provided above.
"""
```

**Why avoid this**:
- ⚠️ LLM might modify or hallucinate URLs
- ⚠️ Wastes tokens
- ⚠️ Increases error risk

---

## Problem 5: Inefficient Rate Limiting

### Current Issue
```python
# main.py:56-72
for query in queries[:3]:
    patents = self.searcher.search(query, max_results=10)
    time.sleep(2)  # ← 2 sec × 3 queries = 6 seconds wasted

for patent in unique_patents[:15]:
    details = self.searcher.get_patent_details(patent['patent_number'])
    time.sleep(1)  # ← 1 sec × 15 patents = 15 seconds wasted
```

**Total artificial delay: 21+ seconds** (on top of actual network/API time)

### Fix: Intelligent Rate Limiting

```python
import time
from datetime import datetime, timedelta

class RateLimiter:
    """Intelligent rate limiter"""

    def __init__(self, max_requests: int, time_window: int):
        """
        Args:
            max_requests: Maximum requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    def wait_if_needed(self):
        """Wait only if rate limit would be exceeded"""
        now = datetime.now()

        # Remove old requests outside time window
        self.requests = [
            req_time for req_time in self.requests
            if now - req_time < timedelta(seconds=self.time_window)
        ]

        # Check if we need to wait
        if len(self.requests) >= self.max_requests:
            # Calculate wait time
            oldest_request = self.requests[0]
            wait_time = (oldest_request + timedelta(seconds=self.time_window) - now).total_seconds()

            if wait_time > 0:
                print(f"   ⏳ Rate limit: waiting {wait_time:.1f}s")
                time.sleep(wait_time)
                self.requests.pop(0)  # Remove oldest

        # Record this request
        self.requests.append(datetime.now())

# Usage in PatentSearchPOC
def __init__(self):
    load_dotenv()
    self.llm = LLMClient()
    self.searcher = GooglePatentsSearcher()

    # PatentsView: 45 requests/minute
    self.rate_limiter = RateLimiter(max_requests=45, time_window=60)

def run(self, invention_file: str, output_file: str = None):
    # ... existing code ...

    # Step 3: Search patents
    print("\n[STEP 3] Searching patent databases...")
    all_patents = []
    for query in queries[:3]:
        self.rate_limiter.wait_if_needed()  # ✅ Intelligent wait
        patents = self.searcher.search(query, max_results=10)
        all_patents.extend(patents)
        # ❌ Remove: time.sleep(2)  # No longer needed!

    # Step 4: Fetch patent details
    print("\n[STEP 4] Fetching patent details...")
    detailed_patents = []
    for i, patent in enumerate(unique_patents[:15], 1):
        self.rate_limiter.wait_if_needed()  # ✅ Intelligent wait
        details = self.searcher.get_patent_details(patent['patent_number'])
        detailed_patents.append(details)
        # ❌ Remove: time.sleep(1)  # No longer needed!
```

**Performance**:
- Before: 21 seconds of fixed delays
- After: Only waits when actually needed (often 0-2 seconds total)

---

## Complete Implementation Roadmap

### Phase 1: Critical Fixes (1-2 hours)

1. ✅ Replace Google Patents scraping with PatentsView API
2. ✅ Add CLI argument parsing
3. ✅ Fix URL in analysis output (preserve from source data)

### Phase 2: Performance Optimization (2-3 hours)

4. ✅ Implement parallel LLM analysis (ThreadPoolExecutor)
5. ✅ Replace fixed delays with intelligent rate limiting
6. ✅ Add progress bars for better UX

### Phase 3: Enhancement (3-4 hours)

7. ✅ Add caching for LLM responses
8. ✅ Implement retry logic with exponential backoff
9. ✅ Add structured logging
10. ✅ Add unit tests

### Expected Performance After All Fixes

| Stage | Before | After | Improvement |
|-------|--------|-------|-------------|
| Patent search | **FAILS** | 3-5 sec | ✅ Works |
| Detail fetching | 15 sec + delays | 2-3 sec | **5x faster** |
| LLM analysis | 60 sec | 12 sec | **5x faster** |
| **Total** | **FAILS** | **20 sec** | **✅ 3x faster + works!** |

---

## Quick Start: Minimal Working Version

Here's the absolute minimum changes to get it working:

### 1. Replace patent_search.py with PatentsView API

```python
"""
Patent search using PatentsView API
"""
import requests
from typing import List, Dict
import time

class PatentsViewSearcher:
    """
    Official USPTO PatentsView API
    Free, no authentication required
    """

    BASE_URL = "https://api.patentsview.org/patents/query"

    def search(self, query: str, max_results: int = 20) -> List[Dict]:
        """Search PatentsView API"""
        print(f"🔍 Searching PatentsView for: '{query}'")

        payload = {
            "q": {"_text_any": {"patent_abstract": query}},
            "f": [
                "patent_number", "patent_title", "patent_abstract",
                "patent_date", "inventor_first_name", "inventor_last_name",
                "assignee_organization"
            ],
            "o": {"per_page": max_results}
        }

        try:
            response = requests.post(self.BASE_URL, json=payload, timeout=15)
            response.raise_for_status()

            data = response.json()
            patents = data.get('patents', [])

            results = []
            for p in patents:
                results.append({
                    'patent_number': p.get('patent_number', 'Unknown'),
                    'title': p.get('patent_title', 'N/A'),
                    'abstract': p.get('patent_abstract', 'N/A'),
                    'publication_date': p.get('patent_date', 'N/A'),
                    'url': f"https://patents.google.com/patent/{p.get('patent_number', '')}"
                })

            print(f"✓ Found {len(results)} patents")
            return results

        except Exception as e:
            print(f"✗ Search error: {e}")
            return []

    def get_patent_details(self, patent_number: str) -> Dict:
        """Get detailed information for a specific patent"""
        print(f"📄 Fetching details for {patent_number}")

        payload = {
            "q": {"patent_number": patent_number},
            "f": [
                "patent_number", "patent_title", "patent_abstract",
                "patent_date", "inventor_first_name", "inventor_last_name",
                "assignee_organization", "cpc_subgroup_id", "claims"
            ]
        }

        try:
            response = requests.post(self.BASE_URL, json=payload, timeout=15)
            response.raise_for_status()

            data = response.json()
            patents = data.get('patents', [])

            if not patents:
                return {'patent_number': patent_number, 'error': 'Not found'}

            p = patents[0]

            # Get first claim
            claims = p.get('claims', [])
            claim_1 = claims[0].get('claim_text', 'N/A') if claims else 'N/A'

            return {
                'patent_number': patent_number,
                'title': p.get('patent_title', 'N/A'),
                'abstract': p.get('patent_abstract', 'N/A'),
                'publication_date': p.get('patent_date', 'N/A'),
                'inventors': [
                    f"{i.get('inventor_first_name', '')} {i.get('inventor_last_name', '')}"
                    for i in p.get('inventors', [])
                ],
                'assignee': p.get('assignee_organization', 'N/A'),
                'cpc_codes': [c.get('cpc_subgroup_id', '') for c in p.get('cpcs', [])],
                'claim_1': claim_1,
                'url': f"https://patents.google.com/patent/{patent_number}"
            }

        except Exception as e:
            print(f"✗ Error fetching details: {e}")
            return {'patent_number': patent_number, 'error': str(e)}
```

### 2. Update main.py imports

```python
# Change line 16:
# from patent_search import GooglePatentsSearcher
from patent_search import PatentsViewSearcher

# Change line 27:
# self.searcher = GooglePatentsSearcher()
self.searcher = PatentsViewSearcher()
```

### 3. Add URL to analysis output

In `_analyze_single_patent()` method, after parsing JSON:

```python
analysis = json.loads(response)

# ✅ Add these lines:
analysis['url'] = patent.get('url', '')
analysis['patent_number'] = patent.get('patent_number', 'Unknown')

return analysis
```

### 4. Test

```bash
cd /home/user/InventionID/patent-search-poc
python src/main.py
```

This minimal fix will:
- ✅ Actually fetch patents (no more 403 errors)
- ✅ Include URLs in output
- ✅ Complete the full analysis pipeline

---

## Summary

The main issues preventing the system from working are:

1. **Google Patents scraping fails** → Use PatentsView API instead
2. **Missing CLI support** → Add argparse
3. **Slow sequential LLM calls** → Use ThreadPoolExecutor for 5x speedup
4. **URLs not in output** → Preserve them from source data
5. **Wasteful rate limiting** → Use intelligent rate limiter

Implementing just fixes #1 and #4 will make the system functional. Adding fixes #2, #3, and #5 will make it production-ready with 3-5x better performance.
