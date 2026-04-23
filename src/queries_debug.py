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
    global bedrock, s3, rate_limiter, circuit_breaker, _initialized
    if _initialized:
        return
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-2')
    s3 = boto3.client('s3')
    rate_limiter = BedrockRateLimiter(min_interval=1.0)
    circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
    _initialized = True


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
    _init_components()
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


def stage_2_generate_queries(invention):
    """Stage 2: Generate search queries (using Sonnet)"""
    print("\n" + "="*60)
    print("STAGE 2: GENERATE SEARCH QUERIES")
    print("="*60)

    prompt = generate_patent_search_prompt(invention, num_queries=30)
    # print("promtpt:",prompt)
    queries = call_bedrock_json(prompt, max_tokens=5000, model_id=MODEL_OPUS)

    if queries:
        print(f"  Generated {len(queries)} queries:")
        for q in queries:
            print(f"    - {q}")

    return queries or []

# def generate_patent_search_prompt(invention_data: dict, num_queries: int = 15) -> str:
#     return f"""You are a patent agent generating Google Patents search queries to find prior art for the invention described below.

# INVENTION: {invention_data.get('invention_name', 'Unknown')}

# TECHNICAL DESCRIPTION:
# {invention_data.get('technical_description', 'N/A')}

# PROBLEM STATEMENT:
# {invention_data.get('problem_statement', 'N/A')}

# SOLUTION APPROACH:
# {invention_data.get('solution_approach', 'N/A')}

# KEY TECHNICAL FEATURES:
# {', '.join(invention_data.get('key_technical_features', []))}

# DECLARED STATUTORY CATEGORIES: {', '.join(invention_data.get('statutory_category', []))}

# Generate exactly {num_queries} Google Patents search queries by following ALL steps below in order.

# ## STEP 1: CONFIRM AND SCOPE THE STATUTORY CATEGORY

# Patent law recognizes four statutory categories:
# - **Process:** a method, sequence of steps, or procedure producing a result
# - **Machine:** a device or apparatus with specific interacting components
# - **Manufacture:** an article or product made by a process (a physical thing, not an assembly)
# - **Composition of matter:** a new material, mixture, compound, or formulation

# The extraction declares one or more categories above. Do NOT accept these blindly. Re-derive the categories from the technical description and solution approach, and reconcile with what was declared.

# For each confirmed category, write one sentence answering: **"What is the novel THING in this category?"**
# - Process → what sequence of steps is novel?
# - Machine → what device with what components is novel?
# - Manufacture → what produced article is novel?
# - Composition → what material or mixture is novel?

# **CRITICAL — SCOPE THE CATEGORY TO THE INVENTION, NOT ADJACENT THINGS:**
# The category applies only to the invention itself, not to incidental items that appear in the description.

# Examples of correct scoping:
# - Invention: a method of strengthening plastic cups.
#   - Process queries search plastic-cup strengthening methods.
#   - Composition queries search stronger plastics (the output material).
#   - Do NOT generate queries about metals, dies, or machinery used as tooling in the process, unless the novelty is in that tooling.
# - Invention: a piezoelectric actuator with an asymmetric electrode.
#   - Machine queries search piezoelectric actuators with partial electrodes.
#   - Process queries (if any) search methods of optimizing electrode geometry.
#   - Do NOT generate queries about COMSOL, MATLAB, or the simulation software itself unless those tools are claimed as part of the invention.
# - Invention: a new copper-graphene composite and its fabrication route.
#   - Composition queries search copper-graphene composites.
#   - Process queries search fabrication methods for metal-matrix composites with graphene.
#   - Do NOT generate queries about graphene synthesis in general, unless the specific synthesis step is part of the novelty.

# **Rule:** An item belongs in a category's query set ONLY IF that item is what the invention claims to contribute. Items that merely appear as context, tools, or prior-art ingredients do NOT get their own queries under that category.

# ## STEP 2: ALLOCATE QUERIES BY CATEGORY

# Distribute the {num_queries} queries across the confirmed categories, weighted by where the invention's novelty actually lives.

# Default allocation rules:
# - If one category dominates (the invention is primarily one thing): ~70% of queries target that category, ~30% explore adjacent categories or shared landscape.
# - If two categories share the novelty (e.g., a new composition AND the process to make it): split ~45%/~45% between them, with ~10% for shared landscape.
# - If three categories are genuinely co-equal: split roughly evenly with ~15% for shared landscape.
# - Never allocate queries to a category just because it was declared — only allocate if the invention has genuine novelty in that category.

# Write out the allocation before proceeding. Example:
# - Process: 9 queries (primary novelty is the optimization method)
# - Machine: 4 queries (the actuator device itself)
# - Shared landscape: 2 queries

# ## STEP 3: EXTRACT KEY TERMS, GROUPED BY CATEGORY

# For each category receiving queries, list every significant technical term from the extraction that belongs to THAT category.

# - **Process terms:** verbs, step names, algorithm names, analysis techniques, measurement methods
# - **Machine terms:** component names, geometric features, architectural elements, connection types
# - **Manufacture terms:** article names, form factors, product descriptors
# - **Composition terms:** material names, chemical formulas, phase descriptors, additive names

# If a term would only appear in a category you are NOT querying (per Step 1 scoping), exclude it. This prevents scope leak.

# ## STEP 4: BUILD RETRIEVAL-ORIENTED TERM CHAINS

# For each key concept, build a chain of 3-5 search-useful alternative terms that a patent examiner or technical searcher would recognize as potentially expressing the same or closely related concept in patents, papers, product documentation, or engineering language. Use OR inside parentheses to combine them in queries.

# **Do NOT limit yourself to dictionary synonyms.** Prioritize retrieval usefulness over linguistic similarity.

# Include, when supported by the invention and useful for retrieval:
# - the extraction's exact term
# - close technical equivalents
# - broader field-standard terms
# - narrower field-standard terms
# - acronyms alongside spelled-out forms
# - common word-form variants (noun/adjective, hyphenated/non-hyphenated)
# - patent-style generalized phrasing
# - functionally equivalent expressions
# - domain-specific alternative phrasing used in patents or engineering writing
# - software/UI or industry-standard vocabulary when it differs from academic vocabulary

# **EXPLICIT vs IMPLICIT TERM SUPPORT:**
# A term does not need to appear verbatim in the invention text to be usable.
# You may include a term if it is:
# - **Explicitly supported**: directly stated in the extraction
# - **Implicitly supported**: not stated verbatim, but clearly represents the same technical idea, function, structure, behavior, parameter, or result described in the extraction

# Do NOT include terms that are unsupported or speculative.

# **IMPORTANT:**
# A good alternative term is one that could realistically retrieve relevant prior art, even if it is not a strict synonym.
# For example, technical documents often use different wording for:
# - the same structure
# - the same function
# - the same measured outcome
# - the same design parameter
# - the same physical mechanism

# **Method/technique families — RELAXED SUBSTITUTION RULE:**
# For process-category concepts, include related methods from the same technical family when a prior-art searcher would reasonably inspect them together, even if they are not strict synonyms.

# **RETRIEVAL TEST for OR chains:**
# Before finalizing a chain, ask:
# - "Would these terms likely retrieve overlapping prior-art neighborhoods?"
# - "Would a skilled searcher treat these as alternate ways the same concept may be expressed?"
# If yes, the chain is valid.

# Terms belong in different AND clauses, not the same OR chain, when they represent different aspects of the invention, such as:
# - component vs. measurement
# - material vs. process
# - structure vs. function
# - cause vs. effect
# - object vs. attribute
# - device vs. optimization goal

# Avoid weak thesaurus-style substitutions that are linguistically similar but technically useless.

# ## STEP 5: DISAMBIGUATE VAGUE TERMS

# Generic concept words (optimization, analysis, modeling, simulation, control, design, characterization, improvement, processing, fabrication) are ambiguous because they appear across every technical field.


# A query containing a bare generic concept word fails validation and must be rewritten.

# When building alternatives for generic terms, prefer:
# - domain-object pairings
# - technical compound phrases
# - function-specific variants
# - parameter-specific variants

# ## STEP 6: SEPARATE SHARED VOCABULARY FROM NOVELTY VOCABULARY

# Within each category, identify:
# - **Shared vocabulary:** general device type, material class, method family, application field that the invention shares with existing work. Prior art uses these terms.
# - **Novelty vocabulary:** specific findings, discoveries, or unique features that make the invention new. Prior art usually does NOT use these.

# A search query describes the NEIGHBORHOOD where prior art might live, not the invention itself.

# Query budget within each category:
# - **~80% shared-vocabulary queries:** should return 20-200 results with relevant prior art in the top 10-50.
# - **~20% novelty-vocabulary queries:** long-shot queries that may return few or zero results, which is expected.

# ## STEP 7: BUILD QUERIES USING ROUND STRUCTURE, APPLIED WITHIN EACH CATEGORY

# Within each category's allocated budget, use this round structure:

# **Round 1 — Landscape:** Search the specific materials, components, or methods that define the category's scope. Maps what already exists.

# **Round 2 — Function/Property:** Combine the category's nouns with the target function, property, or problem solved.

# **Round 3 — Core novelty approximation:** Search the invention's specific approach using shared vocabulary terms rather than overly invention-specific wording. This is where the most likely relevant prior art is found.

