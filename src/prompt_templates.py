"""
Prompt Templates for Patent Search System

Contains all prompt templates for:
- Potential Invention Identification
- Query generation
- Patent detail fetching
- Patent analysis
- Batch operations

All templates are designed to produce structured JSON outputs.
"""
import json

class PromptTemplates:
    """Collection of prompt templates for patent search operations"""

    @staticmethod
    def generate_search_queries(invention_data: dict, num_queries: int = 5) -> str:
        """
        Generate prompt for creating patent search queries

        Args:
            invention_data: Dictionary containing invention details
            num_queries: Number of queries to generate

        Returns:
            Formatted prompt string
        """
        return f"""You are a patent agent generating Google Patent search queries to find prior art for this invention.
 
INVENTION: {invention_data.get('invention_name', 'Unknown')}
 
TECHNICAL DESCRIPTION:
{invention_data.get('technical_description', 'N/A')}
 
PROBLEM STATEMENT:
{invention_data.get('problem_statement', 'N/A')}
 
SOLUTION APPROACH:
{invention_data.get('solution_approach', 'N/A')}
 
KEY TECHNICAL FEATURES:
{', '.join(invention_data.get('key_technical_features', []))}
 
Generate exactly {num_queries} Google Patent search queries by following ALL steps below.
 
## STEP 1: DETERMINE STATUTORY CATEGORY
Classify the invention into one or more of the four patent-eligible categories:
- Process: a method, sequence of steps, or procedure
- Machine: a device or apparatus with specific components
- Manufacture: an article or product made by a process
- Composition of matter: a new material, mixture, or compound
 
Identify the PRIMARY category. This determines query focus:
- Composition of Matter or Manufacture: "does this material/product exist?" then "has anyone made it this way?"
- Process: "has anyone used these steps before?" then "on these materials/inputs?"
- Machine: "does this device exist?" then "has anyone used these components this way?"
 
## STEP 2: EXTRACT KEY TERMS
List every significant technical term from the extraction. Group them into:
- Materials/Components
- Structure/Architecture/Configuration
- Process/Method/Steps
- Properties/Function/Performance
- Problem/Application/Field
 
CRITICAL: Every query term MUST trace back to this list OR to a field-standard synonym from Step 3.
 
## STEP 3: EXPAND WITH FIELD-STANDARD SYNONYMS AND BUILD SYNONYM CHAINS
For each key concept in Step 2, identify the standard technical term used in the broader field, even if the extraction does not use that exact word. A patent agent uses domain knowledge to recognize that a concept described in the extraction may be known by a different established term in the literature and patent databases.
 
For each key concept, build a **synonym chain** — a group of interchangeable terms that all refer to the same or closely related concept. These chains will be used with OR inside parentheses in queries.
 
**Target chain length: 3-5 terms per chain when synonyms exist.** Do not settle for 2-term chains if more valid synonyms exist. Only use shorter chains when the concept genuinely has fewer field-standard synonyms.
 
General principles for building chains:
- Include the extraction's term + broader/narrower field-standard terms
- Include both the specific technical name and its common generic equivalent
- Include different word forms if patents use them (noun vs adjective, hyphenated vs non-hyphenated)
- Include acronyms alongside their spelled-out forms
- Group together only terms that a patent examiner would recognize as describing the same concept
 
**Method/technique families — RELAXED SUBSTITUTION RULE:**
When the concept is a method, technique, or analytical approach, include RELATED techniques in the same family, not just strict synonyms. Patents often address the same underlying problem using different but related techniques, so prior art crosses technique boundaries.
 
For method concepts, ask: "Would a patent examiner reviewing prior art for this invention recognize these techniques as addressing the same underlying design or analysis problem?" If yes, they belong in the same OR chain even if the techniques differ in specifics.
 
This applies to method families like optimization methods, analysis methods, synthesis methods, fabrication methods, modeling methods, and control methods — where multiple named techniques share a common purpose.
 
Only use synonyms and related techniques you are confident are field-standard. Do NOT invent terms.
 
## STEP 3b: USE SYNONYM CHAINS IN QUERIES
When a concept has multiple field-standard names, wrap the chain in parentheses with OR:
concept_X AND (synonym1 OR synonym2 OR synonym3) AND concept_Y
 
This catches patents using different vocabulary for the same idea. Use synonym chaining especially in Rounds 4 and 5 where you are searching concepts, not specific materials.
 
**CRITICAL: OR chains must contain ONLY true synonyms — terms that are interchangeable and describe the same underlying concept.**
 
Before writing an OR chain, ask: "Could I substitute any term in this chain for any other without changing what I'm searching for?" If yes, the chain is valid. If no, the terms belong in separate AND clauses, not an OR.
 
Terms belong in different AND clauses (not OR) when they represent different aspects of the invention — such as a component vs a measurement, a material vs a process, a cause vs an effect, or an object vs an attribute.
 
## STEP 3c: DISAMBIGUATE VAGUE TERMS
Some words are too generic on their own and will return irrelevant results. When a concept term is vague, it MUST always be paired with WHAT it applies to.
 
Generic concept words (e.g., optimization, analysis, modeling, simulation, control, improvement, design, characterization) are ambiguous on their own because they appear across every technical field.
 
**MANDATORY: Never use a generic concept word alone in a query.** The preferred strategy is to build a synonym chain of quoted compound phrases where the generic word is prefixed by a specific modifier.
 
Strategy 1 (preferred) — Build a chain of quoted compound phrases:
Wrap each variant as a 2-word quoted phrase combining a modifier with the generic word. A good chain has 3-5 quoted compound phrases.
 
Strategy 2 — Pair the vague word with the specific domain object via AND:
Connect the vague word to the specific thing being acted upon.
 
Strategy 3 — Combine both: use a compound phrase chain AND pair with the domain object.
 
**Quoted compound phrases inside OR chains are ENCOURAGED, not discouraged.** A chain like `("compound_A" OR "compound_B" OR "compound_C" OR "compound_D")` counts as ONE concept for the precision rule, not four separate quoted phrases.
 
If a query contains a generic concept word that is not part of a synonym chain AND not paired with its domain object in the same query, the query FAILS validation and must be rewritten.
 
## STEP 4: IDENTIFY NOVELTY
Read the problem statement and solution approach to rank what is MOST novel vs LEAST novel:
- What does the extraction say is "already known," "existing," "conventional," or "prior work"? → LEAST novel
- What does the extraction say is "new," "novel," "underexplored," "first," "unlike," or "distinct from"? → MOST novel
 
Spend MORE queries on what is novel. Spend FEWER on what is known.
 
### STEP 4b: IDENTIFY DUAL NOVELTY AXES
Most inventions have TWO independent novelty axes. You must identify both and allocate queries to each:
 
1. **WHAT axis (the thing itself):** The physical device, material, structure, or composition being claimed. Queries search: "does this thing exist?"
 
2. **HOW axis (the method of discovery/creation):** The process, optimization method, analysis technique, or design methodology that produced or characterizes the thing. Queries search: "has anyone used this method before?"
 
Examples of HOW axis signals in an extraction:
- The title contains a method verb (Optimizing, Designing, Synthesizing, Analyzing, Simulating)
- The solution approach describes a computational, analytical, or experimental methodology
- Design tools, software, or algorithms are provided
- The extraction emphasizes a discovery, finding, or characterization
 
CRITICAL: If the HOW axis exists, it MUST receive its own dedicated queries, not just be mentioned as a secondary term in WHAT-axis queries. Prior art on the HOW axis is often in a completely different field and will not be found by WHAT-axis queries.
 
## STEP 5: BUILD QUERIES ACROSS ROUNDS
 
Allocate {num_queries} queries across these rounds based on statutory category and novelty. Not all rounds need equal queries. Skip rounds that don't apply.
 
**Round 1 — Landscape:** Search the specific materials, components, or device type to map what already exists.
 
**Round 2 — Function/Property:** Combine materials/components with the target properties, functions, or problems solved.
 
**Round 3 — Process/Method:** Search the specific process steps, method, or technique. For process inventions, this is the core round.
 
**Round 4 — Concept (drop specifics):** Replace specific materials/components with generic equivalents and search the underlying structural, architectural, or methodological concept. This is where hidden and distant prior art lives.
 
**Round 5 — Broadest:** Search the design principle or method at its most abstract level. Include field-standard synonyms from Step 3 here.
 
## QUERY FORMAT RULES
- Use AND, OR, "", and () operators
- Each term is MAXIMUM 2 words
- **MANDATORY: Any multi-word phrase (2+ words) MUST be wrapped in double quotes.** Example: write "tip deflection" NOT tip deflection. Write "electrode width" NOT electrode width.
- **MANDATORY: Every concept in a query MUST be connected by explicit AND.** Example: write `piezoelectric AND "unimorph actuator" AND electrode` NOT `piezoelectric unimorph actuator electrode`.
- Use OR to group synonyms within parentheses
- Use AND to connect concepts (always explicit, never implicit)
- Typical query has 3-5 terms connected by AND
- Do NOT use site:, -, or other advanced operators
- ANCHORING RULE: Every query MUST include at least one highly specific technical phrase in "" quotes to prevent matching unrelated fields
 
## PRECISION vs RECALL BALANCE
Each standalone quoted phrase acts as a hard filter — stacking multiple standalone quoted phrases creates empty result sets.
- Use MAXIMUM 1-2 standalone quoted phrases per query (phrases outside OR chains)
- Quoted phrases INSIDE an OR chain do not count toward this limit — a full OR chain of quoted compounds counts as ONE concept
- Fill the rest of the query with single keywords and OR synonym chains
- If you have 3+ standalone quoted phrases, remove quotes from all but the most distinctive one
- Target query structure: 3-4 AND concepts, where 1 is a standalone quoted anchor phrase and at least 1 is an OR synonym chain of 3-5 terms (single words or quoted compound phrases)
 
## VALIDATION CHECK (perform before outputting)
For every query you generate, verify:
1. Every multi-word phrase has quotes around it
2. Every concept is connected by explicit AND
3. At least one quoted phrase exists for anchoring
4. NO MORE than 2 STANDALONE quoted phrases (quoted compounds inside OR chains don't count)
5. Every OR chain contains ONLY true synonyms — terms that describe the same concept. If terms belong to different categories, use AND instead of OR.
6. OR chains contain 3-5 terms when valid synonyms exist (only shorter if the concept has fewer real synonyms)
7. Any generic concept word (optimization, analysis, modeling, simulation, control, design, etc.) is either part of a compound-phrase OR chain, OR paired with its specific domain object via AND — never alone
8. Query has 3-4 AND-connected concepts total
If any query fails these checks, rewrite it before outputting.
 
## OUTPUT FORMAT
Output ONLY a Python list of query strings. No explanations, no reasoning, no commentary, no round labels.
 
["query 1", "query 2", "query 3", ...]
 
The list must contain exactly {num_queries} strings.
"""

    @staticmethod
    def generate_concept_scratchpad(invention_data: dict) -> str:
        """
        Call 1 of the two-call query generation pipeline.
        Extracts concepts with specificity ratings, patent-drafter synonyms,
        synonym chains, novelty axes, and top-3 anchor keywords.
        Output feeds directly into generate_queries_from_scratchpad().
        """
        return f"""You are a patent agent preparing to search Google Patents for prior art.

INVENTION: {invention_data.get('invention_name', 'Unknown')}

TECHNICAL DESCRIPTION:
{invention_data.get('technical_description', 'N/A')}

PROBLEM STATEMENT:
{invention_data.get('problem_statement', 'N/A')}

SOLUTION APPROACH:
{invention_data.get('solution_approach', 'N/A')}

KEY TECHNICAL FEATURES:
{', '.join(invention_data.get('key_technical_features', []))}

Perform the following steps and output the result as structured JSON.

## STEP 1: STATUTORY CATEGORY
Classify the invention's PRIMARY patent-eligible category: Process, Machine, Manufacture, or Composition of Matter.

## STEP 2: NOVELTY AXES
Identify:
- WHAT axis: the physical thing being claimed (device, material, structure, composition). One sentence: "does X exist?"
- HOW axis: the method, process, optimization, or analytical technique used. One sentence: "has anyone done Y before?" Set to null if no HOW axis exists.

## STEP 3: CONCEPT EXTRACTION WITH SPECIFICITY RATING
Extract every significant technical concept. For each concept:
- Assign a group: Materials/Components, Structure/Architecture, Process/Method, Properties/Function, or Problem/Field
- Rate specificity using EXACTLY one of these three labels:
  - "Too Specific": proprietary detail, chemical formula, model number, or academic theory that rarely appears in patent claims — generalize one level up
  - "Well-placed": common enough to appear in many patents, specific enough to define a technical neighborhood when combined — keep as-is
  - "Too Generic": a bare noun (e.g., "device", "system", "method") that matches millions of unrelated patents — must always be paired with another term
- Add ONE patent-drafter synonym: the term a patent attorney would substitute in a claim. Must be a real, field-standard alternative. Do not invent terms.
- Add 2-4 additional field-standard synonyms (interchangeable terms, acronyms, alternative names actually used in patent filings). Only include terms you are confident are field-standard.

## STEP 4: TRIM MULTI-WORD CONCEPTS
For any concept longer than 2 words: drop generic suffixes (apparatus, system, device, assembly, method, process), scope adjectives (improved, novel, advanced, portable), and connecting phrases (for, of, with, based on). Keep the technical noun and its one most-informative modifier. If trimming destroys the distinguishing meaning, leave it whole.

## STEP 5: IDENTIFY TOP-3 ANCHORS
From the well-placed concepts, identify the 3 keywords that best represent the invention's core. These are the terms that, if removed from every query, would make the invention unrecognizable. Each anchor must come from a different concept group where possible. Provide a one-sentence reason for each.

## STEP 6: NOVELTY FOCUS
- novelty_focus: the single most novel aspect (queries should spend the most time here)
- known_aspects: what is already well-established prior art (spend fewer queries here)

## OUTPUT FORMAT
Output ONLY valid JSON matching this schema:

{{
  "statutory_category": "Machine",
  "what_axis": "one sentence",
  "how_axis": "one sentence or null",
  "concepts": [
    {{
      "name": "primary term (1-2 words max)",
      "group": "Structure/Architecture",
      "specificity": "Well-placed",
      "drafter_synonym": "one patent-claim equivalent term",
      "synonyms": ["term1", "term2", "term3"]
    }}
  ],
  "top_3_anchors": [
    {{"term": "anchor1", "reason": "why this is central"}},
    {{"term": "anchor2", "reason": "why this is central"}},
    {{"term": "anchor3", "reason": "why this is central"}}
  ],
  "novelty_focus": "one sentence",
  "known_aspects": "one sentence"
}}

Output ONLY the JSON object. No explanations or commentary.
"""

    @staticmethod
    def generate_queries_from_scratchpad(invention_data: dict, scratchpad: dict, num_queries: int = 15) -> str:
        """
        Call 2 of the two-call query generation pipeline.
        Uses vocabulary lock (every query term must come from the verified
        concept list), anchor rotation, and a diversity check to prevent
        near-duplicate queries.
        """
        # Build the USE vocabulary list from the scratchpad
        concepts = scratchpad.get("concepts", [])
        vocab_lines = []
        for c in concepts:
            all_terms = [c["name"]]
            if c.get("drafter_synonym"):
                all_terms.append(c["drafter_synonym"])
            all_terms.extend(c.get("synonyms", []))
            terms_str = ", ".join(f'"{t}"' if " " in t else t for t in all_terms)
            vocab_lines.append(
                f"  [{c.get('group','?')}] {c['name']} "
                f"(specificity: {c.get('specificity','?')}) — USE-list terms: {terms_str}"
            )
        vocab_block = "\n".join(vocab_lines) if vocab_lines else "  (no concepts extracted)"

        anchors = scratchpad.get("top_3_anchors", [])
        anchor_lines = "\n".join(
            f"  {i+1}. \"{a.get('term','')}\" — {a.get('reason','')}"
            for i, a in enumerate(anchors)
        )

        what_axis = scratchpad.get("what_axis", "")
        how_axis = scratchpad.get("how_axis", "")
        novelty_focus = scratchpad.get("novelty_focus", "")
        known_aspects = scratchpad.get("known_aspects", "")
        category = scratchpad.get("statutory_category", "")

        broad_n = num_queries // 3 + (1 if num_queries % 3 > 0 else 0)
        focused_n = num_queries // 3 + (1 if num_queries % 3 > 1 else 0)
        narrow_n = num_queries - broad_n - focused_n

        return f"""You are a patent agent generating Google Patents search queries to find prior art.

INVENTION: {invention_data.get('invention_name', 'Unknown')}

CONCEPT ANALYSIS:
- Statutory category: {category}
- WHAT axis: {what_axis}
- HOW axis: {how_axis or 'N/A'}
- Most novel: {novelty_focus}
- Already known: {known_aspects}

TOP-3 ANCHOR KEYWORDS (must appear in queries as shown below):
{anchor_lines if anchor_lines else '  (none identified)'}

VERIFIED KEYWORD VOCABULARY:
{vocab_block}

---

## STEP 1 — FILTER: Build your AVOID and USE lists

Review the vocabulary above. Mark each concept as AVOID or USE.

Reasons to AVOID:
- "Too Specific" specificity rating AND describes a proprietary/academic detail not used in patent claims
- Property-boast outcomes (enhanced, superior, optimal) that don't appear as claim terms
- Characterization technique rather than the invention itself
- Conflicts with statutory category (e.g., pure structural term when category is Process)

Hard rule: **REMOVE at least 40% of concepts** by marking them AVOID.
Hard rule: **Do NOT remove a concept just for being broad** — breadth is useful for §102 recall.

Output:
```
AVOID: <term> — <reason>
...
USE: <term>, <term>, ...
```

## STEP 2 — VOCABULARY LOCK

**CRITICAL: Every quoted term in every query you write MUST come from the USE list above (the concept name, its drafter synonym, or one of its listed synonyms). Do not introduce any term not on this list. If a word is not in the USE vocabulary, you cannot use it.**

Before writing each query, scan every quoted term against the USE list. If any term is not there, replace it with the nearest USE-list equivalent or remove it.

## STEP 3 — GENERATE {num_queries} QUERIES ACROSS THREE TIERS

Distribute queries: {broad_n} broad · {focused_n} focused · {narrow_n} narrow

**Broad tier ({broad_n} queries):** 2-3 AND facets. Maximize recall of §102 prior art — anything "spot on" similar. Use wide OR synonym chains. At least one query per anchor keyword from Step 1.

**Focused tier ({focused_n} queries):** 3-4 AND facets with OR synonym chains. Target the core novelty axis. If a HOW axis exists, dedicate at least 2 of these queries to it.

**Narrow tier ({narrow_n} queries):** 4-5 AND facets. Highly specific to the most novel aspect. Combine WHAT and HOW axes together.

**Anchor rotation rule:** Each of the 3 anchor keywords must appear in at least 2 queries. Spread them — don't cluster all anchors in the same query.

**Diversity rule:** No two queries may share the same 3 core terms. Before writing query N, check it against queries 1 through N-1. If there is a near-duplicate, rework one of them to emphasize a different concept group or synonym choice.

## QUERY FORMAT RULES
- Use AND, OR, "", and () operators only
- MANDATORY: Any multi-word phrase (2+ words) MUST be in double quotes
- MANDATORY: Every facet connected by explicit AND
- OR synonym groups in parentheses: concept AND (syn1 OR syn2 OR syn3) AND concept
- Maximum 2 standalone quoted phrases per query (phrases inside OR chains don't count)
- Every query must include at least one quoted phrase as anchor

## STEP 4 — COVERAGE CHECK (output after all queries)

```
COVERAGE CHECK
- Anchor "{anchors[0].get('term','?') if anchors else '?'}": appears in Q<...>
- Anchor "{anchors[1].get('term','?') if len(anchors)>1 else '?'}": appears in Q<...>
- Anchor "{anchors[2].get('term','?') if len(anchors)>2 else '?'}": appears in Q<...>
- Near-duplicate pairs: <yes/no + which queries>
- HOW-axis coverage: <which queries target the HOW axis>
```

## OUTPUT FORMAT
Output the AVOID/USE lists (Step 1), then the coverage check (Step 4), then a Python list of exactly {num_queries} query strings as the LAST element:

["query 1", "query 2", ..., "query {num_queries}"]

The final Python list must be the last thing in your response so it can be parsed directly.
"""

