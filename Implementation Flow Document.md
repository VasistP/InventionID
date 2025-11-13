# **Implementation Flow Document**

## **File Structure**

```
src/
├── config.py                          # Central configuration
├── main.py                            # Modified entry point
├── llm_client.py                      # Existing (minimal changes)
├── patent_search.py                   # Modified - IDs/URLs only
│
├── modules/                           # New modular components
│   ├── __init__.py
│   ├── rate_limiter.py               # Rate limiting module
│   ├── batch_processor.py            # Batch processing module
│   ├── text_summarizer.py            # Text compression module
│   ├── embedding_filter.py           # Semantic filtering module
│   └── patent_analyzer.py            # Patent detail analysis module
│
└── utils/
    ├── __init__.py
    └── prompt_templates.py            # Batch prompt templates
```

---

## **Module Purposes**

| Module | Purpose | Can Disable? | Flag |
|--------|---------|--------------|------|
| `rate_limiter.py` | Enforces API rate limits | No (core) | - |
| `batch_processor.py` | Batches patents for processing | Yes | `USE_BATCHING` |
| `text_summarizer.py` | Compresses abstracts/claims | Yes | `USE_SUMMARIZATION` |
| `embedding_filter.py` | Pre-filters patents by similarity | Yes | `USE_EMBEDDING_FILTER` |
| `patent_analyzer.py` | Fetches & analyzes patent details | Yes | `USE_DETAILED_ANALYSIS` |

---

## **Module Dependency Map**

### **Dependency Graph:**

```
llm_client.py (External APIs)
    ↑
    │
    ├─── rate_limiter.py
    │    (wraps llm_client calls)
    │
    ├─── batch_processor.py
    │    ├─ NEEDS: llm_client
    │    └─ NEEDS: rate_limiter
    │
    ├─── patent_analyzer.py
    │    ├─ NEEDS: llm_client
    │    ├─ NEEDS: rate_limiter
    │    ├─ OPTIONAL: batch_processor (if USE_BATCHING)
    │    └─ OPTIONAL: text_summarizer (if USE_SUMMARIZATION)
    │
    └─── patent_search.py
         ├─ NEEDS: llm_client (for LLM mode)
         └─ OPTIONAL: rate_limiter (if USE_RATE_LIMITING)

text_summarizer.py
    └─ INDEPENDENT (only uses sumy/gensim)

embedding_filter.py
    └─ INDEPENDENT (only uses sentence-transformers)

main.py
    ├─ NEEDS: llm_client
    ├─ NEEDS: patent_search
    ├─ OPTIONAL: rate_limiter
    ├─ OPTIONAL: embedding_filter
    ├─ OPTIONAL: patent_analyzer
    └─ Orchestrates all modules
```

---

## **Detailed Dependencies:**

### **1. rate_limiter.py**
**Depends on:** Nothing (self-contained)
**Purpose:** Tracks timing, enforces delays
**Can be removed?** Yes - system works without it (but hits rate limits)

---

### **2. text_summarizer.py**
**Depends on:** 
- `sumy` library
- `nltk` library

**Purpose:** Text compression
**Can be removed?** Yes - use full text instead
**Independent?** ✅ YES - No dependencies on other modules

---

### **3. embedding_filter.py**
**Depends on:**
- `sentence-transformers` library
- `numpy` library

**Purpose:** Semantic filtering
**Can be removed?** Yes - process all patents instead
**Independent?** ✅ YES - No dependencies on other modules

---

### **4. batch_processor.py**
**Depends on:**
- `llm_client` (to make API calls)
- `rate_limiter` (to enforce delays)

**Purpose:** Batch multiple items into single API call
**Can be removed?** Yes - use individual processing
**Independent?** ❌ NO - Needs llm_client and rate_limiter

---

### **5. patent_analyzer.py**
**Depends on:**
- `llm_client` (to make API calls)
- `rate_limiter` (to enforce delays)
- `batch_processor` (optional - only if USE_BATCHING)
- `text_summarizer` (optional - only if USE_SUMMARIZATION)

**Purpose:** Fetch and analyze patent details
**Can be removed?** Yes - skip detailed analysis
**Independent?** ❌ NO - Needs llm_client and rate_limiter

