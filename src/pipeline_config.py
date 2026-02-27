"""
Central configuration for the patent analysis pipeline.

Edit this file to change models, search limits, and analysis parameters.
All values here are the single source of truth — no need to touch full_pipeline_cached.py.
"""

# ── Models ────────────────────────────────────────────────────────────────────
# Invention extraction (Stage 1 ReAct agent) — needs strong reasoning
MODEL_EXTRACTION = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Search query generation (Stage 2) — lightweight, fast
MODEL_QUERY_GEN = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Patent analysis (Stage 5) — needs strong reasoning
MODEL_ANALYSIS = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# sonnet: "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
# opus: "us.anthropic.claude-opus-4-20250514-v1:0"


# ── Search ────────────────────────────────────────────────────────────────────
# How many distinct search queries to generate from the invention description
NUM_SEARCH_QUERIES = 10

# Maximum patent results returned per query (Google Patents via SerpAPI)
MAX_RESULTS_PER_QUERY = 5

# Parallel SerpAPI search workers
MAX_SEARCH_CONCURRENT = 5

# Seconds to wait between SerpAPI calls (avoid rate limits)
SERPAPI_DELAY = 0.2


# ── Analysis ──────────────────────────────────────────────────────────────────
# How many patents to fetch full details for (Stage 4)
MAX_PATENTS_TO_FETCH = 10

# How many patents to run LLM analysis on (Stage 5)
# Must be <= MAX_PATENTS_TO_FETCH
MAX_PATENTS_TO_ANALYZE = 5


# ── Invention Agent ───────────────────────────────────────────────────────────
# Maximum ReAct iterations before the agent is forced to finalize
AGENT_MAX_ITERATIONS = 4


# ── Rate Limiting / Resilience ────────────────────────────────────────────────
# Minimum seconds between consecutive Bedrock API calls
BEDROCK_MIN_INTERVAL = 1.0

# Circuit breaker: failures before opening the circuit
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5

# Circuit breaker: seconds to wait before retrying after opening
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60.0