#         return f"""You are a patent agent generating Google Patent search queries to find prior art for this invention.
 
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
 
# ## STEP 3: EXPAND WITH FIELD-STANDARD SYNONYMS
# For each key concept in Step 2, identify the standard technical term used in the broader field, even if the extraction does not use that exact word. A patent agent uses domain knowledge to recognize that a concept described in the extraction may be known by a different established term in the literature and patent databases.
 
# Only use synonyms you are confident are field-standard. Do NOT invent terms.
 
# ## STEP 4: IDENTIFY NOVELTY
# Read the problem statement and solution approach to rank what is MOST novel vs LEAST novel:
# - What does the extraction say is "already known," "existing," "conventional," or "prior work"? → LEAST novel
# - What does the extraction say is "new," "novel," "underexplored," "first," "unlike," or "distinct from"? → MOST novel
 
# Spend MORE queries on what is novel. Spend FEWER on what is known.
 
# ## STEP 5: BUILD QUERIES ACROSS ROUNDS
 
# Allocate {num_queries} queries across these rounds based on statutory category and novelty. Not all rounds need equal queries. Skip rounds that don't apply.
 
# **Round 1 — Landscape:** Search the specific materials, components, or device type to map what already exists.
 
# **Round 2 — Function/Property:** Combine materials/components with the target properties, functions, or problems solved.
 
