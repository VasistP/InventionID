"""
Central configuration for Patent Search System

This file contains all feature flags, rate limits, and processing parameters.
Adjust these settings to control system behavior without code changes.
"""

# ============================================================================
# FEATURE FLAGS - Enable/Disable Optional Modules
# ============================================================================

# Core Features
USE_RATE_LIMITING = True           # Enable rate limiting for API calls
USE_BATCHING = False                # Batch multiple patents into single API calls
USE_SUMMARIZATION = False           # Compress abstracts/claims before analysis
USE_EMBEDDING_FILTER = False        # Pre-filter patents by semantic similarity
# Fetch and analyze patent details (abstracts/claims)
USE_DETAILED_ANALYSIS = False

# ============================================================================
# RATE LIMITING CONFIGURATION
# ============================================================================

# Rate limit settings (to avoid hitting API limits)
RATE_LIMIT_RPM = 10                 # Requests per minute (10 RPM for testing)
# Minimum seconds between requests (60/10 = 6s)
MIN_REQUEST_INTERVAL = 6.0

# ============================================================================
# PATENT PROCESSING LIMITS
# ============================================================================

# How many patents to process at each stage
# Maximum patents from search (set to 1 for testing)
MAX_PATENTS_TO_FETCH = 1
# Maximum patents after filtering (set to 1 for testing)
MAX_PATENTS_TO_ANALYZE = 1
# Maximum patents for deep analysis (set to 1 for testing)
MAX_PATENTS_FOR_DETAILED_ANALYSIS = 1

# ============================================================================
# BATCH PROCESSING CONFIGURATION
# ============================================================================

# Batch sizes for different operations
BATCH_SIZE_SEARCH = 1               # Patents per search batch
BATCH_SIZE_DETAILS = 1              # Patents per detail fetch batch
BATCH_SIZE_ANALYSIS = 1             # Patents per analysis batch

# ============================================================================
# TEXT SUMMARIZATION CONFIGURATION
# ============================================================================

# Summarizer settings (only used if USE_SUMMARIZATION = True)
SUMMARIZER_METHOD = "textrank"      # Options: "textrank", "luhn", "lsa", "lexrank"
MAX_ABSTRACT_SENTENCES = 3          # Maximum sentences in summarized abstract
MAX_CLAIM_SENTENCES = 5             # Maximum sentences in summarized claims

# ============================================================================
# EMBEDDING FILTER CONFIGURATION
# ============================================================================

# Semantic similarity filter settings (only used if USE_EMBEDDING_FILTER = True)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Sentence transformer model
SIMILARITY_THRESHOLD = 0.3            # Minimum similarity score (0-1)
TOP_K_PATENTS = 15                    # Top K patents to keep after filtering

# ============================================================================
# LLM CLIENT CONFIGURATION
# ============================================================================

# Default LLM model (can be overridden)
DEFAULT_LLM_MODEL = "claude-sonnet-4-5"
# DEFAULT_LLM_MODEL = "gemini-2.5-flash"

# LLM generation parameters
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TEMPERATURE = 0.3

# ============================================================================
# SEARCH CONFIGURATION
# ============================================================================

# Patent search settings
# Use LLM web search (True) or traditional scraping (False)
USE_LLM_WEB_SEARCH = True
MAX_SEARCH_QUERIES = 5              # Maximum number of search queries to generate
MAX_RESULTS_PER_QUERY = 10          # Maximum results per search query

# ============================================================================
# OUTPUT CONFIGURATION
# ============================================================================

# Output paths
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_OUTPUT_FILE = "../output/results.json"

# Output format settings
INCLUDE_SEARCH_METADATA = True
# Include full abstracts in output (if available)
INCLUDE_FULL_ABSTRACTS = True
INCLUDE_CLAIMS = True               # Include claims in output (if available)

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

# Logging settings
VERBOSE_LOGGING = True              # Enable detailed logging
LOG_API_CALLS = True                # Log all API calls (useful for debugging)
LOG_RATE_LIMIT_WAITS = True         # Log when rate limiting causes delays

# ============================================================================
# CONFIGURATION PRESETS
# ============================================================================