# **Round 4 — Concept (drop specifics):** Replace specific materials/components with generic but technically valid equivalents. Search the underlying architectural or methodological concept. This is where hidden and distant prior art lives.

# **Round 5 — Broadest:** Search the design principle at its most abstract level, using field-standard term chains.

# Not every round must be used in every category. Skip rounds that don't produce meaningful queries for that category.

# ## QUERY FORMAT RULES

# - Use AND, OR, "", and () operators
# - Each term is MAXIMUM 2 words (except inside quoted phrases)
# - Any multi-word phrase (2+ words) MUST be wrapped in double quotes
# - Every concept in a query MUST be connected by explicit AND
# - Use OR to group alternative terms inside parentheses
# - Do NOT use site:, -, or other advanced operators
# - **Anchoring rule:** every query MUST include at least one highly specific technical phrase in quotes to prevent matching unrelated fields

# ## PRECISION vs RECALL BALANCE

# - Max 1-2 STANDALONE quoted phrases per query
# - Quoted phrases inside OR chains don't count toward the limit — an OR chain of quoted compounds counts as ONE concept
# - Fill the rest of each query with single keywords and OR chains

# ## CONSTRAINT MIX

# Distribute query tightness across the full set:
# - **~20% tight (4 AND concepts):** specific prior art, few results
# - **~40% medium (3 AND concepts):** balanced coverage
# - **~40% loose (2 AND concepts):** broad landscape, many results

# **When loosening: keep the broad field/device/material anchor. Drop niche sub-features.**

# Test: "If I remove this term, will results drift into unrelated fields?" If yes, keep it (it's the anchor). If no, safe to drop.

# ## VALIDATION CHECK

# Before outputting, verify each query:
# 1. Every multi-word phrase has quotes
# 2. Every concept connected by explicit AND
# 3. At least one quoted phrase for anchoring
# 4. Max 2 standalone quoted phrases (OR-chain compounds don't count)
# 5. OR chains group only technically compatible alternatives that would search the same or closely related prior-art neighborhood
# 6. OR chains have 3-5 terms when useful supported alternatives exist
# 7. Generic concept words never alone — always in compound-phrase chain or paired with domain object
# 8. Query belongs to the correct category per Step 1 scoping — no scope leak to adjacent technologies
# 9. Mix of tight, medium, and loose queries across the full set
# 10. Category allocation matches Step 2 distribution
# 11. Terms that do not appear verbatim are still grounded by clear implicit support from the invention text
# 12. Remove unsupported, speculative, or merely generic wording

# If any query fails, rewrite it.

# ## OUTPUT FORMAT

# Output ONLY a Python list of query strings. No explanations, no reasoning, no commentary, no round labels, no category labels.

# ["query 1", "query 2", "query 3", ...]

# The list must contain exactly {num_queries} strings.
# """


# def generate_patent_search_prompt(invention_data: dict, num_queries: int = 30) -> str:
#     return f"""You are a patent agent. Extract the core technical keywords a patent agent would use to search for prior art.

# INVENTION: {invention_data.get('invention_name', 'Unknown')}

# TECHNICAL DESCRIPTION:
# {invention_data.get('technical_description', 'N/A')}

# PROBLEM STATEMENT:
# {invention_data.get('problem_statement', 'N/A')}

# SOLUTION APPROACH:
# {invention_data.get('solution_approach', 'N/A')}

# KEY TECHNICAL FEATURES:
# {', '.join(invention_data.get('key_technical_features', []))}

# Output ONLY keywords, one per line with a newline after each. No numbering, no explanations, no extra text."""


# def generate_patent_search_prompt(invention_data: dict, num_queries: int = 15) -> str:
#     return f"""You are a patent agent generating Google Patent search queries to find prior art for this invention.

# INVENTION: {invention_data.get('invention_name', 'Unknown')}

# TECHNICAL DESCRIPTION:
# {invention_data.get('technical_description', 'N/A')}

# PROBLEM STATEMENT:
# {invention_data.get('problem_statement', 'N/A')}

# SOLUTION APPROACH:
# {invention_data.get('solution_approach', 'N/A')}

# KEY TECHNICAL FEATURES:
# {', '.join(invention_data.get('key_technical_features', []))}

# Generate exactly {num_queries} Google Patent search queries by following ALL steps below.

# ## STEP 1: DETERMINE STATUTORY CATEGORY
# Classify the invention into one or more of the four patent-eligible categories:
# - Process: a method, sequence of steps, or procedure
# - Machine: a device or apparatus with specific components
# - Manufacture: an article or product made by a process
# - Composition of matter: a new material, mixture, or compound

# Identify the PRIMARY category. This determines query focus:
# - Composition of Matter or Manufacture: "does this material/product exist?" then "has anyone made it this way?"
# - Process: "has anyone used these steps before?" then "on these materials/inputs?"
# - Machine: "does this device exist?" then "has anyone used these components this way?"

# ## STEP 2: EXTRACT KEY TERMS
# List every significant technical term from the extraction. Group them into:
# - Materials/Components
# - Structure/Architecture/Configuration
# - Process/Method/Steps
# - Properties/Function/Performance
# - Problem/Application/Field

# CRITICAL: Every query term MUST trace back to this list OR to a field-standard synonym from Step 3.

# ## STEP 2b: CORPUS-FREQUENCY FILTER (CRITICAL)
# A term being in the source paper does NOT mean it belongs in a patent query. Patents and papers use different vocabulary for the same concepts. Some paper-register terms are rarely or never used in patent text for the target device class — and including them silently degrades queries even when syntactically well-placed.

# **The test: Would a patent attorney drafting a claim for this specific technology area actually use this word?**

# Patent drafters deliberately avoid jargon that narrows claim scope, preferring functional language (what the device does) over structural-descriptor language (what shape or form it has). If a term is technically accurate but patent-rare for the target technology area, DROP it from the candidate pool. Do not try to position it safely with AND-pairing. Do not include it in OR-chains. Its presence will either return cross-domain noise or actively filter out target patents that don't use the word.

# **Recognizing patent-rare terms (domain-agnostic patterns):**

# 1. **Paper-invented compounds.** When a paper stacks 3+ modifiers into a noun phrase, the compound is almost always paper-specific and will not appear in patent text. Patents describe the same configuration functionally instead. If the extraction contains a term with 3+ stacked modifiers, break it into component concepts and drop the compound.

# 2. **Directional / geometric conventions.** Papers use directional modifiers to distinguish their work from prior work (e.g., "planar X," "in-plane Y," "vertical Z"). Patents describe motion or orientation functionally in the claim body, not in compound nouns. Directional modifiers rarely survive into patent claim language.

# 3. **Math and analysis descriptors.** Words that describe the *character of a result* rather than the device itself (e.g., "nonmonotonic," "nonlinear response," "parametric," "nondimensional," "scale-invariant") belong to paper methodology sections and almost never appear in patent claims.

# 4. **Structural terms with heavy cross-domain usage.** Some bare nouns (e.g., structural terms borrowed from civil/mechanical engineering, geometric descriptors used across many fields) are technically valid for the device but absent from patents in the specific technology area because (a) patent drafters avoid them to keep claim scope broad, and (b) the bare noun pulls in massive corpora from unrelated domains.

# 5. **Ratios and parameterizations specific to the paper's framing.** Terms like "X-to-Y ratio," "normalized Z," "dimensionless W" are paper framings for presenting results. Patents name the dimensions or parameters separately.

# **How to apply the filter:**
# For each extracted term, perform three checks:
# (a) Does this term appear in patent claim language for THIS specific technology area, or only in academic writing?
# (b) If I searched this term alone on a patent database, would the results concentrate in the target technology area, or drift into unrelated domains?
# (c) Does a shorter or more functional alternative exist that patents are more likely to use?

# If (a) is "only academic," (b) is "drifts into unrelated domains," or (c) is "yes," drop the term. Use the functional alternative instead.

# **Failure mode to recognize and avoid:** a term that is (1) in the source paper, (2) technically accurate, and (3) patent-rare for the target domain will produce queries that feel well-constructed but systematically miss target patents. The term carries provenance, which makes it feel safe, but it hurts recall.

# ## STEP 3: EXPAND WITH FIELD-STANDARD SYNONYMS AND BUILD SYNONYM CHAINS
# For each key concept that survived Step 2b, identify the standard technical term used in the broader field, even if the extraction does not use that exact word. A patent agent uses domain knowledge to recognize that a concept described in the extraction may be known by a different established term in the literature and patent databases.

# For each key concept, build a **synonym chain** — a group of interchangeable terms that all refer to the same or closely related concept. These chains will be used with OR inside parentheses in queries.

# **Target chain length: 3-5 terms per chain when synonyms exist.** Do not settle for 2-term chains if more valid synonyms exist. Only use shorter chains when the concept genuinely has fewer field-standard synonyms.

# General principles for building chains:
# - Include the extraction's term (if it passed Step 2b) + broader/narrower field-standard terms
# - Include both the specific technical name and its common generic equivalent
# - Include different word forms if patents use them (noun vs adjective, hyphenated vs non-hyphenated)
# - Include acronyms alongside their spelled-out forms
# - Group together only terms that a patent examiner would recognize as describing the same concept
# - Every term in the chain must independently pass the Step 2b corpus-frequency filter