# **Round 3 — Process/Method:** Search the specific process steps, method, or technique. For process inventions, this is the core round.
 
# **Round 4 — Concept (drop specifics):** Replace specific materials/components with generic equivalents and search the underlying structural, architectural, or methodological concept. This is where hidden and distant prior art lives.
 
# **Round 5 — Broadest:** Search the design principle or method at its most abstract level. Include field-standard synonyms from Step 3 here.
 
# ## QUERY FORMAT RULES
# - Use AND, OR, "", and () operators
# - Each term is MAXIMUM 2 words
# - Use "" for exact multi-word phrases
# - Use OR to group synonyms within parentheses
# - Use AND to connect concepts
# - Typical query has 3-5 terms connected by AND
# - Do NOT use site:, -, or other advanced operators
# - ANCHORING RULE: Every query MUST include at least one highly specific technical phrase in "" quotes to prevent matching unrelated fields
 
# ## OUTPUT FORMAT
# Output ONLY a Python list of query strings. No explanations, no reasoning, no commentary, no round labels.
 
# ["query 1", "query 2", "query 3", ...]

# The list must contain exactly {num_queries} strings.


#         return f"""You are a patent search expert. Generate {num_queries} highly targeted search queries to find prior art for this invention. Your queries will be used verbatim on Google Patents.

