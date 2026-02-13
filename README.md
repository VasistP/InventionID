# Patent Prior Art Search Agent

## What Does This System Do?

Imagine you've invented something new — a device, a process, a piece of software. Before you can file a patent, you need to answer one critical question: **has someone already patented something similar?**

Answering that question today means hiring a patent attorney, spending weeks searching through millions of existing patents, and paying thousands of dollars. This system automates that entire process. You upload a research paper or technical document, and within minutes, it:

1. **Reads and understands** your invention
2. **Decides if it's patentable** — is this a genuine invention, or just a scientific discovery?
3. **Searches** millions of existing patents
4. **Analyzes** which patents might block yours
5. **Delivers a report** classifying each prior patent as blocking, relevant, or merely related

The entire pipeline is powered by large language models (LLMs) — the same technology behind ChatGPT and Claude — orchestrated through a multi-stage workflow with built-in quality checks.

---

## High-Level Architecture

The system has three layers:

```
 ┌─────────────────────────────────────────────────────────────┐
 │                     FRONTEND (React)                        │
 │   Upload PDF  →  Live Progress Bar  →  Results Dashboard    │
 └────────────────────────┬────────────────────────────────────┘
                          │ WebSocket (real-time updates)
                          │ REST API (upload, results)
 ┌────────────────────────▼────────────────────────────────────┐
 │                    BACKEND (FastAPI)                         │
 │   Receives PDF  →  Triggers Pipeline  →  Streams Progress   │
 └────────────────────────┬────────────────────────────────────┘
                          │
 ┌────────────────────────▼────────────────────────────────────┐
 │                 PIPELINE (Python, 6 Stages)                 │
 │                                                             │
 │  Stage 0: Extract text from PDF (AWS Textract)              │
 │  Stage 1: Understand the invention (Claude + ReAct Agent)   │
 │       └─► Patentability Gate: Is this actually patentable?  │
 │           YES → continue    NO → stop early                 │
 │  Stage 2: Generate patent search queries (Claude Sonnet)    │
 │  Stage 3: Search existing patents (Google Patents API)      │
 │  Stage 4: Fetch full patent details (Google Patents API)    │
 │  Stage 5: Analyze each patent vs. the invention (Claude)    │
 │  Stage 6: Generate final report (saved to S3)               │
 │                                                             │
 └─────────────────────────────────────────────────────────────┘
```

Let's walk through each layer, starting from what the user sees, then moving deeper into the AI-powered pipeline.

---

## The Frontend: What the User Sees

The frontend is a single-page React application. It has three states:

**1. Upload** — The user drags in a PDF of their research paper.

**2. Progress** — A live progress tracker shows which stage the pipeline is on. This updates in real-time over a WebSocket connection.

**3. Results** — A dashboard showing:
- The extracted invention name and description
- Key technical features identified
- A list of prior art patents, each classified as **blocking** (very similar), **relevant** (partially overlapping), or **related** (same domain but different approach)
- Relevance scores shown as percentage bars

The key frontend code lives in `frontend/src/hooks/usePipeline.ts`. Here's how it connects to the backend:

```typescript
// frontend/src/hooks/usePipeline.ts — starting an analysis

const { s3_key } = await uploadPdf(file);              // POST /api/upload
wsRef.current = connectPipeline(                         // WebSocket /ws/pipeline/{s3_key}
  s3_key,
  (msg: ProgressMessage) => { /* update progress */ },
  (error) => { startPolling(sessionId); },               // fallback if WebSocket drops
);
```