# **Method/technique families — RELAXED SUBSTITUTION RULE:**
# When the concept is a method, technique, or analytical approach, include RELATED techniques in the same family, not just strict synonyms. Patents often address the same underlying problem using different but related techniques, so prior art crosses technique boundaries.

# For method concepts, ask: "Would a patent examiner reviewing prior art for this invention recognize these techniques as addressing the same underlying design or analysis problem?" If yes, they belong in the same OR chain even if the techniques differ in specifics.

# **DOMAIN KNOWLEDGE EXPANSION FOR METHODS:**
# When the extraction describes a method or technique, think beyond what the extraction literally says. Ask yourself: "What are the established named techniques in this method family that a domain expert would recognize?"

# For each method concept, mentally enumerate the broader family of related named techniques used in the same field or adjacent fields. Include these in your synonym chains even if the extraction only mentions one specific technique. Prior art often uses a different technique from the same family to solve the same problem.

# Only use synonyms and related techniques you are confident are field-standard. Do NOT invent terms.

# ## STEP 3b: USE SYNONYM CHAINS IN QUERIES
# When a concept has multiple field-standard names, wrap the chain in parentheses with OR:
# concept_X AND (synonym1 OR synonym2 OR synonym3) AND concept_Y

# This catches patents using different vocabulary for the same idea. Use synonym chaining especially in Rounds 4 and 5 where you are searching concepts, not specific materials.

# **CRITICAL: OR chains must contain ONLY true synonyms — terms that are interchangeable and describe the same underlying concept.**

# Before writing an OR chain, ask: "Could I substitute any term in this chain for any other without changing what I'm searching for?" If yes, the chain is valid. If no, the terms belong in separate AND clauses, not an OR.

# Terms belong in different AND clauses (not OR) when they represent different aspects of the invention — such as a component vs a measurement, a material vs a process, a cause vs an effect, or an object vs an attribute.

# ## STEP 3c: DISAMBIGUATE VAGUE TERMS
# Generic concept words (e.g., optimization, analysis, modeling, simulation, control, improvement, design, characterization) are ambiguous on their own because they appear across every technical field.

# **MANDATORY: Never use a generic concept word alone in a query.** The preferred strategy is to build a synonym chain of quoted compound phrases where the generic word is prefixed by a specific modifier.

# Build a chain of 3-5 quoted compound phrases, each combining a modifier with the generic word. Quoted compound phrases inside OR chains are ENCOURAGED and count as ONE concept for the precision rule, not multiple separate quoted phrases.

# If a query contains a generic concept word that is not part of a compound-phrase synonym chain AND not paired with its domain object in the same query, the query FAILS validation and must be rewritten.

# ## STEP 3d: REGISTER-TRANSLATION
# Papers and patents describe the same physical concepts using different vocabulary. Papers favor academic register; patents favor engineering/industrial register. A query built only from paper-register terms will miss patents that describe the same concept in industrial-register terms.

# For each key concept that passed Step 2b, identify BOTH:
# - The **paper-register term** (what the extraction literally says, IF patent-common enough to retain after Step 2b)
# - The **patent-register term** (what patents typically call the same concept)

# When the two differ, the OR chain for that concept MUST include both registers (subject to Step 2b — if the paper-register term fails corpus-frequency filtering, use only the patent-register term).

# **Vocabulary sources for patent-register translation:**
# - Software UI labels and screenshot text in the source paper (software vendors calibrate vocabulary to industry/patent terms; a paper that uses one word in prose may label the same quantity differently in its simulation tool's interface)
# - Industry datasheets and component manufacturer specifications
# - Standards documents (IEEE, ASME, ANSI, ISO, ASTM)
# - CPC/IPC classification scheme terminology
# - Review articles that span academic and industrial perspectives
# - Patent claims in the same technology area (when any are already known)

# **The paper-prose vs paper-software-UI mismatch signal:** When a paper's prose uses one term but the paper's own software screenshots use a different term for the same quantity, the software-UI term is usually closer to patent-register. Extract both and flag the UI term as a high-confidence patent-bridge candidate.

# **Repurposed terms:** A term may appear in the paper in one sense but be used in the query in a different, patent-register sense. These are powerful because they carry provenance from the source while doing patent-world bridging work. Flag repurposed terms as distinct from pure injections.

# ## STEP 3e: POSITION-SAFETY FOR CROSS-DOMAIN TERMS
# Some terms are technically valid in multiple unrelated domains and cause recall collapse when used naively. These terms pass Step 2b in some contexts but still need careful positioning.

# A term is **domain-ambiguous** if it:
# - Appears as a common noun across multiple unrelated engineering fields, AND
# - Does not carry its own domain lock (no field-specific prefix like a material class, a device class, or a scale qualifier)

# Rule for domain-ambiguous terms:
# (a) Use ONLY as an AND-narrowing term in a query that already has a domain-locked anchor elsewhere in the same query.
# (b) NEVER OR-chain a domain-ambiguous term with a domain-locked anchor. The OR makes the chain match documents that only have the ambiguous term, exploding the result set into unrelated domains.
# (c) If the term also fails Step 2b for the target technology area, drop it entirely.

# **How to detect domain-ambiguity for an unfamiliar term:** Ask "If I searched this term alone on a patent database, would results concentrate in the target domain or scatter across many domains?" If results would scatter, the term is domain-ambiguous and needs position-safety handling.

# ## STEP 4: IDENTIFY NOVELTY AND SEARCH STRATEGY

# **CRITICAL — SEARCH THE NEIGHBORHOOD, NOT THE INVENTION:**
# A search query is NOT a description of the invention. A search query describes the FIELD or NEIGHBORHOOD where prior art might exist.

# Novelty terms (the specific findings, discoveries, or unique features that make this invention new) will NOT appear in prior art — because if they did, the invention wouldn't be novel. Using too many novelty terms produces empty results.

# Build most queries from SHARED vocabulary — the general device type, material class, method family, and application field that the invention shares with existing work.

# Query budget:
# - **~80% of queries: Use shared vocabulary** — broad field, device type, material, method family. These should return 20-200 results with relevant patents in the top 10.
# - **~20% of queries: Use novelty terms** — specific findings or unique features. Long-shot queries that may return few or zero results, which is expected.

# ## STEP 4b: IDENTIFY WHAT vs HOW AXES
# Most inventions have TWO independent searchable axes:

# 1. **WHAT axis (the thing itself):** The physical device, material, structure, or composition. Queries search: "does this thing exist?"

# 2. **HOW axis (the method):** The process, optimization method, analysis technique, or design methodology. Queries search: "has anyone used this method before?"

# HOW axis signals in an extraction:
# - The title contains a method verb (Optimizing, Designing, Synthesizing, Analyzing, Simulating)
# - The solution approach describes a computational, analytical, or experimental methodology
# - Design tools, software, or algorithms are provided

# CRITICAL: If the HOW axis exists, it MUST receive its own dedicated queries, not just be mentioned as a secondary term in WHAT-axis queries.

# ## STEP 4c: SIX-ROLE QUERY DECOMPOSITION (PRIMARY QUERY-BUILDING FRAMEWORK)
# Every well-formed query can be decomposed into up to six ROLES. Each role performs a distinct discriminating function. Before writing a query, identify which roles the query fills. Well-balanced queries fill 4-6 roles; each role uses 1 concept (a single term or one OR-chain).

# **The six roles:**

# 1. **OBJECT ROLE** — the physical device, material, or artifact. Anchors the technical neighborhood. Usually 1-2 terms, tightly specific. MUST be a term that passes Step 2b corpus-frequency filtering for the target domain. Prefer the shortest patent-register device noun over any paper-compounded version.

# 2. **METHOD ROLE** — how the work was performed or how the invention operates. Filters the cluster from fabrication-only or materials-only patents to analysis/design/operation patents.

# 3. **OBJECTIVE ROLE** — what is being maximized, minimized, measured, or achieved. This is where paper-to-patent vocabulary mismatch bites hardest and where register-translation (Step 3d) is most important. Almost always a 3-4 term OR-chain spanning academic and patent registers.

# 4. **PROCESS ROLE** — what engineering activity the work represents. Distinguishes same-object documents doing different things (e.g., optimization vs fabrication vs characterization vs synthesis). Usually 1 term.

# 5. **VARIABLE-CLASS ROLE** — what aspect of the object is being varied or specified. Works best as an OR-chain of moderately generic design-space terms rather than the paper's specific variable names (which are usually too narrow).

# 6. **BRIDGE ROLE** — one patent-register term that tilts ranking toward industrial documents. Appears heavily in patent claims but rarely dominates academic prose. Candidates include terms that frame how patents formulate design problems (e.g., words that express constraints, specifications, tolerances, requirements, or criteria). Not strictly necessary but often pushes top-20 hits into top-10.

# **When to use which roles:**
# - Tight queries (4 AND concepts): typically OBJECT + METHOD + OBJECTIVE + (PROCESS or VARIABLE-CLASS)
# - Medium queries (3 AND concepts): typically OBJECT + METHOD + (OBJECTIVE or VARIABLE-CLASS)
# - Loose queries (2 AND concepts): typically OBJECT + (METHOD or OBJECTIVE or VARIABLE-CLASS)
# - Bridge role is optional but often decisive for ranking — add when targets are consistently landing in top 20-50 but not top 10