# INVENTION: {invention_data.get('invention_name', 'Unknown')}

# TECHNICAL DESCRIPTION:
# {invention_data.get('technical_description', 'N/A')}

# PROBLEM STATEMENT:
# {invention_data.get('problem_statement', 'N/A')}

# SOLUTION APPROACH:
# {invention_data.get('solution_approach', 'N/A')}

# KEY TECHNICAL FEATURES:
# {', '.join(invention_data.get('key_technical_features', []))}

# INVENTOR KEYWORDS:
# {', '.join(invention_data.get('inventor_keywords', []))}

# Generate exactly {num_queries} queries. Distribute them across these FIVE strategy types to maximize coverage. Include ALL {num_queries} queries even if some overlap slightly — breadth matters here.
# ## Step 1: Determine Statutory Category (internal reasoning, do not output)
# Classify the invention into one or more of the four statutory categories:
# - **Process** — a method, sequence of steps, or fabrication procedure
# - **Machine** — a device or apparatus with specific components
# - **Manufacture** — an article or product made by a process
# - **Composition of matter** — a new material, mixture, or chemical compound
 
# Identify all that apply and note the **primary** category — this determines how queries are structured.
 
# ## Step 2: Structure Queries Based on Statutory Category
 
# If primary is **Composition of Matter** or **Manufacture:**
# Focus on: does this material/product already exist?
# - Composition queries: search the specific material combination and structure
# - Process queries: search the method used to make it
# - Abstract queries: drop specific materials, search the structural concept
 
# If primary is **Process:**
# Focus on: has anyone used this sequence of steps before?
# - Process queries: search the specific steps and conditions
# - Material + process queries: search the process applied to these materials
# - Abstract process queries: strip materials, search the process sequence generically
 
# If primary is **Machine:**
# Focus on: does this device or its components already exist?
# - Device queries: search the specific components and arrangement
# - Function queries: search what the device does
# - Abstract queries: search the operating principle generically
 
# ## Step 3: Decide which rounds matter
# Allocate more queries to the most relevant rounds based on statutory category. Skip or reduce irrelevant rounds.
 