---

### **6. patent_search.py**
**Depends on:**
- `llm_client` (for LLM search mode)
- `requests` + `BeautifulSoup` (for scraping mode)
- `rate_limiter` (optional - if USE_RATE_LIMITING)

**Purpose:** Search for patent IDs
**Can be removed?** No - core functionality
**Independent?** ❌ PARTIAL - Can work without rate_limiter

---

### **7. llm_client.py**
**Depends on:**
- `anthropic` library
- `openai` library

**Purpose:** Make API calls
**Can be removed?** No - core functionality
**Independent?** ✅ YES -底层基础模块

---

## **Summary by Independence Level:**

| Module | Fully Independent? | Dependencies | Can Disable? |
|--------|-------------------|--------------|--------------|
| `llm_client` | ✅ YES | External APIs only | No |
| `rate_limiter` | ✅ YES | None | Yes |
| `text_summarizer` | ✅ YES | External libraries only | Yes |
| `embedding_filter` | ✅ YES | External libraries only | Yes |
| `patent_search` | 🟡 PARTIAL | llm_client, (rate_limiter) | No |
| `batch_processor` | ❌ NO | llm_client, rate_limiter | Yes |
| `patent_analyzer` | ❌ NO | llm_client, rate_limiter, (batch_processor), (text_summarizer) | Yes |

**Legend:**
- ✅ YES = No dependencies on other custom modules
- 🟡 PARTIAL = Some optional dependencies
- ❌ NO = Hard dependencies on other modules
- (parentheses) = Optional dependency

---

## **Config.py Structure**

```
# Feature Flags
USE_BATCHING = True
USE_SUMMARIZATION = True
USE_EMBEDDING_FILTER = True
USE_DETAILED_ANALYSIS = True          # NEW
USE_RATE_LIMITING = True

# Rate Limiting
RATE_LIMIT_RPM = 50
MIN_REQUEST_INTERVAL = 1.2

# Batching
BATCH_SIZE_ANALYSIS = 3
BATCH_SIZE_DETAILS = 5
BATCH_SIZE_SEARCH = 1

# Patent Processing Limits                # NEW SECTION
MAX_PATENTS_TO_FETCH = 50               # From search
MAX_PATENTS_TO_ANALYZE = 15             # After filtering
MAX_PATENTS_FOR_DETAILED_ANALYSIS = 10  # Deep dive with claims

# Summarization
SUMMARIZER_METHOD = "textrank"
MAX_ABSTRACT_SENTENCES = 3
MAX_CLAIM_SENTENCES = 5

# Embedding Filter
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD = 0.3
TOP_K_PATENTS = 15
```

---

## **Module Details**

### **Phase 1: Rate Limiting (Required)**

**File:** `modules/rate_limiter.py`

**Components:**
- `RateLimiter` class
  - `acquire()` - Wait until safe to proceed
  - `_calculate_wait_time()` - Check request history
  - `_record_request()` - Update timestamps

---

### **Phase 2: Patent Search (Modified - Lightweight)**

**File:** `patent_search.py` (Modified)

**Changes:**
- Search returns **only**: `patent_number`, `url`, `title` (if available)
- Remove detailed scraping/fetching from search phase
- Remove `get_patent_details()` method (moved to patent_analyzer)

**Methods:**
- `search()` - Returns list of `{patent_number, url, title}`
- `_search_with_llm()` - Lightweight search
- `_search_with_scraping()` - Lightweight scraping

**Output Example:**
```
[
  {"patent_number": "US10123456B2", "url": "https://...", "title": "..."},
  {"patent_number": "US10123457B2", "url": "https://...", "title": "..."}
]
```

---

### **Phase 3: Embedding Filter (Optional)**

**File:** `modules/embedding_filter.py`

**Components:**
- `EmbeddingFilter` class
  - `filter_patents(invention_desc, patents)` - Uses title only
  - `_compute_embeddings(texts)` - Embed invention + titles
  - `_calculate_similarities()` - Cosine similarity
  - `_rank_and_filter()` - Return top K patent IDs

**Input:** List of `{patent_number, url, title}`
**Output:** Filtered list (top 15 patents)

---

### **Phase 4: Patent Detail Analyzer (Optional - NEW)**