# **Diagnostic use:** If a query is underperforming, check which roles are missing or mis-filled. Missing OBJECT = too broad. Missing METHOD = wrong cluster. Missing OBJECTIVE = noisy ranking. Missing PROCESS = mixing fabrication and design work. Missing VARIABLE-CLASS = can't distinguish what's being searched for. OBJECT filled with a patent-rare term = systematic miss (revisit Step 2b).

# **Role independence rule:** Each role should be filled by terms that do not overlap with other roles' terms. If the same term fits two roles, the query is double-counting. Move one to a different role or drop it.

# ## STEP 5: BUILD QUERIES ACROSS ROUNDS

# Allocate {num_queries} queries across these rounds based on statutory category and novelty. Not all rounds need equal queries. Skip rounds that don't apply.

# **Round 1 — Landscape:** Search the specific materials, components, or device type to map what already exists. Typically fills OBJECT + 1-2 other roles.

# **Round 2 — Function/Property:** Combine materials/components with the target properties, functions, or problems solved. Typically fills OBJECT + OBJECTIVE + PROCESS.

# **Round 3 — Process/Method:** Search the specific process steps, method, or technique. For process inventions, this is the core round. Typically fills METHOD + OBJECT + PROCESS.

# **Round 4 — Concept (drop specifics):** Replace specific materials/components with generic equivalents and search the underlying structural, architectural, or methodological concept. This is where hidden and distant prior art lives. Typically fills VARIABLE-CLASS + OBJECTIVE + PROCESS.

# **Round 5 — Broadest:** Search the design principle or method at its most abstract level. Include field-standard synonyms from Step 3 here. Typically fills 2 roles max, with heavy OR-chaining.

# ## QUERY FORMAT RULES
# - Use AND, OR, "", and () operators
# - Each term is MAXIMUM 2 words
# - **MANDATORY: Any multi-word phrase (2+ words) MUST be wrapped in double quotes.**
# - **MANDATORY: Every concept in a query MUST be connected by explicit AND.** Never rely on implicit AND between space-separated words.
# - Use OR to group synonyms within parentheses
# - Do NOT use site:, -, or other advanced operators
# - ANCHORING RULE: Every query MUST include at least one highly specific technical phrase in "" quotes to prevent matching unrelated fields

# ## PRECISION vs RECALL BALANCE
# - Max 1-2 STANDALONE quoted phrases per query (quoted phrases inside OR chains don't count — an OR chain of quoted compounds counts as ONE concept)
# - Fill the rest of the query with single keywords and OR synonym chains

# ## CONSTRAINT MIX
# Distribute queries across tightness levels:
# - **~20% tight (4 AND concepts):** Specific prior art, may return few results.
# - **~40% medium (3 AND concepts):** Balanced coverage.
# - **~40% loose (2 AND concepts):** Broad landscape, should return many results.

# **WHEN LOOSENING: Keep the broad field/device/material anchor. Drop niche sub-features.**
# Ask: "If I remove this term, will results drift into unrelated fields?" If yes, keep it (it's the anchor). If no, safe to drop.

# In role terms: when loosening, keep OBJECT first, then METHOD, then OBJECTIVE. Drop BRIDGE first, then VARIABLE-CLASS, then PROCESS.

# ## VALIDATION CHECK
# Before outputting, verify each query:
# 1. Every multi-word phrase has quotes
# 2. Every concept connected by explicit AND
# 3. At least one quoted phrase for anchoring
# 4. Max 2 standalone quoted phrases (OR-chain compounds don't count)
# 5. OR chains contain only true synonyms (substitution test)
# 6. OR chains have 3-5 terms when valid synonyms exist
# 7. Vague words never alone — always in compound-phrase chain or paired with domain object
# 8. Mix of tight, medium, and loose queries across the full set
# 9. Each query fills 2-6 identifiable roles from Step 4c, and roles do not overlap within a query
# 10. Every term in the query passes the Step 2b corpus-frequency filter for the target technology area
# 11. For each concept where paper-register and patent-register differ, the OR chain includes both registers (subject to Step 2b)
# 12. Domain-ambiguous terms (Step 3e) are only used as AND-narrowing terms with a domain-locked anchor elsewhere in the query — never as OR-chain members alongside domain-locked anchors
# If any query fails, rewrite it.

# ## OUTPUT FORMAT
# Output ONLY a Python list of query strings. No explanations, no reasoning, no commentary, no round labels.

# ["query 1", "query 2", "query 3", ...]

# The list must contain exactly {num_queries} strings.
# """



def generate_patent_search_prompt(invention_data: dict, num_queries: int = 15) -> str:
    statutory = invention_data.get('statutory_category', 'N/A')
    if isinstance(statutory, list) and len(statutory) > 3:
        statutory_instruction = (
            f"The disclosure lists multiple statutory categories: {statutory}. "
            f"Pick the TWO categories with the highest claim-drafting impact for this "
            f"invention and generate queries biased toward those two. Ignore the rest."
        )
    else:
        statutory_instruction = f"Statutory category: {statutory}"

    return f"""You are a patent agent generating Google Patents search queries for prior art discovery. Your queries must use PATENT CLAIM LANGUAGE, not academic paper language.

# INVENTION DISCLOSURE

Name: {invention_data.get('invention_name', 'Unknown')}

Technical description:
{invention_data.get('technical_description', 'N/A')}

Problem statement:
{invention_data.get('problem_statement', 'N/A')}

Solution approach:
{invention_data.get('solution_approach', 'N/A')}

Key technical features:
{', '.join(invention_data.get('key_technical_features', []))}

{statutory_instruction}

# CORE PRINCIPLE

The disclosure is INPUT, not vocabulary. The vocabulary comes from patent claim language in this technical field. The disclosure tells you WHICH claim-language terms apply — not which words to copy verbatim.

You are not searching for the invention. You are searching for the NEIGHBORHOOD the invention lives in. The query should describe the category of thing the invention belongs to, using terms that would appear in claims of competing or adjacent patents — not terms that describe what makes this specific invention different.

# STEP 1 — NAME THE FIELD

Before drafting queries, state the patent-classification field of this invention in one phrase. This is the field a patent examiner would be assigned to, not the specific invention.

The field determines what counts as claim language. You cannot filter terms without knowing the field.

# STEP 2 — NOVELTY-FILTER CHECK

After naming the field, identify the terms in the disclosure that describe what makes THIS invention different from others in the field. These are the novelty terms — the specific configuration, the distinguishing structural feature, the optimization variable, the mechanism the inventor discovered.

NOVELTY TERMS DO NOT GO IN THE QUERY.

The query describes the neighborhood the invention lives in, not the invention itself. You are searching for prior art in the same category — competing patents, adjacent approaches, earlier work on the same class of device. Those patents will not use this invention's novelty vocabulary, because if they did, the invention would not be novel.

How to separate novelty terms from category terms:

- CATEGORY terms: the generic noun for the device, its standard components, its performance metric, its typical analysis method, its activity verb. These appear in many patents in the field.
- NOVELTY terms: adjectives and qualifiers that mark THIS design as different from the norm in its field (e.g., terms expressing asymmetry vs. symmetry, partial vs. full, one-direction vs. another, mechanism-specific modifiers, analytical descriptors of the departure). These are specific to the invention's contribution.

If a term describes the axis along which this invention departs from the norm, drop it. The search is for the norm, not the departure.

The disclosure will spend most of its vocabulary explaining the novelty — that is what disclosures are for. A good prior-art query throws almost all of that vocabulary away and keeps only the category scaffolding underneath.

# STEP 3 — CLAIM-LANGUAGE CHECK, IN CONTEXT

For each candidate term that survived Step 2, ask: in independent claims of patents in THIS field, does this term appear?

Three reasoning questions to answer that:

1. Is this term naming the invention (the thing being claimed), or is it explaining HOW or WHY the invention works? Terms that explain mechanism, cause, or analytical approach are almost always spec-only, regardless of field.

2. Is this term at the abstraction level a claim drafter uses, or is it more specific (a grade, a brand, a formulation, an analytical descriptor)? Claims tend toward generic structural and functional terms. Specific identifiers live in the specification.

3. If you imagine scanning 20 independent claims in this field, would this term appear in several, or would it be rare/absent? If rare, drop it — even if it is central to the disclosure's novelty.

When uncertain between a more specific and more generic term, prefer the generic one.

# STEP 4 — OBJECT-COLLISION CHECK

Do not AND two nouns that name the same object at different abstraction levels.

Test: if you pointed at the physical thing the invention is, would both nouns correctly name it? If yes, they collide — pick one.

If the nouns name different things (device vs. a part of it, or two distinct parts), they do not collide and can coexist.

This rule applies regardless of field. What varies by field is which nouns are device-level vs. component-level — you determine that from Step 1.

# TERM CLASSIFICATION

After Steps 1–4, classify each surviving term as one of:
- DEVICE (the thing itself)
- COMPONENT (a part of the device)
- METHOD (how it was made or analyzed)
- METRIC (the performance quantity)
- ACTIVITY (the verb of the invention)
- FRAMING (words that signal formal engineering disclosure, such as "constraint", "tradeoff", "objective function")

# SIX-BLOCK QUERY SKELETON

Every well-formed query maps to some subset of these blocks:

1. DEVICE — the anchor noun (exactly one per query)
2. METHOD — how the invention is made or analyzed (optional, but commonly included)
3. METRIC — the performance quantity being measured or improved
4. ACTIVITY — the verb (optimization, fabrication, detection, etc.)
5. TARGET — what the activity acts on (geometry, parameters, composition, etc.)
6. FRAMING — a word that filters casual mentions and selects for formal engineering disclosures

ACTIVITY and TARGET should either be AND'd as separate terms, OR combined as a quoted bigram (e.g., adjacency forms like "X optimization" or "optimal X"). Google Patents has no proximity operator — quoted bigrams are the only way to require adjacency.

# GOOGLE PATENTS SYNTAX RULES

- AND and OR must be CAPITALIZED. Lowercase versions become search terms.
- Quotes enforce exact-token matching: "dog" matches dog but not dogs. Unquoted terms stem and expand.
- Parentheses group OR clauses. Use them whenever an OR is present.
- No NEAR, w/n, or other proximity operators exist. Use quoted bigrams for adjacency.
- Prefer quoted singles over unquoted terms for reproducibility and predictable narrowing.

# AND BUDGET — CALIBRATE PER INVENTION

The number of AND blocks is not fixed. Estimate the neighborhood before drafting:

- CROWDED domain + STABLE vocabulary → 5–6 ANDs of quoted singles
- SPARSE domain + STABLE vocabulary → 3–4 ANDs; more ANDs will zero out
- ANY domain + UNSTABLE vocabulary (fields where academic and patent terminology diverge sharply) → fewer ANDs, more OR-groups inside them to hedge vocabulary mismatch

Also consider anchor distinctiveness: a common anchor needs more ANDs to narrow; a narrow anchor needs fewer.

# OR-GROUP DISCIPLINE

OR groups are a crutch, not a default. Only add an OR group when you genuinely don't know which of several synonyms the patent literature uses, and the synonyms are roughly equally likely. Otherwise, pick the DOMINANT claim-language term and commit. Every unnecessary OR group widens recall and dilutes precision.

When in doubt between a paper term and a patent term, pick the patent term. Do not OR them.

# QUERY DIVERSITY

Generate {num_queries} queries that cover different facets of the invention:
- Some queries should anchor on the DEVICE + COMPONENT + METHOD
- Some on the DEVICE + METRIC + ACTIVITY + TARGET
- Some on the DEVICE + FRAMING + ACTIVITY
- Vary which block is dropped across queries to probe different regions of prior art
- Do NOT produce {num_queries} minor variations of the same query. Each query should hit a genuinely different slice of the literature.

# SELF-CHECK BEFORE EMITTING EACH QUERY

For every query you write, verify:
1. Does every term pass the novelty-filter check from Step 2? (No term in the query should describe what makes THIS invention different from others in the field.)
2. Does it contain exactly ONE device-class noun? (Object-collision check from Step 4.)
3. Has every term passed the claim-language check from Step 3?
4. Does ACTIVITY have a TARGET, either as a separate AND or as a quoted bigram?
5. Is the AND budget calibrated to the domain density?
6. Would this query, read aloud, describe a coherent invention category — not a specific invention?

# OUTPUT FORMAT

Output ONLY a Python list of query strings. No explanations, no reasoning, no commentary, no round labels, no category labels.

["query 1", "query 2", "query 3", ...]
"""