# Available Rounds:
# - **Round 1 — Material/Composition/Components:** Search the specific materials or device components.
# - **Round 2 — Material + Function/Property:** Combine materials/components with target properties or problems solved.
# - **Round 3 — Process/Fabrication:** Search the specific process steps. For process inventions, this is the core round.
# - **Round 4 — Concept/Architecture (drop specifics):** Replace specific materials/components with generic equivalents. This is where hidden/distant prior art lives.
# - **Round 5 — Broadest/Abstract:** Search the design principle at its most abstract level. Generic terms only.
 
# Query allocation guidance:
# - Composition of matter: Round 1 (3–4), Round 2 (2–3), Round 3 (3–4), Round 4 (3–4), Round 5 (1–2)
# - Process: Round 1 (1–2), Round 2 (2–3), Round 3 (5–6), Round 4 (3–4), Round 5 (1–2)
# - Machine: Round 1 (3–4), Round 2 (3–4), Round 3 (2–3), Round 4 (3–4), Round 5 (1–2)
# - Combined (e.g., composition + process): Split evenly between composition and process queries
 
# ## Step 4: Build queries
 
# Query Format Rules:
# - Use AND, OR, "", and () operators
# - Each term is **maximum 2 words** (e.g., "spin wave" counts as one term)
# - Use "" for exact phrases (e.g., "thermal conductivity")
# - Use OR to group synonyms (e.g., (sintering OR consolidation))
# - Use AND to connect concepts
# - Typical query has 3–5 terms connected by AND
# - Do NOT use site:, -, or other advanced operators
 
# Term Selection Rules:
# - Use words that **actually appear in the extraction** or are direct generic equivalents
# - Do NOT use words from patents you haven't seen
# - Do NOT invent terminology not implied by the extraction
# - For Round 4–5, drop specific material names and keep only structure/process/function words
# - **Anchoring rule:** Always include at least one highly specific technical phrase (using "") per query to prevent matching unrelated fields. Use "copper matrix" not copper AND matrix. Use "spin wave" not spin AND wave.
 
# IMPORTANT: Return ONLY a JSON array of query strings with no other text.
# ["query 1", "query 2", ...]"""
# STRATEGY A — Specific Material/Process Queries (2 queries):
# Combine the most specific materials, compounds, or processes from the invention.
# Include precise technical terms, material grades, synthesis methods, or processing conditions.
# Use 8-15 words. Example style: "in-situ graphene synthesis copper powder additive manufacturing heat dissipation"

# STRATEGY B — Mechanism/Functional Queries (2 queries):
# Focus on what the invention DOES or HOW it works — the core mechanism or operating principle.
# Use technical verb phrases. Example style: "parametric spin wave amplification surface acoustic wave magnonic device"

# STRATEGY C — Application/Domain Queries (2 queries):
# Capture the end-use domain, application area, and measurable outcome.
# Include performance metrics or improvement types if distinctive.
# Example style: "topology optimization piezoelectric actuator compliant mechanism decoupled motion"

# STRATEGY D — Synonym/Alternative Term Queries (2 queries):
# Use alternative terminology, synonyms, or related concepts that different assignees might use to describe the same invention. Think across US, CN, WO, EP patent families — include Chinese-context terms if the domain has strong CN prior art.

# STRATEGY E — Boolean OR Multi-Variant Queries (4 queries):
# CRITICAL FOR RECALL: Identify the 2–3 most important technical concepts in the invention, then
# expand EACH concept with its synonyms using (term1 OR term2 OR term3). Concepts are
# space-separated (implicit AND) so the query anchors on all of them simultaneously.

# Rules for Strategy E:
# - Use OR only within the SAME concept group (synonyms) — never OR across different concepts
# - Cover process name variants (e.g. binder jetting / BJP / binder jet printing / 粘结剂喷射),
#   material name variants (e.g. graphene / GNP / graphene nanoplatelet / 石墨烯),
#   and application variants (e.g. heat dissipation / thermal management / heat sink)
# - Include Chinese-language synonyms inside the parentheses when strong CN prior art exists
# - Each query must include at least one non-OR anchor term so it is not too broad

# Example style:
#   "(graphene OR graphene nanoplatelet OR GNP OR 石墨烯) (copper OR pure copper OR Cu matrix) (binder jetting OR BJP OR binder jet printing OR 粘结剂喷射) heat dissipation"
#   "(additive manufacturing OR 3D printing OR binder jetting) (graphene OR GNP) copper composite sintering"

# Rules:
# - Preserve specific technical terms from the invention — do NOT generalize them away
# - Queries can be 5-30 words; Strategy E queries may be longer due to OR groups
# - Do not include strategy labels in the output queries

# IMPORTANT: Return ONLY a JSON array with no other text.