def get_preset_config(preset_name: str) -> dict:
    """
    Get a preset configuration for common use cases

    Args:
        preset_name: Name of the preset ("testing", "quick_scan", "budget", "comprehensive")

    Returns:
        Dictionary of configuration overrides
    """
    presets = {
        "testing": {
            # Minimal configuration for testing
            "USE_RATE_LIMITING": True,
            "USE_BATCHING": False,
            "USE_SUMMARIZATION": False,
            "USE_EMBEDDING_FILTER": False,
            "USE_DETAILED_ANALYSIS": False,
            "MAX_PATENTS_TO_FETCH": 10,
            "MAX_PATENTS_TO_ANALYZE": 1,
            "MAX_PATENTS_FOR_DETAILED_ANALYSIS": 1,
        },
        "quick_scan": {
            # Fast scanning, no detailed analysis
            "USE_RATE_LIMITING": True,
            "USE_BATCHING": False,
            "USE_SUMMARIZATION": False,
            "USE_EMBEDDING_FILTER": True,
            "USE_DETAILED_ANALYSIS": False,
            "MAX_PATENTS_TO_FETCH": 100,
            "MAX_PATENTS_TO_ANALYZE": 15,
        },
        "budget": {
            # Budget-conscious: analyze only top patents
            "USE_RATE_LIMITING": True,
            "USE_BATCHING": True,
            "USE_SUMMARIZATION": True,
            "USE_EMBEDDING_FILTER": True,
            "USE_DETAILED_ANALYSIS": True,
            "MAX_PATENTS_TO_FETCH": 50,
            "MAX_PATENTS_TO_ANALYZE": 15,
            "MAX_PATENTS_FOR_DETAILED_ANALYSIS": 5,
        },
        "comprehensive": {
            # Full analysis on many patents
            "USE_RATE_LIMITING": True,
            "USE_BATCHING": True,
            "USE_SUMMARIZATION": True,
            "USE_EMBEDDING_FILTER": True,
            "USE_DETAILED_ANALYSIS": True,
            "MAX_PATENTS_TO_FETCH": 100,
            "MAX_PATENTS_TO_ANALYZE": 20,
            "MAX_PATENTS_FOR_DETAILED_ANALYSIS": 20,
        }
    }

    return presets.get(preset_name, {})


def apply_preset(preset_name: str):
    """
    Apply a preset configuration to the current module

    Args:
        preset_name: Name of the preset to apply
    """
    preset = get_preset_config(preset_name)
    for key, value in preset.items():
        globals()[key] = value


# ============================================================================
# CONFIGURATION SUMMARY
# ============================================================================

def print_config_summary():
    """Print a summary of the current configuration"""
    print("=" * 80)
    print("PATENT SEARCH SYSTEM CONFIGURATION")
    print("=" * 80)
    print("\nFeature Flags:")
    print(f"  - Rate Limiting:       {USE_RATE_LIMITING}")
    print(f"  - Batching:            {USE_BATCHING}")
    print(f"  - Summarization:       {USE_SUMMARIZATION}")
    print(f"  - Embedding Filter:    {USE_EMBEDDING_FILTER}")
    print(f"  - Detailed Analysis:   {USE_DETAILED_ANALYSIS}")

    print("\nRate Limiting:")
    print(f"  - Requests per minute: {RATE_LIMIT_RPM}")
    print(f"  - Min interval:        {MIN_REQUEST_INTERVAL}s")

    print("\nProcessing Limits:")
    print(f"  - Max patents to fetch:     {MAX_PATENTS_TO_FETCH}")
    print(f"  - Max patents to analyze:   {MAX_PATENTS_TO_ANALYZE}")
    print(f"  - Max detailed analysis:    {MAX_PATENTS_FOR_DETAILED_ANALYSIS}")

    print("\nBatch Sizes:")
    print(f"  - Search:  {BATCH_SIZE_SEARCH}")
    print(f"  - Details: {BATCH_SIZE_DETAILS}")
    print(f"  - Analysis: {BATCH_SIZE_ANALYSIS}")

    print("=" * 80)


# ============================================================================
# TESTING/DEBUGGING
# ============================================================================

if __name__ == "__main__":
    print_config_summary()

    print("\n" + "=" * 80)
    print("AVAILABLE PRESETS")
    print("=" * 80)

    for preset_name in ["testing", "quick_scan", "budget", "comprehensive"]:
        print(f"\n{preset_name.upper()}:")
        preset = get_preset_config(preset_name)
        for key, value in preset.items():
            print(f"  {key}: {value}")