#ACTUATORS
invention = {'invention_name': 'Optimized Asymmetric Electrode Planar Piezoelectric Unimorph Actuator', 'technical_description': 'A planar piezoelectric unimorph actuator consisting of a piezoelectric layer (PZT-5H with d₃₁ = -274 pC/N, d₃₃ = 593 pC/N, d₁₅ = 741 pC/N) sandwiched between thin conductive electrodes, where the top electrode only partially covers the upper piezoelectric surface (width Welec) while the bottom electrode covers the entire lower surface, creating an asymmetric electrode configuration that produces fringing electric fields driving in-plane deflection. The device geometry is optimized through parametric sweeps of electrode width Welec, passive width Wpass, total width w, and layer thickness h, revealing nonmonotonic deflection characteristics where, for a piezoelectric layer thickness equal to half the total width (h = w/2), the optimal electrode width is approximately 32.5% of the overall width. The actuator achieves in-plane tip deflection on the order of 1% of transducer length (e.g., 1.09 µm for L = 100 µm, w = 4 µm, h = 2 µm, Welec = 1.6 µm, hₘ = 0.01 µm), with out-of-plane deflection two orders of magnitude smaller and gravity-induced deflection four orders smaller. The optimal electrode geometry ratio is scale-independent because the cross-sectional fringing electric field shapes are independent of length scale, and larger deflections result from minimizing width-to-thickness ratios, enabling design across micro- and macro-scale applications. The fabrication uses a simple two-electrode, three-layer process (sol-gel or prefabricated rolled PZT/PVDF sheets), and the electrode structure facilitates connection of one planar transducer to a multitude of others in large arrays to increase overall deflection or force.', 'problem_statement': 'While out-of-plane piezoelectric configurations are well established, in-plane deflection and asymmetric electrode placement have been underexplored in terms of actuation efficiency. Existing planar piezoelectric actuator designs rely on symmetric, full-coverage electrode structures (typically three electrodes) that avoid fringing electric fields, but this increases fabrication steps, wiring complexity, and cost. For simpler two-electrode unimorph configurations where the top electrode only partially covers the piezoelectric surface, the complex interplay of fringing electric fields with geometric parameters creates nonmonotonic deflection behavior that is not linear or easily predictable, making it impossible for designers to determine optimal electrode geometry without systematic parametric analysis. Prior planar designs with symmetrical electrodes do not encounter this nonmonotonic optimization challenge, leaving no established design guidelines for asymmetric electrode placement in slender in-plane unimorphs.', 'solution_approach': 'The invention solves the problem of suboptimal deflection in in-plane unimorph piezoelectric microactuators by using finite element analysis (FEA) to systematically sweep four geometric design parameters—electrode width, passive width, total width, and layer thickness—and identify optimal nondimensional parameter ratios that maximize planar tip deflection. The method accounts for the complex fringing electric field that arises when a single top electrode only partially covers the piezoelectric surface, which causes nonmonotonic deflection behavior unlike conventional parallel-electrode configurations. Through parameterized simulations, it was demonstrated that the optimal electrode width is approximately 32.5% of total width when layer thickness equals half the total width, and that this optimal ratio is scale-independent because the fringing field cross-sectional shape does not change with geometric scaling. To aid practical design, a MATLAB optimization function and two standalone COMSOL simulation applications were created and made publicly available, enabling designers to determine optimal electrode geometry for various piezoelectric materials and dimensions.', 'key_technical_features': ['Asymmetric two-electrode unimorph configuration with one electrode partially covering the top piezoelectric surface and a second electrode fully covering the bottom surface, producing in-plane deflection via fringing electric fields', 'Optimal electrode width ratio of approximately 32.5% of total unimorph width when the piezoelectric layer thickness equals half the total width (h = w/2)', 'Scale-independent optimal electrode geometry ratios derived from the fact that fringing electric field cross-sectional shapes are independent of geometric length scale', 'Nonmonotonic tip deflection behavior as a function of electrode width, requiring explicit optimization rather than linear parameter extrapolation, caused by the fringing electric field within the piezoelectric material', 'Design principle that smaller width-to-thickness ratios yield larger deflections for optimized electrode width pairs', 'Parameterized nondimensional design framework using ratios y/ymax, Welec/w, Wpass/w0, and h/w to enable application across different geometric scales and piezoelectric materials', 'MATLAB optimization function (Welec = unimorph_optimal_welec(w, h)) and two standalone COMSOL simulation applications made publicly available for determining optimal electrode geometry', 'Identification that optimal geometric ratios are material-dependent—optimal design ratios for one piezoelectric material are not necessarily optimal for another type'], 'domain_classification': 'MEMS / Piezoelectric Microactuators', 'statutory_category': ['Process', 'Machine', 'Manufacture'], 'inventor_keywords': ['in-plane unimorph piezoelectric microactuator', 'asymmetric electrode geometry', 'fringing electric field', 'nonmonotonic deflection', 'electrode width optimization', 'planar piezoelectric actuation', 'PZT-5H', 'finite element modeling', 'scale-independent design ratios', 'width-to-thickness ratio', 'microelectromechanical systems', 'unimorph cantilever'], 'citations': {'invention_name': ['The proposed in-plane unimorph actuator in this article consists of one electrode partially covering the piezoelectric top surface and a second electrode covering the entire bottom surface: [s02]', 'Optimal geometric design parameters were determined for the planar unimorph of the type for which piezoelectric material is interposed between the thin top and bottom electrodes, with the top electrode only covering a portion of the upper piezoelectric surface: [s05]', 'uncommon in-plane configurations have been sparsely explored: [s02]', 'the configuration presented herein is a slender, two-electrode unimorph that is subject to a significant fringing field: [s02]'], 'technical_description': ['piezoelectric material is sandwiched between thin conductive electrodes: [s03]', 'The piezoelectric strain coefficients for PZT-5H are experimentally matched to those reported in [29], where d₃₁ = -274 pC/N, d₃₃ = 593 pC/N, and d₁₅ = 741 pC/N: [s03]', 'The proposed piezoelectric unimorph simulated with an unmagnified tip deflection of 1.09 µm. Parameters are length L = 100 µm, width w = 4 µm, thickness h = 2 µm, electrode width Welec = 1.6 µm, and electrode thickness hₘ = 0.01 µm: [s04]', "if the thickness of the piezoelectric layer is half of the unimorph's total width, the optimal electrode width is approximately 32.5% of the overall width: [s05]", 'the optimal electrode geometry ratio is independent of scale, and larger deflections resulted from minimizing the width-to-thickness ratios: [s05]', "variations in the top electrode's width and the piezoelectric layer's thickness resulted in nonmonotonic deflection characteristics: [s05]", 'the fringing electric field is the cause of nonmonotonic tip deflection y when the parameters are linearly swept: [s04]', 'the cross-sectional shapes of the fringing electric fields are independent of the length scale, and the unimorph cross-sectional field determines the optimal deflection and not the unimorph length: [s04]', 'in-plane tip deflection along the y-axis can be on the order of 1% of the transducer length: [s03]', 'the out-of-plane deflection along the z-axis is two orders smaller, and the out-of-plane deflection solely due to 1G gravity is four orders smaller: [s03]', 'This electrode structure facilitates the connection of one planar transducer to a multitude of others in large arrays to increase overall deflection or force: [s02]', 'The fabrication process can be carried out using sol-gel [17-19,24], or be purchased prefabricated and poled in rolled piezoelectric sheets, e.g., lead zirconate titanate (PZT) [25,26] or polyvinylidene fluoride (PVDF) [27]: [s03]', 'simulations were performed for the dependence of planar deflection on four design parameters: electrode width Welec, passive width Wpass, total width w, and layer thickness h: [s04]', "The parameters held constant are the unimorph's length L = 100 µm, the electrode thickness hₘ = 0.01 µm, and the applied electric field: [s04]", 'symmetry in electrode placement is often not optimal: [s05]', "the material on the left side of the cross-section induces much greater strain due to the field lines' concentration and the field lines' dominant vertical orientation: [s03]", 'the curve representing h/w = 0.5 peaks at an electrode width ratio of Welec/w ≈ 0.325: [s04]'], 'problem_statement': ['While out-of-plane piezoelectric configurations are well established, both in-plane deflection and asymmetric electrode placement have been underexplored in terms of actuation efficiency.: [s01]', 'uncommon in-plane configurations have been sparsely explored [17-21]: [s02]', 'their bimorph structures avoid the fringing electric field issue by using three electrodes that cover all or most of the entire upper and lower surfaces: [s02]', 'While three electrodes would increase deflection performance, doing so would increase the number of fabrication steps, wiring complexity, and cost: [s02]', 'the fringing electric fields play a measurable role in performance for electrode geometries where the electrodes do not fully and equally cover opposing surfaces: [s02]', 'Due to the complex interplay between the fringing electric fields, the width and thickness of the piezoelectric material, and the asymmetric widths of the surface electrodes: [s02]', 'The results suggest that the deflection response of the unimorph is not linear or easily predictable based on incremental changes in these parameters.: [s05]', "variations in the top electrode's width and the piezoelectric layer's thickness resulted in nonmonotonic deflection characteristics: [s05]", 'The results suggest that the cause of the behavior of this nonlinear design is due to the fringing electric field within the piezoelectric.: [s05]', 'A key finding of this study is that symmetry in electrode placement is often not optimal.: [s05]', 'This finding is significant because it identifies the nonmonotonic behavior caused by the width of the singular upper electrode. This is a novel finding because of the symmetrical nature of electrodes in previous planar designs that do not have this issue.: [s04]', 'Due to this nonmonotonic behavior, the design of planar piezoelectric actuators that only have a single upper electrode must include the optimization of the electrode structure to maximize efficiency.: [s04]', 'These results are unlike what is conventionally obtained from the cross-sections of non-fringing, parallel electric field configurations [17-21] that would result in monotonic tip deflections if the design parameters were swept.: [s04]'], 'solution_approach': ['simulations were performed for the dependence of planar deflection on four design parameters: electrode width Welec, passive width Wpass, total width w, and layer thickness h: [s04]', 'the fringing electric field is the cause of nonmonotonic tip deflection y when the parameters are linearly swept: [s04]', "if the thickness of the piezoelectric layer is half of the unimorph's total width, the optimal electrode width is approximately 32.5% of the overall width: [s05]", 'the cross-sectional shapes of the fringing electric fields are independent of the length scale: [s04]', 'These results are unlike what is conventionally obtained from the cross-sections of non-fringing, parallel electric field configurations [17-21] that would result in monotonic tip deflections: [s04]', 'three freely available unimorph design tools in the form of a MATLAB function and two standalone COMSOL applications have been created and are available for download: [s04]', 'Due to the complex interplay between the fringing electric fields, the width and thickness of the piezoelectric material, and the asymmetric widths of the surface electrodes, finite element modeling is used to parameterize and understand the effects on performance: [s02]'], 'key_technical_features': ['The proposed in-plane unimorph actuator in this article consists of one electrode partially covering the piezoelectric top surface and a second electrode covering the entire bottom surface: [s02]', 'the curve representing h/w = 0.5 peaks at an electrode width ratio of Welec/w ≈ 0.325: [s04]', 'the shape of the voltage contours and electric field lines (as shown in Figure 5) is independent of scale: [s04]', 'the fringing electric field is the cause of nonmonotonic tip deflection y when the parameters are linearly swept: [s04]', 'thinner widths yield larger deflections for optimized electrode region width pairs: [s04]', 'Tip deflection is expressed as y/ymax ≤ 1, where Ymax is the largest deflection found by sweeping the design parameters: [s04]', 'The MATLAB function returns the optimal value of electrode width Welec given inputs of width w and layer thickness h: [s04]', 'the optimal geometric ratios of one piezoelectric material are not necessarily the optimal design ratios for another type of piezoelectric material: [s05]', 'symmetry in electrode placement is generally nonoptimal: [s01]', 'the design of planar piezoelectric actuators that only have a single upper electrode must include the optimization of the electrode structure to maximize efficiency: [s04]', 'optimal electrode geometry is independent of scale: [s01]', 'the smaller the ratio of width to thickness, the larger the deflection: [s01]'], 'domain_classification': ['Piezoelectric microactuators have been widely used for actuation, sensing, and energy harvesting: [s01]', 'energy-efficient piezoelectric transducers convert electrical energy into mechanical movements or vice versa, which establishes them as useful components in actuation, fine resolution sensing, or energy harvesting implementations for applications such as biomedical, microrobotics, and precision instrumentation: [s02]', 'The findings contribute to the development of efficient design strategies that optimize the performance of planar actuators for potential implications for microelectromechanical systems (MEMS): [s01]', 'in-plane piezoelectric transducers often achieve a faster response, a larger generative force, and improved electromechanical coupling: [s02]', 'uncommon in-plane configurations have been sparsely explored: [s02]'], 'statutory_category': ['The proposed in-plane unimorph actuator in this article consists of one electrode partially covering the piezoelectric top surface and a second electrode covering the entire bottom surface: [s02]', 'This electrode structure facilitates the connection of one planar transducer to a multitude of others in large arrays to increase overall deflection or force: [s02]', 'Optimal geometric design parameters were determined for the planar unimorph of the type for which piezoelectric material is interposed between the thin top and bottom electrodes, with the top electrode only covering a portion of the upper piezoelectric surface: [s05]', 'three electrodes would increase deflection performance, doing so would increase the number of fabrication steps, wiring complexity, and cost, where planar arrays can be used to regain any loss in deflection: [s02]', 'two downloadable COMSOL applications for modeling a variety of other piezoelectric materials are made publicly available: [s05]', 'sweeping the geometric parameters, optimal parameter combinations are established: [s02]'], 'inventor_keywords': ['in-plane configurations that bend in the direction of width are capable of faster responses, greater deflection, greater resonance frequency, and greater blocking force: [s02]', 'the fringing electric field within the piezoelectric: [s05]', 'nonmonotonic deflection characteristics: [s05]', 'asymmetric electrode geometry on the performance of slender unimorph actuators that deflect in-plane: [s01]', 'optimal electrode geometry is independent of scale: [s01]', 'the smaller the ratio of width to thickness, the larger the deflection: [s01]', 'the default PZT-5H produces the best performance of the provided choices: [s04]', 'finite element modeling is used to parameterize and understand the effects on performance: [s02]', 'symmetry in electrode placement is generally nonoptimal: [s01]', 'microelectromechanical systems (MEMS): [s01]', 'slender, two-electrode unimorph that is subject to a significant fringing field: [s02]', 'the optimal electrode width is approximately 32.5% of the overall width: [s05]']}}