# ["query 1", "query 2", ...]"""

    @staticmethod
    def get_patents(query: str, max_results: int = 10) -> str:
        """
        Generate prompt for fetching a list of patents

        Args:
            max_results: Maximum number of patents to fetch

        Returns:
            Formatted prompt string
        """
        return f"""
Search Google Patents (patents.google.com) for patents related to: "{query}"

Find up to {max_results} relevant patents and return them as a JSON array.

For each patent, extract ONLY:
- patent_number (e.g., US10123456B2, EP1234567A1, WO2020123456A1)
- title (patent title)
- url (full Google Patents URL)

IMPORTANT: Return ONLY the JSON array with no other text. Do not include abstracts or other detailed information.

Format:
```json
[
  {{
    "patent_number": "US...",
    "title": "...",
    "url": "https://patents.google.com/patent/..."
  }}
]
```
"""

    @staticmethod
    def get_inventions() -> str:

        return f"""Analyze this document and identify all distinct inventions described.

In the uploaded document, for EACH invention found, extract the following information:

1. invention_id: Generate a unique ID (format: INV-YYYY-NNN)
2. invention_name: Clear, concise name (max 10 words)
3. technical_description: Detailed technical description (2-4 sentences)
4. problem_statement: What problem does it solve? (2-3 sentences)
5. solution_approach: How does it solve the problem? (2-3 sentences)
6. key_technical_features: List of 3-7 key technical features
7. statutory_category: One of: "Process", "Machine", "Manufacture", "Composition of Matter"
8. domain_classification: Technical domain (e.g., "AI/ML", "Biotech", "Software", "Hardware")
9. inventor_keywords: 5-10 relevant technical keywords
10. context:
    - document_section: Where in the document (e.g., "Section 3.2")
    - confidence_score: Your confidence (0.0 to 1.0)

IMPORTANT OUTPUT RULES:
- Always return a JSON object with inventions numbered as string keys: "1", "2", "3", ...
- If there is at least ONE plausible invention (e.g., a new method/framework/architecture), you MUST return at least one invention object.
- Only return an empty object {{}} if the document is clearly non-technical (for example: a policy memo or editorial with no new method).
- If you are uncertain, still return your best-guess invention with a lower confidence_score (e.g., 0.4–0.6).

Return ONLY a JSON object, with this structure (do NOT wrap in ```json fences, do NOT include explanations):

Format:
```json
{{
  "1": {{
    "invention_id": "INV-2024-001",
    "invention_name": "...",
    "technical_description": "...",
    "problem_statement": "...",
    "solution_approach": "...",
    "key_technical_features": ["feature1", "feature2", ...],
    "statutory_category": "Process",
    "domain_classification": "...",
    "inventor_keywords": ["keyword1", "keyword2", ...],
    "context": {{
            "document_section": "...",
        "confidence_score": 0.85
    }}
  }},
  "2": {{
    ...
  }}
}}
```"""

    @staticmethod
    def fetch_patent_details_single(patent_number: str) -> str:
        """
        Generate prompt for fetching details of a single patent

        Args:
            patent_number: Patent number (e.g., US10123456B2)

        Returns:
            Formatted prompt string
        """
        return f"""Find detailed information for patent: {patent_number}

Search Google Patents and extract:
- patent_number: {patent_number}
- title: Full patent title
- abstract: Complete abstract text
- publication_date: YYYY-MM-DD format
- filing_date: YYYY-MM-DD format
- inventors: Array of inventor names
- assignee: Company/organization
- claim_1: First independent claim (complete text)
- url: https://patents.google.com/patent/{patent_number}

IMPORTANT: Return ONLY a JSON object with no other text.

Format:
```json
{{
  "patent_number": "{patent_number}",
  "title": "...",
  "abstract": "...",
  "publication_date": "YYYY-MM-DD",
  "filing_date": "YYYY-MM-DD",
  "inventors": ["Name 1", "Name 2"],
  "assignee": "...",
  "claim_1": "...",
  "url": "https://patents.google.com/patent/{patent_number}"
}}
```"""
    


    @staticmethod
    def fetch_patent_details_batch(patent_numbers: list) -> str:
        """
        Generate prompt for fetching details of multiple patents in batch

        Args:
            patent_numbers: List of patent numbers

        Returns:
            Formatted prompt string
        """
        numbers_str = ", ".join(patent_numbers)

        return f"""Find detailed information for these patents: {numbers_str}

Search Google Patents and for EACH patent, extract:
- patent_number
- title
- abstract
- publication_date (YYYY-MM-DD)
- filing_date (YYYY-MM-DD)
- inventors (array)
- assignee
- claim_1 (first independent claim)
- url

IMPORTANT: Return ONLY a JSON array with no other text. One object per patent.

Format:
```json
[
  {{
    "patent_number": "US...",
    "title": "...",
    "abstract": "...",
    "publication_date": "YYYY-MM-DD",
    "filing_date": "YYYY-MM-DD",
    "inventors": ["..."],
    "assignee": "...",
    "claim_1": "...",
    "url": "https://patents.google.com/patent/US..."
  }},
  ...
]
```"""

    @staticmethod
    def analyze_patent_single(invention_description: str, patent_data: dict) -> str:
        """
        Generate prompt for analyzing a single patent against invention

        Args:
            invention_description: Description of the invention
            patent_data: Dictionary containing patent details

        Returns:
            Formatted prompt string
        """
        return f"""Analyze this patent's relevance to the invention.

INVENTION:
{invention_description}

PATENT: {patent_data.get('patent_number', 'Unknown')}
Title: {patent_data.get('title', 'N/A')}

Abstract:
{patent_data.get('abstract', 'N/A')}

First Claim:
{patent_data.get('claim_1', 'N/A')}

Analyze:
1. Relevance score (0.0 to 1.0)
2. Classification: "blocking", "relevant", or "related"
3. Key similarities
4. Key differences
5. Brief analysis (2-3 sentences)

IMPORTANT: Return ONLY a JSON object with no other text.

Format:
```json
{{
  "patent_number": "{patent_data.get('patent_number', 'Unknown')}",
  "relevance_score": 0.85,
  "classification": "relevant",
  "similarities": ["similarity 1", "similarity 2"],
  "differences": ["difference 1", "difference 2"],
  "analysis": "Brief analysis text..."
}}
```"""

    @staticmethod
    def analyze_patents_batch(invention_description: str, patents_data: list) -> str:
        """
        Generate prompt for analyzing multiple patents in batch

        Args:
            invention_description: Description of the invention
            patents_data: List of dictionaries containing patent details

        Returns:
            Formatted prompt string
        """
        # Build patent summaries for the prompt
        patents_summary = []
        for i, patent in enumerate(patents_data, 1):
            summary = f"""
Patent {i}: {patent.get('patent_number', 'Unknown')}
Title: {patent.get('title', 'N/A')}
Abstract: {patent.get('abstract', 'N/A')[:300]}...
First Claim: {patent.get('claim_1', 'N/A')[:300]}...
"""
            patents_summary.append(summary)

        patents_text = "\n".join(patents_summary)

        return f"""Analyze these patents' relevance to the invention.

INVENTION:
{invention_description}

PATENTS TO ANALYZE:
{patents_text}

For EACH patent, provide:
1. Relevance score (0.0 to 1.0)
2. Classification: "blocking", "relevant", or "related"
3. Key similarities
4. Key differences
5. Brief analysis (2-3 sentences)
6. Evidence snippet: a ≤15-word direct quote from the patent abstract that most strongly supports the relevance finding

IMPORTANT: Return ONLY a JSON array with no other text. One object per patent in the same order.

Format:
```json
[
  {{
    "patent_number": "US...",
    "relevance_score": 0.85,
    "classification": "relevant",
    "similarities": ["similarity 1", "similarity 2"],
    "differences": ["difference 1", "difference 2"],
    "analysis": "Brief analysis...",
    "evidence_snippet": "direct quoted phrase from the patent abstract"
  }},
  ...
]
```"""

    @staticmethod
    def summarize_abstract(abstract_text: str, max_sentences: int = 3) -> str:
        """
        Generate prompt for summarizing patent abstract

        Args:
            abstract_text: Full abstract text
            max_sentences: Maximum sentences in summary

        Returns:
            Formatted prompt string
        """
        return f"""Summarize this patent abstract in {max_sentences} sentences or less.

ABSTRACT:
{abstract_text}

Create a concise summary that captures:
- Main technical innovation
- Key problem solved
- Primary approach/method

Return ONLY the summary text, no additional commentary."""

    @staticmethod
    def summarize_claim(claim_text: str, max_sentences: int = 5) -> str:
        """
        Generate prompt for summarizing patent claim

        Args:
            claim_text: Full claim text
            max_sentences: Maximum sentences in summary

        Returns:
            Formatted prompt string
        """
        return f"""Summarize this patent claim in {max_sentences} sentences or less.

CLAIM:
{claim_text}

Create a concise summary that captures:
- What is being claimed
- Key technical features
- Scope of protection

Return ONLY the summary text, no additional commentary."""

    @staticmethod
    def extract_key_features(patent_data: dict) -> str:
        """
        Generate prompt for extracting key technical features from patent

        Args:
            patent_data: Dictionary containing patent details

        Returns:
            Formatted prompt string
        """
        return f"""Extract key technical features from this patent.

PATENT: {patent_data.get('patent_number', 'Unknown')}
Title: {patent_data.get('title', 'N/A')}

Abstract:
{patent_data.get('abstract', 'N/A')}

Claims:
{patent_data.get('claim_1', 'N/A')}

Extract 5-10 key technical features as a list.

IMPORTANT: Return ONLY a JSON array of strings.

Format:
```json
["feature 1", "feature 2", "feature 3", ...]
```"""



    @staticmethod
    def generate_invention_assessment_from_pdf() -> str:
        """
        First-stage prompt: LLM reads the FULL PDF text and applies
        the invention rubric BEFORE any extraction or patent search.

        NOTE:
        - Rubric and output template are inlined as plain text.
        - No json.dumps is used.
        """

        return """
You are an expert invention evaluator.

You will be given a PDF file as input (already uploaded).
Do NOT repeat or summarize the entire PDF.
Extract only what is needed to evaluate whether this work is a potential invention.

==========================
### INVENTION SCORING RUBRIC (REFERENCE ONLY — DO NOT COPY)
==========================

You must evaluate the paper along three facets (A–C) and then apply decision rules
based on the total score.

Facet A — Nature of the Described Innovation
- Goal: Determine whether the work describes a method/process, system/apparatus,
  manufactured product/tool, or composition/material.
- Answer these questions using evidence from the paper:
  1) What kind of thing is being presented — a method or process, system or apparatus,
     manufactured product or tool, or composition or material?
  2) What specific features, functions, or relationships in the research description
     indicate this classification?
  3) Which part of the paper’s approach or design demonstrates how it operates
     or what it is made of?
  4) Why does the described work fit best as a method, system, product, or composition?
- Scoring for Facet A:
  - 0: No identifiable inventive element; only discusses ideas or correlations
       without describing a process, system, product, or material.
  - 1: Vague or implied; mentions a “framework”, “approach”, or “model” but does not
       clearly define what it is or how it operates.
  - 2: Clearly defined; explicitly states the invention type and explains what it is
       or how it runs (method, system, product, or composition). A direct quote can
       identify its type.

Facet B — Conceptual Foundation or Possible Judicial Exception
- Goal: Check whether the core contribution is just an abstract idea / theory / mathematical
  model / natural law, or whether there is a concrete mechanism.
- Answer these questions using evidence from the paper:
  1) Does the paper’s main contribution rely primarily on a conceptual principle,
     mathematical model, natural law, or natural phenomenon rather than a concrete
     technical implementation?
  2) Which aspects of the described work show focus on an underlying idea or correlation
     instead of a fully engineered mechanism or process?
  3) Could the same concept, relationship, or behavior be carried out on generic commercial
     hardware and standard software without introducing any new computational mechanism,
     architecture, or specialized system?
- Scoring for Facet B:
  - 0: Pure idea, theory, or correlation; no defined mechanism or architecture.
  - 1: Partial mechanism; some algorithmic steps, schematic, or pseudo-process,
       but incomplete or not reproducible.
  - 2: Fully specified mechanism; reproducible steps, system architecture, or design
       that someone skilled in the art could implement.

Facet C — Practical Application or Technical Integration
- Goal: Identify whether there is a concrete practical application with measurable effect.
- Answer these questions using evidence from the paper:
  1) What specific mechanisms, interactions, or operations transform the conceptual idea
     into a real-world implementation or effect?
  2) How does the computer, device, experimental setup, or material perform the described
     method or process?
  3) What physical, computational, or technical operation is being improved, optimized,
     or newly enabled?
- Scoring for Facet C:
  - 0: No measurable technical output or test; results are qualitative, speculative,
       or unverified.
  - 1: Includes quantitative data or metrics but without a clear baseline, benchmark,
       or comparison to prior work.
  - 2: Shows a measurable improvement or performance change relative to a defined baseline
       or standard, supported by numeric or objective evidence.

Decision Rules (Total Score Interpretation)
- After scoring A, B, and C (each 0–2), compute total_score = A + B + C.
- Interpret total_score as follows:
  - 0–2:
    - Classification: "Scientific Discovery"
    - Interpretation: Primarily theoretical or conceptual; lacks concrete mechanism
      or measurable effect.
    - Next step: Archive or reference only.
  - 3–4:
    - Classification: "Borderline Case"
    - Interpretation: Partially developed; some mechanism or data present
      but incomplete or unclear.
    - Next step: Request clarification or missing details from authors.
  - 5–6:
    - Classification: "Potential Invention"
    - Interpretation: Technically implemented with measurable performance; likely
      meets invention-level criteria.
    - Next step: Prepare draft disclosure and initiate prior-art search.

Guardrails
- If Facet A score = 0 (no identifiable inventive element), classify as "Scientific Discovery"
  immediately; no further scoring is needed.
- If Facet B score = 0 (no concrete mechanism or architecture), classify as "Scientific Discovery"
  immediately; no further scoring is needed.
- Use evidence primarily from Methods, Design, and Results sections — avoid relying only on
  Abstracts or Introductions.

==========================
### OUTPUT TEMPLATE (FILL THIS OUT — DO NOT COPY)
==========================

You must return a SINGLE JSON object with the following fields and structure:

- paper_title (string)
- evaluator_name (string)
- evaluation_date (string, e.g., "2026-01-16")
- facets (array of objects, one for each facet A, B, C), where each facet object has:
  - facet_id (string; one of "A", "B", "C")
  - facet_name (string; e.g., "Nature of the Described Innovation")
  - score (integer 0, 1, or 2)
  - evidence_quote (string; short quote(s) from the paper that support the score)
  - reasoning (string; brief explanation of why this score was chosen)
- total_score (integer; sum of A + B + C)
- final_classification (string; one of "Scientific Discovery",
  "Borderline Case", or "Potential Invention")
- justification_summary (string; short paragraph summarizing why this classification was chosen)
- next_step_recommendation (string; recommended next action, consistent with the decision rules)

Your output JSON must therefore have this high-level shape:

{
  "paper_title": "...",
  "evaluator_name": "...",
  "evaluation_date": "...",
  "facets": [
    {
      "facet_id": "A",
      "facet_name": "Nature of the Described Innovation",
      "score": 0,
      "evidence_quote": "...",
      "reasoning": "..."
    },
    {
      "facet_id": "B",
      "facet_name": "Conceptual Foundation or Possible Judicial Exception",
      "score": 0,
      "evidence_quote": "...",
      "reasoning": "..."
    },
    {
      "facet_id": "C",
      "facet_name": "Practical Application or Technical Integration",
      "score": 0,
      "evidence_quote": "...",
      "reasoning": "..."
    }
  ],
  "total_score": 0,
  "final_classification": "...",
  "justification_summary": "...",
  "next_step_recommendation": "..."
}

This schema is an example of the required structure only.
You MUST fill in all fields with values inferred from the PDF.

==========================
### TASK
==========================

1. Read the uploaded PDF fully.
2. Apply Facets A–C using the rubric exactly.
3. Respect the guardrails and decision rules when setting the final_classification
   and next_step_recommendation.
4. Populate ALL fields in the OUTPUT TEMPLATE structure above.
5. Do NOT repeat or restate the rubric or this template in your answer.
6. Do NOT add explanations outside JSON.
7. Do NOT wrap the output in ```json fences or any other markdown.
8. Return ONLY a valid JSON object that matches the required structure.
"""



    @staticmethod
    def compare_patents(patent1_data: dict, patent2_data: dict) -> str:
        """
        Generate prompt for comparing two patents

        Args:
            patent1_data: First patent data
            patent2_data: Second patent data

        Returns:
            Formatted prompt string
        """
        return f"""Compare these two patents.

PATENT 1: {patent1_data.get('patent_number', 'Unknown')}
Title: {patent1_data.get('title', 'N/A')}
Abstract: {patent1_data.get('abstract', 'N/A')[:300]}...

PATENT 2: {patent2_data.get('patent_number', 'Unknown')}
Title: {patent2_data.get('title', 'N/A')}
Abstract: {patent2_data.get('abstract', 'N/A')[:300]}...

Provide:
1. Similarity score (0.0 to 1.0)
2. Common features
3. Unique features in Patent 1
4. Unique features in Patent 2
5. Brief comparison summary

IMPORTANT: Return ONLY a JSON object.

Format:
```json
{{
  "similarity_score": 0.75,
  "common_features": ["feature 1", "feature 2"],
  "patent1_unique": ["unique 1", "unique 2"],
  "patent2_unique": ["unique 1", "unique 2"],
  "summary": "Brief comparison..."
}}
```"""