**File:** `modules/patent_analyzer.py`

**Components:**
- `PatentAnalyzer` class
  - `__init__(llm_client, rate_limiter, summarizer)`
  - `fetch_patent_details(patent_numbers)` - Get abstracts/claims
  - `analyze_patents(invention, patents)` - Compare with invention
  - `_fetch_single_patent(patent_number)` - Scrape or LLM fetch
  - `_analyze_single_patent(invention, patent)` - Relevance scoring
  - `_batch_fetch_details(patent_numbers)` - Batch fetching
  - `_batch_analyze(invention, patents)` - Batch analysis

**Behavior:**
- If `USE_DETAILED_ANALYSIS = False`: Skip this entirely, return patent list
- If `True`: Fetch details for top N patents only

**Methods:**

1. **`fetch_patent_details(patent_numbers)`**
   - Input: List of patent numbers
   - Fetches: abstract, claims, metadata
   - Uses: Batching if enabled
   - Output: List of detailed patent objects

2. **`analyze_patents(invention, patents)`**
   - Input: Invention + detailed patents
   - Analyzes: Relevance, overlap, blocking risk
   - Uses: Batching if enabled
   - Output: Patents with analysis scores

---

### **Phase 5: Text Summarization (Optional)**

**File:** `modules/text_summarizer.py`

**Integration:** 
- Used by `patent_analyzer.py` after fetching details
- Compresses abstract/claims before analysis

---

### **Phase 6: Batch Processing (Optional)**

**File:** `modules/batch_processor.py`

**Components:**
- `BatchProcessor` class
  - `batch_search(queries)` - Combine search queries
  - `batch_fetch_details(patent_numbers)` - Fetch in groups
  - `batch_analyze_patents(invention, patents)` - Analyze in groups

**Used by:** `patent_analyzer.py` if `USE_BATCHING = True`

---

## **Complete Function Call Flow**

### **Scenario 1: All Features Enabled**

```
main.py::run(invention)
│
├─ Step 1: Generate Search Queries
│   └─ rate_limiter.acquire() → llm_client.generate()
│   └─ Returns: ["query1", "query2", ...]
│
├─ Step 2: Search Patents (lightweight - IDs/URLs only)
│   └─ patent_search.search(queries, max_results=50)
│       └─ Returns: [{patent_number, url, title}, ...] x50
│
├─ Step 3: Pre-filter with Embeddings (optional)
│   └─ If USE_EMBEDDING_FILTER:
│       └─ embedding_filter.filter_patents(invention, 50_patents)
│           └─ Uses titles only for similarity
│           └─ Returns: top 15 patents
│   └─ Else: Use all 50 (or config limit)
│
├─ Step 4: Detailed Analysis (optional)
│   └─ If USE_DETAILED_ANALYSIS:
│       │
│       ├─ 4a: Fetch Patent Details
│       │   └─ patent_analyzer.fetch_patent_details(top_10_numbers)
│       │       └─ If USE_BATCHING:
│       │           └─ batch_processor.batch_fetch_details([10 patents])
│       │               └─ Split into 2 batches of 5
│       │               └─ rate_limiter.acquire() → llm_client.generate()
│       │       └─ Returns: [{abstract, claims, metadata}, ...] x10
│       │
│       ├─ 4b: Summarize (optional)
│       │   └─ If USE_SUMMARIZATION:
│       │       └─ text_summarizer.summarize_text(abstract, 3)
│       │       └─ text_summarizer.summarize_text(claim_1, 5)
│       │
│       └─ 4c: Analyze Patents
│           └─ patent_analyzer.analyze_patents(invention, 10_patents)
│               └─ If USE_BATCHING:
│                   └─ batch_processor.batch_analyze_patents()
│                       └─ Split into 4 batches of 3
│                       └─ rate_limiter.acquire() → llm_client.generate()
│               └─ Returns: [{analysis, score}, ...] x10
│   │
│   └─ Else: Return filtered list without analysis
│
└─ Step 5: Generate Report
    └─ Format results based on what was enabled
```

---

### **Scenario 2: Basic Mode (Only Search + Filter)**