#COPPER GRAPHENE
# invention = {'invention_name': '3D Interlocking Graphene Network Reinforced Copper Matrix Composites', 'technical_description': "A bottom-up in-situ synthesis method fabricates copper matrix composites reinforced by a three-dimensional interlocking graphene network (3D-IGN) with a bio-inspired 'brick-bridge-mortar' structure. Spherical Cu powders (1.0 µm average particle size) are ball milled at 400 rpm for 3 h under argon with a 1:20 powder-to-ball mass ratio, then 24.0 g of resulting Cu flakes are impregnated with 0.320 g sucrose dissolved in ethanol/water (20 mL/40 mL), dried at 70°C, cold pressed at 400 MPa for 3 min, and calcined at 900°C for 1 h in Ar-H₂ atmosphere (Ar: 200 mL·min⁻¹; H₂: 100 mL·min⁻¹) to in-situ synthesize 3D-IGN on the assembled Cu flakes template. The calcinated bulk is consolidated by hot-pressing at 950°C for 60 min at 50 MPa under 10⁻⁴ Pa vacuum, then hot-rolled with 0.2 mm reduction per pass and intermediate annealing at 800°C for 2 min, yielding well-crystallized few-layer graphene (5–10 layers, 0.34 nm layer spacing) with intimate Cu-O-C interfacial bonding and refined Cu grain size of 0.45 µm. The resulting composites achieve a dynamic compressive strength of 511 MPa and energy absorption of 611.2 MJ·m⁻³ at 4000 s⁻¹ strain rate, tensile strength of 290 MPa with 7% elongation, thermal conductivity of 360.62 W·m⁻¹·K⁻¹ parallel to rolling direction, and strain rate sensitivity values of 0.038–0.048, demonstrating simultaneously enhanced dynamic strength and ductility through dislocation blocking, grain boundary restriction, and heat-induced softening alleviation.", 'problem_statement': 'Copper and its alloys used in high strain rate applications suffer from adiabatic temperature rise and thermal softening during dynamic deformation, leading to the formation of catastrophic adiabatic shear bands (ASBs) and pre-failure of structural components. Existing graphene-reinforced copper composites with uniform or random reinforcement distributions lack effective spatial architecture design, resulting in insufficient dislocation pinning, poor thermal management, and strain localization under high strain rates. The successful fabrication of graphene/Cu composites with controlled three-dimensional reinforcement architectures and the study of their high strain-rate dynamic behaviors remain largely unexplored. Furthermore, conventional ceramic particle reinforcements in metal matrix composites have lower thermal conductivity than the metal matrix and suffer from interfacial degradation at elevated temperatures, amplifying thermal softening and localization effects during dynamic loading.', 'solution_approach': "The invention solves the problem of poor dynamic mechanical performance in copper under high strain-rate loading by fabricating copper matrix composites reinforced with a bio-inspired 'brick-bridge-mortar' three-dimensional interlocking graphene network (3D-IGN). The 3D-IGN is constructed via a bottom-up assembly and in-situ synthesis strategy: copper flakes serve as both template and catalyst, coated with sucrose as a solid carbon source, then calcinated to grow an interconnected graphene network on the Cu flake assembly surfaces, followed by densification through hot-pressing and hot-rolling. The interlocking network structure simultaneously blocks dislocation movement, restricts grain boundary sliding, and improves horizontal thermal conductivity to alleviate heat-induced softening during adiabatic deformation. Experimentally demonstrated results show that 3D-IGN/Cu achieves simultaneously enhanced dynamic strength and ductility compared to uniformly-distributed RGO/Cu and pure Cu across strain rates from 1000 to 8000 s⁻¹, with dynamic compressive strength of 511 MPa and energy absorption of 611.2 MJ·m⁻³ at 4000 s⁻¹ (7% and 21% higher than pure Cu, respectively). Finite element simulations further confirmed the role of the graphene network in strain delocalization, and the flexible IGN structure maintained interfacial integrity even at 8000 s⁻¹ strain rates.", 'key_technical_features': ["Bio-inspired 'brick-bridge-mortar' 3D interlocking graphene network (3D-IGN) architecture as reinforcement in copper matrix, where 'bridge' structures between laminated layers provide superior dynamic properties over conventional 'brick-and-mortar' designs", 'Bottom-up fabrication via in-situ synthesis: ball-milled copper flakes (average 1 µm) serve as both template and catalyst, coated with sucrose carbon source by impregnation and drying, then calcinated to grow interconnected few-layer graphene (5-10 layers, 0.34 nm layer spacing) on Cu flake assembly surfaces', 'Densification by hot-pressing followed by hot-rolling (up to 70% reduction) that preserves the 3D-IGN structural integrity while eliminating voids and defects, achieving tensile strength of 290 MPa with 7% elongation', 'Dislocation pinning and grain boundary confinement mechanism: the network structure controls grain size to 0.45 µm before and after deformation at 8000 s⁻¹, compared to severe coarsening (7.82 µm) in uniformly-distributed RGO/Cu', 'Cu-O-C interfacial bonding between in-situ grown IGN and Cu matrix that withstands shock impact up to 8000 s⁻¹ strain rate, with the flexible IGN transferring and relaxing shock loading to eliminate shear localization', 'Simultaneous enhancement of dynamic compressive strength and ductility across strain rates of 1000-8000 s⁻¹, with 511 MPa strength and 611.2 MJ·m⁻³ energy absorption at 4000 s⁻¹ (7% and 21% higher than pure Cu)', 'Facilitation of stacking fault emission from graphene/Cu interface at relatively low strain rates (~10⁴ s⁻¹) due to extreme confinement network structure, enabling coordination deformation typically observed only at ultra-high strain rates above 10⁶ s⁻¹', 'Anisotropic thermal conductivity improvement in the horizontal direction that alleviates adiabatic heat-induced softening and prevents formation of adiabatic shear bands (ASBs) during high strain-rate deformation'], 'domain_classification': 'Advanced Materials / Metal-Matrix Composites', 'statutory_category': ['Process', 'Manufacture', 'Composition of Matter'], 'inventor_keywords': ['three-dimensional interlocking graphene network', '3D-IGN/Cu', 'bio-inspired brick-bridge-mortar structure', 'copper matrix composites', 'split Hopkinson pressure bar', 'strain rate sensitivity', 'adiabatic shear band suppression', 'in-situ graphene growth', 'dislocation pinning', 'geometric necessary dislocations', 'Williamson-Hall method', 'finite element method simulation', 'viscous drag mechanism'], 'citations': {'invention_name': ['copper matrix composites (CMCs) reinforced by three-dimensional interlocking graphene network (3D-IGN): [s02]', "a unique bio-inspired 'brick-bridge-mortar' structure: [s02]", '3D-IGN/Cu bulk composites were synthesized via a bottom-up and in-situ synthesis method: [s04]', 'in-situ synthesis 3D-IGN in the assembled Cu flakes template: [s04]', 'the complete network structure of 3D-IGN was exposed after etching the surface of the Cu matrix: [s05]'], 'technical_description': ['15.0 g of spherical Cu powders with an averaged particle size of 1.0 µm were ball milled in a stainless-steel mixing jar at a speed of 400 rpm for 3 h under the protection of argon atmosphere, with a mass ratio between the Cu powder and the stainless-steel milling ball of about 1:20: [s04]', '0.320 g sucrose was dissolved in the hybrid solution of ethanol and water (20 mL/40 mL) and stirred for 30 min to obtain a uniform and transparent solution: [s04]', '24.0 g Cu flakes were added into the solution under stirring, sonicated for 20 min and then heated at 80°C under constant magnetic stirring until the solution was fully vaporized: [s04]', 'dried in a vacuum oven at 70°C for 3 h to remove residual solution: [s04]', 'cold pressed (400 MPa, 3 min) into a green body block: [s04]', 'calcined in an Ar-H₂ mixed atmosphere (Ar: 200 mL.min⁻¹; H₂: 100 mL.min⁻¹) with a holding temperature 900°C and incubation time of 1 h: [s04]', 'consolidated by hot-pressing at 950°C for 60 min with a pressure of 50 MPa, under a high vacuum level of 10⁻⁴ Pa level: [s04]', 'The rolling reduction during each rolling cycle was 0.2 mm. After each pass, the samples were placed in a box furnace at 800°C for 2 min: [s04]', 'The well-crystallized few-layer graphene (5-10 layers) has a layer spacing of 0.34 nm: [s05]', 'the network structure had a strong pinning force on the grain growth of the Cu matrix, which causes a small average size of 0.45 µm: [s05]', 'high tensile strength of 290 MPa and a moderate elongation of 7% were achieved after hot-rolling: [s05]', '3D-IGN/Cu reached the dynamic compressive strength of 511 MPa and energy absorption of 611.2 MJ.m⁻³ which were 7% and 21% higher than that of pure Cu: [s05]', '3D-IGN/Cu exhibited higher SRS values than pure Cu... high SRS values of 0.038-0.048: [s06]', 'the thermal conductivity of 3D-IGN/Cu parallel to the rolling direction was 360.62 W.m⁻¹.K⁻¹, while in the vertical rolling direction the value was only 311.76 W.m⁻¹.K⁻¹: [s06]', 'The interlocking network structure not only blocks dislocation movement and restricts grain boundary sliding, but also alleviates the heat-induced softening by improving the thermal conductivity in the horizontal direction: [s02]', 'the in-situ growth strategy not only solved graphene agglomeration issue but also facilitated to an intimate interfacial bonding between 3D-IGN and Cu: [s05]', 'the dislocation density level of 2.2 X 10¹⁵ in 3D-IGN/Cu after 8000 S impact: [s06]', 'the ratio (ID/IG) between D band (1350) and G band (1580) changing from 0.85 to 0.95 after 50% deformation: [s05]', 'a higher stress level, which is more than 2.4 times, are observed in 3D-IGN/Cu compared to the uniformly dispersed laminated graphene/Cu: [s06]', 'Owing to the Cu-O-C bonding between the in-situ grown IGN and Cu, the bonding strength of IGN/Cu interface could be sufficient to withstand the shocking impact under high strain rate: [s05]'], 'problem_statement': ['The fraction of heat extracted becomes smaller as the increase of the strain rate during impact loading, leading to a sharp temperature rise and softening: [s03]', 'Undesirable pre-failure normally happens and therefore causes potentially harmful effects to the structural materials.: [s03]', 'adiabatic shear bands (ASBs) prefer to nucleate in those alloys (e.g. Cu-Zn and Cu-Al alloys) with lower stacking fault energy: [s03]', 'the successful composite fabrication and the related high strain-rate dynamics of the graphene/Cu system is lack of research.: [s03]', 'the thermal conductivity of ceramic particles is lower than that of the metal matrix, and it cannot effectively transfer heat away: [s06]', 'the interfacial strength decreases at high temperature, leading to interface cracking and failure of the material under conditions of higher temperature and deformation rate compared to quasi-static deformation: [s06]', 'the localization effect will be more significant after thermal softening of the matrix under dynamic deformation conditions: [s06]', 'The formation of adiabatic shear bands will further exacerbate the incompatibility thus leading to matrix pre-fracture.: [s06]', 'this effect is often further amplified by the incorporation of a large number of heterogeneous interfaces: [s06]', 'the high-strain-rate adiabatic deformation process leads to the accumulation of a large amount of heat in the material, which is difficult to dissipate instantly: [s06]', 'This often causes thermal softening effects in the local areas, dynamic recrystallization, and even catastrophic adiabatic shear bands.: [s06]', 'the dynamic mechanical properties under high strain rate were severely degraded by the poor interfacial bonding between reinforcement and the metal matrix: [s05]', 'the lacking of the efficient dislocation pinning mechanism in RGO/Cu and Cu results in the more significant increase in the flow strength with the increased strain rate: [s06]', 'The severe coarsening phenomenon happened in RGO/Cu with average grain size 7.82 µm after hot-rolling deformation: [s05]', 'Due to the limited control of the position and the orientation of the reinforcement during preparation, the exact regulations based on experiments have been rarely reported on the dynamic properties of graphene reinforced metal matrix composites.: [s06]', 'the homogeneously distributed RGO/Cu only exhibits a much lower flow strength as well as the dynamic ductility with the same weight ratio of graphene: [s05]', 'At sufficiently high rates of deformation, the extracted heat can be neglected, and one has an adiabatic condition: [s03]'], 'solution_approach': ["copper matrix composites (CMCs) reinforced by three-dimensional interlocking graphene network (3D-IGN) with a unique bio-inspired 'brick-bridge-mortar' structure: [s02]", 'The interlocking network structure not only blocks dislocation movement and restricts grain boundary sliding, but also alleviates the heat-induced softening by improving the thermal conductivity in the horizontal direction: [s02]', '3D-IGN/Cu shows simultaneously enhanced dynamic strength and ductility as compared to the uniformly-distributed RGO/Cu and pure Cu at the specific strain rate from 1000 to 8000 s⁻¹: [s02]', "copper matrix composites reinforced by a bio-inspired 'brick-bridge-mortar' 3D interlocking graphene network architecture (3D-IGN/Cu), were fabricated via a bottom-up assembly and in-situ synthesis strategy: [s03]", 'even under a high strain rate of 4000 s⁻¹, 3D-IGN/Cu reached the dynamic compressive strength of 511 MPa and energy absorption of 611.2 MJ.m⁻³ which were 7% and 21% higher than that of pure Cu: [s05]', 'The finite element simulation results further confirm the important role of the graphene network on strain delocalization: [s02]', 'the interface remained intact even under a high strain rate up to 8000: [s05]'], 'key_technical_features': ["the 'bridge' structures between the laminated layers of nacre and its inspired materials play the determined role in affecting their dynamic properties: [s03]", "composites with 'brick-bridge-mortar' structural should have better dynamic properties than those with 'brick-and-mortar' structure: [s03]", 'copper flakes obtained by ball milling of spherical copper powder with an average size of 1 µm were chosen as the building blocks for the assembly, acting as both the template and also the catalyst: [s05]', 'Sucrose as the solid carbon source was coated on the surface of copper flakes by a convenient impregnation and drying method: [s05]', 'The well-crystallized few-layer graphene (5-10 layers) has a layer spacing of 0.34 nm: [s05]', 'After further densification by hot-pressing and hot-rolling, the 3D-IGN/Cu composites could be fabricated without the graphene agglomeration and debonding problems of the ex-situ strategies: [s05]', 'high tensile strength of 290 MPa and a moderate elongation of 7% were achieved after hot-rolling: [s05]', 'the network structure had a strong pinning force on the grain growth of the Cu matrix, which causes a small average size of 0.45 µm: [s05]', 'The severe coarsening phenomenon happened in RGO/Cu with average grain size 7.82 µm after hot-rolling deformation: [s05]', 'Owing to the Cu-O-C bonding between the in-situ grown IGN and Cu, the bonding strength of IGN/Cu interface could be sufficient to withstand the shocking impact under high strain rate: [s05]', 'the flexible nature of IGN could also transfer and relax the shock loading at the interface and thus eliminate the shear localization: [s05]', 'the SFs structures in the IGN-8000 suggested that the extreme confinement network structure facilitates the emission of Shockley partials from graphene/Cu interface under a relatively low strain rate ~ 10⁴ s⁻¹: [s05]', 'graphene distributed at the grain boundaries blocks the dislocation movement and confines the dislocation lines within one grain without creating slip lines through multiple grains, thus avoiding the formation of adiabatic shear bands (ASBs): [s05]', 'alleviates the heat-induced softening by improving the thermal conductivity in the horizontal direction: [s02]', 'the interlocking graphene network could still be well preserved: [s05]', 'the structural integrity of 3D-IGN was maintained intact with little damage even after the severe deformation process: rolling deformation with 70% strain: [s05]'], 'domain_classification': ['copper matrix composites (CMCs) reinforced by three-dimensional interlocking graphene network (3D-IGN): [s02]', 'A. Metal-matrix composites (MMCs): [s01]', 'A. 3-Dimensional reinforcement: [s01]', 'B. Impact behavior: [s01]', 'designing shock-resistant metallic structures: [s02]', 'fabricate CMCs with network architecture and superior dynamic properties for high-rate applications: [s02]', 'the dynamic compression properties of bio-inspired three-dimensional interlocking graphene network reinforced copper matrix composites: [s01]', 'the spatial architecture of graphene plays an important role in affecting the final dynamic mechanical performance: [s05]'], 'statutory_category': ['copper flakes obtained by ball milling of spherical copper powder with an average size of 1 µm were chosen as the building blocks for the assembly: [s05]', 'Sucrose as the solid carbon source was coated on the surface of copper flakes by a convenient impregnation and drying method: [s05]', 'The assembly of the hybrid precursors formed by cold-pressing was calcinated in a tube furnace, during which process 3D-IGN was in-situ constructed on the surface of the Cu flakes assembly: [s05]', 'After further densification by hot-pressing and hot-rolling, the 3D-IGN/Cu composites could be fabricated without the graphene agglomeration and debonding problems: [s05]', 'This work offers a promising bottom-up tactic to fabricate CMCs with network architecture and superior dynamic properties: [s02]', 'copper matrix composites (CMCs) reinforced by three-dimensional interlocking graphene network (3D-IGN) with a unique bio-inspired brick-bridge-mortar structure: [s02]', 'the 3D-IGN/Cu composites could be fabricated without the graphene agglomeration and debonding problems of the ex-situ strategies: [s05]', 'hot rolling deformation with 50% reduction in thickness, the interlocking graphene network could still be well preserved: [s05]'], 'inventor_keywords': ['three-dimensional interlocking graphene network (3D-IGN): [s02]', 'bio-inspired brick-bridge-mortar structure: [s02]', 'copper matrix composites (CMCs): [s02]', 'the SRS values (m), reflecting the sensitivity of the flow stress to changes of strain rate: [s06]', 'geometric necessary dislocations (GND) during the rolling deformation and dynamic shocking tests: [s06]', 'X-ray line broadening of full-width at half maximum (FWHM) based on Williamson-Hal (W-H) method: [s06]', 'simulated the dynamic compression behavior of 3D-IGN/Cu and uniformly-dispersed laminated graphene/Cu using the finite element method: [s06]', 'the viscous drag mechanism which is supposed to plays a much more important role in the high strain rate deformation process: [s06]', 'avoiding the formation of adiabatic shear bands (ASBs): [s05]', 'dislocation blocking effect of the network architecture: [s06]', 'strain rate from 1000 to 8000 s⁻¹: [s02]', 'in-situ growth strategy not only solved graphene agglomeration issue but also facilitated to an intimate interfacial bonding between 3D-IGN and Cu: [s05]', 'the bridge structure can be clearly identified from the Cu-etched surface: [s05]', 'strain delocalization: [s02]']}}
#SAW PUMP

queries = stage_2_generate_queries(invention)