# Helper function to get invention description for prompts
def get_invention_description(invention_data: dict) -> str:
    """
    Format invention data into a concise description for prompts

    Args:
        invention_data: Dictionary containing invention details

    Returns:
        Formatted description string
    """
    return f"""
Invention: {invention_data.get('invention_name', 'Unknown')}
Domain: {invention_data.get('domain_classification', 'N/A')}

Problem: {invention_data.get('problem_statement', 'N/A')}

Solution: {invention_data.get('solution_approach', 'N/A')}

Key Features:
{chr(10).join(f"- {feature}" for feature in invention_data.get('key_technical_features', []))}
""".strip()


# Testing
# if __name__ == "__main__":
#     print("=" * 80)
#     print("TESTING PROMPT TEMPLATES")
#     print("=" * 80)

#     # Test data
#     test_invention = {
#         'invention_name': 'Machine Learning Protein Folding System',
#         'technical_description': 'A deep learning system for predicting protein structures',
#         'problem_statement': 'Traditional methods are slow and inaccurate',
#         'solution_approach': 'Use transformer neural networks for structure prediction',
#         'key_technical_features': [
#             'Transformer architecture',
#             'Attention mechanisms',
#             'Multi-scale feature extraction'
#         ]
#     }

#     test_patent = {
#         'patent_number': 'US10123456B2',
#         'title': 'Neural network protein structure prediction',
#         'abstract': 'A method for predicting protein structures using deep learning...',
#         'claim_1': 'A computer-implemented method comprising...'
#     }