```
Set: USE_DETAILED_ANALYSIS = False

main.py::run(invention)
│
├─ Generate queries → llm_client
├─ Search patents → [{id, url, title}] x50
├─ Filter with embeddings → top 15 patents
└─ Return patent list (no detailed analysis)
```

**Output:** List of patent IDs with URLs and similarity scores only
**Use case:** Quick scan, save detailed analysis for later

---

### **Scenario 3: Full Analysis on Pre-selected Patents**

```
Set: USE_DETAILED_ANALYSIS = True
     MAX_PATENTS_FOR_DETAILED_ANALYSIS = 5

main.py::run(invention)
│
├─ Search → 50 patents
├─ Filter → 15 patents
└─ Detailed analysis on top 5 only
    ├─ Fetch details for 5
    ├─ Summarize
    └─ Analyze relevance
```

**Use case:** Budget-conscious mode, analyze only highest probability patents

---

## **API Call Reduction**

| Stage | Before | After (All Features) | After (Basic Mode) |
|-------|--------|----------------------|--------------------|
| Search queries | 5 calls | 1 call | 1 call |
| Filter patents | N/A | 0 (local) | 0 (local) |
| Fetch details | 20 calls | 2 calls | 0 calls |
| Analyze patents | 20 calls | 4 calls | 0 calls |
| **Total** | **45 calls** | **7 calls** | **1 call** |
| **Cost** | $X | $0.16X | $0.02X |

---

## **Configuration Examples**

### **Quick Scan Mode:**
```python
USE_DETAILED_ANALYSIS = False
MAX_PATENTS_TO_FETCH = 100
# Returns: 100 patent IDs with similarity scores
```

### **Budget Mode:**
```python
USE_DETAILED_ANALYSIS = True
MAX_PATENTS_FOR_DETAILED_ANALYSIS = 5
USE_BATCHING = True
# Analyzes only top 5 patents
```

### **Comprehensive Mode:**
```python
USE_DETAILED_ANALYSIS = True
MAX_PATENTS_FOR_DETAILED_ANALYSIS = 20
USE_BATCHING = True
USE_SUMMARIZATION = True
# Full analysis on 20 patents
```

### **Speed Mode:**
```python
USE_EMBEDDING_FILTER = True
USE_DETAILED_ANALYSIS = False
# Fast filtering, no API calls for analysis
```

---

## **Main.py Integration Points**

### **Modified run() method:**

```
def run(invention_file, output_file):
    # Step 1: Generate queries (always)
    queries = _generate_search_queries(invention)
    
    # Step 2: Search (lightweight - IDs only)
    all_patents = patent_search.search(queries, max_results=MAX_PATENTS_TO_FETCH)
    
    # Step 3: Filter (optional)
    if USE_EMBEDDING_FILTER:
        filtered_patents = embedding_filter.filter_patents(invention, all_patents)
    else:
        filtered_patents = all_patents[:MAX_PATENTS_TO_ANALYZE]
    
    # Step 4: Detailed analysis (optional)
    if USE_DETAILED_ANALYSIS:
        top_patents = filtered_patents[:MAX_PATENTS_FOR_DETAILED_ANALYSIS]
        detailed = patent_analyzer.fetch_patent_details(top_patents)
        analyzed = patent_analyzer.analyze_patents(invention, detailed)
    else:
        analyzed = filtered_patents  # Just patent IDs with similarity scores
    
    # Step 5: Generate report
    report = _generate_report(invention, analyzed)
    return report
```

---

## **Patent Analyzer Module Details**

### **File:** `modules/patent_analyzer.py`

**Class:** `PatentAnalyzer`

**Constructor:**
```
__init__(llm_client, rate_limiter, config):
    - Store references
    - Initialize batch_processor if USE_BATCHING
    - Initialize text_summarizer if USE_SUMMARIZATION
```

**Public Methods:**

1. **`fetch_patent_details(patent_list)`**
   - Input: `[{patent_number, url}, ...]`
   - If USE_BATCHING: Call batch_processor
   - Else: Loop with rate limiting
   - If USE_SUMMARIZATION: Apply after fetching
   - Output: `[{patent_number, abstract, claims, metadata}, ...]`