The frontend uploads the PDF, then opens a WebSocket to receive live progress updates. If the WebSocket disconnects (say, the user's network blips), it automatically falls back to polling the `/api/status` endpoint every 3 seconds. If the user refreshes the page entirely, it recovers the running session from server state. This makes the experience resilient — you won't lose your analysis.

---

## The Backend: Connecting User to Pipeline

The backend is a FastAPI server with three REST endpoints and one WebSocket endpoint:

```python
# backend/main.py

@app.post("/api/upload")          # Accept PDF, store in S3
@app.get("/api/results/{s3_key}") # Fetch completed report from S3
@app.get("/api/status")           # Check if pipeline is running
@app.websocket("/ws/pipeline/{s3_key}")  # Stream live progress
```

When a PDF is uploaded, it goes straight to Amazon S3 (cloud storage) with a timestamp prefix to avoid name collisions:

```python
# backend/main.py — upload handler

ts = int(time.time())
safe_name = file.filename.replace(" ", "_")
s3_key = f"input/{ts}_{safe_name}"     # e.g., input/1770862771_my_paper.pdf
s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=contents)
```

The WebSocket endpoint is where it gets interesting. The pipeline runs in a **background thread** (because it takes minutes, not milliseconds), while the WebSocket stays open to stream progress:

```python
# backend/main.py — WebSocket handler (simplified)

def run_in_thread():
    run_pipeline_with_progress(bucket, s3_key, progress_callback=progress_callback)

thread = threading.Thread(target=run_in_thread, daemon=True)
thread.start()

while True:
    msg = await progress_queue.get()        # wait for progress from pipeline
    await websocket.send_json(msg)           # send it to the browser
    if msg["status"] in ("completed", "error"):
        break
```

An `asyncio.Queue` bridges the synchronous pipeline thread and the asynchronous WebSocket — the pipeline pushes messages in, the WebSocket reads them out.

---

## The Pipeline: Where the AI Lives

This is the heart of the system. Six stages, each building on the previous one.

All pipeline code lives in `src/full_pipeline_cached.py`.

### Stage 0: Extract Text from PDF

Before any AI can work, we need to turn a PDF into text. PDFs are notoriously difficult — they store visual layout information, not semantic structure. We use **AWS Textract** with its Layout feature, which understands document structure:

```python
# src/textractChunkingv2.py

chunks = extract_text_from_s3_by_sections(bucket, pdf_key)
sections = normalize_textract_chunks(chunks)
# Returns: [{section_id: "s01", title: "Abstract", text: "..."}, ...]
```

Textract identifies section headers (Abstract, Introduction, Methods, Results, etc.) and groups the text under each header. The `normalize` step filters out noise — chunks that are too short, have too few actual letters (like a page of equations), or are just figure captions.

The output is a clean list of sections, each with an ID, title, and text content. These sections become the foundation for everything that follows.

---

### Stage 1: Understand the Invention (The ReAct Agent)

This is the most sophisticated stage. We need the AI to read an entire research paper and extract a structured invention description — not just a summary, but specific fields like the problem being solved, the technical approach, and the key features that make it novel.

We use a **ReAct agent** — a pattern where the AI thinks step-by-step in a loop:

```
Think → Act → Observe → Refine → Think → Act → Observe → ...
```

Here's how the loop works in code:

```python
# src/invention_agent_cached.py — the ReAct loop (simplified)

for i in range(self.max_iterations):      # up to 4 iterations

    if invention is None:
        # EXTRACT: "Read the document and extract the invention"
        response = self._call_llm(system_blocks, messages)
        invention = self._parse_json_response(response)

        # TOOL: Schema validation — are all required fields present?
        invention = self._run_schema_validation(invention, ...)

        # TOOL: Patentability check — is this actually an invention?
        patentability = self._run_patentability_check(invention, ...)

    # VALIDATE: "How confident are you in this extraction?"
    validation = self._call_llm(...)    # returns confidence score 0.0-1.0

    if confidence >= 0.85:
        break   # good enough, stop

    # REFINE: "Here's what to improve, try again"
    response = self._call_llm(system_blocks, messages)
    invention = self._parse_json_response(response)
```

**Why a loop instead of a single call?** Because LLMs don't always get it right the first time. The loop lets the system:
- Validate its own output against a schema (are all fields present?)
- Check if the extraction describes a patentable invention or just a scientific discovery
- Refine based on feedback until confidence reaches 85%

#### Prompt Caching: The Key Optimization

A research paper can be 30-50 pages. Sending the full text to the AI on every iteration would be expensive and slow. We use **prompt caching** — the document is placed in the system prompt with a cache marker:

```python
# src/invention_agent_cached.py — building the cached system prompt

system_blocks = [
    {
        "type": "text",
        "text": f"... FULL DOCUMENT TEXT ...\n{document_text}\n...",
        "cache_control": {"type": "ephemeral"},   # <-- this enables caching
    },
    {
        "type": "text",
        "text": "You participate in a ReAct loop. On each turn...",
    },
]
```

On the first call, Claude encodes and caches the document. On subsequent calls (within 5 minutes), it reads from cache — roughly **90% cheaper and much faster**. The multi-turn conversation accumulates naturally: each iteration's reasoning, actions, and feedback stay in the conversation history, so the model can reference its own earlier thinking.

#### Quality Gates: Three Independent Checks

After extraction, three tools evaluate the quality:

**1. Schema Validator** (`src/tools/schema_validator.py`) — Checks that all 9 required fields are present and correctly typed. If the AI forgot a field or returned a string where a list was expected, this catches it and asks for a fix.

**2. Patentability Classifier** (`src/tools/patentability_classifier.py`) — Applies a 3-facet rubric to determine if this is actually a patentable invention:

| Facet | What it measures | Score |
|-------|-----------------|-------|
| A: Nature of Innovation | Is it a method, system, device, or composition? | 0-2 |
| B: Conceptual Foundation | Is there a concrete mechanism, or just an abstract idea? | 0-2 |
| C: Practical Application | Are there measurable results? | 0-2 |

A total score of 0-2 = "Scientific Discovery" (not patentable), 3-4 = "Borderline", 5-6 = "Potential Invention" (proceed).

**3. JudgeBot** (`src/tools/judgeBot.py`) — An independent evaluation using a **completely different AI model** (Meta's Llama 3.1 70B instead of Claude). This avoids the problem of an AI grading its own homework. The judge scores the extraction on 5 dimensions:

```python
# src/tools/judgeBot.py — the judge evaluates without seeing the source document

dimensions = [
    "Completeness",        # Are all fields filled with real content?
    "Specificity",         # Concrete technical terms, not vague buzzwords?
    "Internal Consistency", # Does the solution actually address the problem?
    "Citation Quality",    # Real quotes from the document, or fabricated?
    "Patent Readiness",    # Could a patent attorney work with this?
]
```

The judge runs **once** after the ReAct loop finishes, and its score is combined with the agent's self-reported confidence. If the combined confidence is too low, one final refinement pass runs with the judge's feedback.

---

### Stage 2: Generate Search Queries

Now that we understand the invention, we need to search for existing patents. But you can't just search for the invention name — patent language is very specific. We ask Claude (the lighter, faster Sonnet model) to generate 10 targeted search queries:

```python
# src/full_pipeline_cached.py

prompt = PromptTemplates.generate_search_queries(invention, num_queries=10)
queries = call_bedrock_json(prompt, max_tokens=500, model_id=MODEL_SONNET)
# Returns: ["acoustic wave filter tunable magnetic field", "spin wave correlator RF signal", ...]
```

These queries target different aspects of the invention — the mechanism, the application, the materials, the problem being solved — to cast a wide net.

---

### Stage 3: Search Existing Patents

With 10 search queries in hand, we search Google Patents via the SerpAPI service. This stage runs **in parallel** — multiple searches at once — because each search is just an HTTP request waiting for a response:

```python
# src/utils/parallel_search.py

with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
    future_to_query = {executor.submit(run_query, q): q for q in queries}
    for future in as_completed(future_to_query):
        results_by_query.append(future.result())
```

`ThreadPoolExecutor` spawns multiple threads that make API calls simultaneously. This turns 10 sequential searches (each taking ~1 second) into a batch that completes in ~2-3 seconds. Results are deduplicated by patent number and reordered to match the original query order.

---

### Stage 4: Fetch Patent Details

The search results from Stage 3 only include basic information (title, snippet). For patents that don't have a sufficiently detailed abstract, we fetch the full details. This stage also runs in parallel:

```python
# src/full_pipeline_cached.py — parallel detail fetching

with ThreadPoolExecutor(max_workers=5) as executor:
    future_to_patent = {executor.submit(fetch_one, p): p for p in to_fetch}
    for future in as_completed(future_to_patent):
        fetched.append(future.result())
```

Patents that already have a good abstract (>50 characters) skip this step entirely — no need to fetch what we already have.

---

### Stage 5: Analyze Patents Against the Invention

This is where the AI compares each prior art patent against the user's invention. We use Claude Opus (the most capable model) to analyze up to 5 patents in a single batch:

```python
# src/full_pipeline_cached.py

prompt = PromptTemplates.analyze_patents_batch(inv_desc, patents[:5])
analysis = call_bedrock_json(prompt, max_tokens=3000, model_id=MODEL_OPUS)
```

For each patent, the AI returns:
- **Classification**: blocking, relevant, or related
- **Relevance score**: 0-100%
- **Overlap areas**: what aspects are similar
- **Key differences**: what distinguishes the new invention

---

### Stage 6: Generate Final Report

The final stage assembles everything into a structured JSON report:

```python
# src/full_pipeline_cached.py

report = {
    "invention": invention,          # what the user invented
    "patents_found": len(patents),   # total patents discovered
    "patents_analyzed": len(analysis),
    "blocking": count_blocking,       # how many could block a patent filing
    "relevant": count_relevant,
    "related": count_related,
    "patents": results                # detailed list with analysis
}
```

The report is saved to S3, and the agent logs are uploaded alongside it for traceability:

```python
output_key = pdf_key.replace('input/', 'results/').replace('.pdf', '_report.json')
s3.put_object(Bucket=bucket, Key=output_key, Body=json.dumps(report))

log_key = pdf_key.replace('input/', 'logs/').replace('.pdf', '_agent_logs.json')
s3.put_object(Bucket=bucket, Key=log_key, Body=log_content)
```

---

## Reliability: What Happens When Things Go Wrong?

Real systems fail. APIs throttle. Models hallucinate. Networks drop. This system handles all of these:

### Rate Limiting

AWS Bedrock (the LLM service) has usage limits. Every LLM call goes through a centralized rate limiter that enforces a minimum interval between requests:

```python
# src/utils/rate_limiter.py

class BedrockRateLimiter:
    def wait(self):
        with self._lock:                            # thread-safe
            delay = max(0.0, earliest - now)
            self._last_request = now + delay        # reserve our slot
        if delay > 0:
            time.sleep(delay)                       # sleep OUTSIDE the lock
```

Notice the subtlety: we **reserve the time slot** inside the lock but **sleep outside** it. This prevents one thread from blocking all others while it waits.

### Circuit Breaker

If the LLM service goes down entirely, we don't want to keep hammering it. A circuit breaker pattern detects repeated failures and stops making calls:

```
CLOSED (normal) → 5 consecutive failures → OPEN (reject all calls)
OPEN → 60 seconds pass → HALF_OPEN (try one call)
HALF_OPEN → success → CLOSED | failure → OPEN
```

### Exponential Backoff with Jitter

When a request is throttled, we retry with increasing delays plus a random component:

```python
delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
# Attempt 1: ~2-3 seconds
# Attempt 2: ~4-5 seconds
# Attempt 3: ~8-9 seconds
# Attempt 4: ~16-17 seconds
```

The random jitter prevents multiple threads from retrying at exactly the same time (the "thundering herd" problem).

### JSON Parse Recovery

LLMs sometimes return slightly malformed JSON. Rather than failing, the system tries multiple parsing strategies:

```python
# src/full_pipeline_cached.py — parse_json

# Try 1: Look for ```json ... ``` blocks
match = re.search(r'```json\s*([\s\S]*?)\s*```', text)

# Try 2: Look for raw JSON objects/arrays
match = re.search(r'[\[{].*[\]}]', text, re.DOTALL)

# Try 3: Ask the LLM to fix its own output
messages.append({"role": "user", "content": "Your response was not valid JSON. Return ONLY valid JSON."})
```

If parsing fails completely after 3 attempts, the entire pipeline restarts from scratch (up to 2 total attempts).

---

## Key Design Decisions

| Decision | Why |
|----------|-----|
| **Two different AI models** (Claude + Llama) | Prevents an AI from grading its own work. Independent evaluation catches blind spots. |
| **Prompt caching** | A 40-page paper costs ~150K tokens per call. Caching makes iterations 90% cheaper. |
| **Config-driven rubrics** (JSON files) | Non-engineers can adjust patentability criteria without touching code. |
| **Parallel I/O with ThreadPoolExecutor** | Patent searches are network-bound. Running 5 in parallel is 5x faster. |
| **WebSocket + polling fallback** | Real-time updates when possible, graceful degradation when not. |
| **Logs stored in S3** | Instance can be terminated without losing analysis history. Every run is traceable. |
| **Lazy initialization** | Components are created on first use, not at import time. Prevents side effects during testing. |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React, TypeScript, Tailwind CSS, Vite |
| Backend | Python, FastAPI, Uvicorn |
| AI Models | Claude Opus 4 (analysis), Claude Sonnet 4.5 (queries), Llama 3.1 70B (judge) |
| Cloud Services | AWS Bedrock (LLM), AWS Textract (OCR), AWS S3 (storage) |
| Patent Search | Google Patents via SerpAPI |
| Reverse Proxy | Nginx |
| Process Management | systemd |

---

## File Map

```
patent-agent/
├── frontend/                          # React UI
│   └── src/
│       ├── App.tsx                     # Main app layout and state routing
│       ├── hooks/usePipeline.ts        # WebSocket + polling + session management
│       ├── api/client.ts               # REST API calls (upload, results, status)
│       ├── api/websocket.ts            # WebSocket connection to pipeline
│       └── components/
│           ├── ResultsDisplay.tsx       # Patent results dashboard
│           ├── SummaryHeader.tsx        # Invention summary card
│           ├── PatentCard.tsx           # Individual patent analysis card
│           ├── ProgressTracker.tsx      # Live pipeline stage tracker
│           ├── Sidebar.tsx             # Session history sidebar
│           └── UploadArea.tsx          # PDF upload dropzone
│
├── backend/                           # FastAPI server
│   ├── main.py                        # API endpoints + WebSocket handler
│   ├── pipeline_runner.py             # Thread-safe pipeline wrapper
│   └── config.py                      # S3 bucket, ports, CORS settings
│
├── src/                               # Core pipeline
│   ├── full_pipeline_cached.py        # 6-stage pipeline orchestrator
│   ├── invention_agent_cached.py      # ReAct agent with prompt caching
│   ├── prompt_templates.py            # All LLM prompt templates
│   ├── textractChunkingv2.py          # PDF → structured sections (Textract)
│   ├── tools/
│   │   ├── schema_validator.py        # Invention JSON schema validation
│   │   ├── patentability_classifier.py # 3-facet patentability rubric
│   │   ├── patentability_config.json  # Rubric configuration (editable)
│   │   ├── judgeBot.py                # Independent Llama-based quality judge
│   │   └── judge_config.json          # Judge dimensions and thresholds
│   └── utils/
│       ├── rate_limiter.py            # Rate limiter, circuit breaker, retry logic
│       └── parallel_search.py         # ThreadPoolExecutor for SerpAPI searches
│
└── config/
    └── app.env                        # Environment variables (API keys, S3 bucket)
```