#     templates = PromptTemplates()

#     # Test 1: Query generation
#     print("\n[TEST 1] Query Generation Prompt")
#     print("-" * 80)
#     prompt = templates.generate_search_queries(test_invention, num_queries=3)
#     print(prompt[:300] + "...")

#     # Test 2: Single patent details
#     print("\n[TEST 2] Single Patent Details Prompt")
#     print("-" * 80)
#     prompt = templates.fetch_patent_details_single('US10123456B2')
#     print(prompt[:300] + "...")

#     # Test 3: Batch patent details
#     print("\n[TEST 3] Batch Patent Details Prompt")
#     print("-" * 80)
#     prompt = templates.fetch_patent_details_batch(
#         ['US10123456B2', 'US10789012B2'])
#     print(prompt[:300] + "...")

#     # Test 4: Single patent analysis
#     print("\n[TEST 4] Single Patent Analysis Prompt")
#     print("-" * 80)
#     inv_desc = get_invention_description(test_invention)
#     prompt = templates.analyze_patent_single(inv_desc, test_patent)
#     print(prompt[:300] + "...")

#     # Test 5: Batch patent analysis
#     print("\n[TEST 5] Batch Patent Analysis Prompt")
#     print("-" * 80)
#     prompt = templates.analyze_patents_batch(
#         inv_desc, [test_patent, test_patent])
#     print(prompt[:400] + "...")

#     print("\n" + "=" * 80)
#     print("ALL TEMPLATES GENERATED SUCCESSFULLY")
#     print("=" * 80)