2. **`analyze_patents(invention, detailed_patents)`**
   - Input: Invention + list of detailed patents
   - If USE_BATCHING: Batch analyze
   - Else: Individual analysis with rate limiting
   - Output: `[{patent, analysis, score}, ...]` sorted by relevance

**Private Methods:**

3. **`_fetch_single_patent_with_llm(patent_number)`**
   - rate_limiter.acquire()
   - llm_client.generate(prompt)
   - Parse patent details from response

4. **`_fetch_single_patent_with_scraping(patent_url)`**
   - Traditional web scraping
   - No API calls

5. **`_analyze_single_patent(invention, patent)`**
   - rate_limiter.acquire()
   - llm_client.generate(comparison_prompt)
   - Parse relevance score and analysis

---

## **Fallback Logic**

### **If Detailed Analysis Disabled:**
```
Return early with patent list
  → Output: [{patent_number, url, title, embedding_score}]
  → No detail fetching
  → No relevance analysis
```

### **If Batching Fails:**
```
patent_analyzer._batch_fetch_details() fails
  → Fall back to _fetch_single_patent() loop
  → Apply rate limiting between calls
```

### **If LLM Fetch Fails:**
```
_fetch_single_patent_with_llm() fails
  → Try _fetch_single_patent_with_scraping()
  → If both fail: Return partial data with error flag
```

---

## **Implementation Order**

**Day 1:**
1. Create `config.py` with all flags
2. Modify `patent_search.py` - lightweight mode (IDs/URLs only)
3. Test search returns correct format

**Day 2:**
4. Create `modules/rate_limiter.py`
5. Create `modules/patent_analyzer.py` (basic version)
6. Test detail fetching with rate limiting

**Day 3:**
7. Create `modules/text_summarizer.py`
8. Integrate into patent_analyzer
9. Test summarization quality

**Day 4:**
10. Create `modules/embedding_filter.py`
11. Integrate between search and analysis
12. Test filtering accuracy

**Day 5:**
13. Create `modules/batch_processor.py`
14. Integrate into patent_analyzer
15. Test batch processing

**Day 6:**
16. Update `main.py` with new flow
17. Test all flag combinations
18. Performance benchmarking

---

## **Testing Matrix**

| Flag Combination | Expected Behavior | API Calls |
|------------------|-------------------|-----------|
| All disabled | Basic search only | 5 |
| Only embedding | Search + filter | 1 |
| Only detailed analysis | Search + analyze all | 45 |
| Embedding + detailed | Search + filter + analyze top 10 | 7 |
| All enabled + batching | Full pipeline optimized | 7 |

---

## **Output Formats**

### **Without Detailed Analysis:**
```json
{
  "search_metadata": {...},
  "patents": [
    {
      "patent_number": "US10123456B2",
      "url": "https://patents.google.com/patent/US10123456B2",
      "title": "Machine learning system...",
      "similarity_score": 0.85
    }
  ]
}
```

### **With Detailed Analysis:**
```json
{
  "search_metadata": {...},
  "patents": [
    {
      "patent_number": "US10123456B2",
      "url": "https://...",
      "title": "...",
      "abstract": "...",
      "claims": "...",
      "analysis": {
        "relevance_score": 0.92,
        "classification": "blocking",
        "analysis": "...",
        "key_differences": "..."
      }
    }
  ]
}
```

---

## **Monitoring Points**

Track these metrics per run:
- Patents searched
- Patents filtered (if embedding enabled)
- Patents analyzed (if detailed analysis enabled)
- API calls per stage
- Time per stage
- Batch success rate
- Fallback triggers

---

## **Migration Path**

### **From Existing Code:**

1. Keep current code as `main_legacy.py`
2. Implement new modules in parallel
3. Add feature flags to switch between old/new
4. Test with flag: `USE_NEW_PIPELINE = False` (uses legacy)
5. Gradually enable features one by one
6. Compare results quality
7. Remove legacy code when stable

---

## **Command Line Interface**

```bash
# Quick scan only
python main.py --mode scan --max-patents 100

# Basic analysis
python main.py --mode basic --analyze-top 10

# Full analysis
python main.py --mode full --analyze-top 20

# Custom flags
python main.py --no-embedding --no-batching --analyze-top 5
```

Add argument parser in `main.py` to set config flags from CLI.
