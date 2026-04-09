"""
RAG-based Invention Extraction Agent

Uses FAISS + Titan embeddings to retrieve relevant sections per field,
then passes original section text to the LLM for extraction with cited evidence.

4 targeted queries fill out the invention JSON incrementally:
  1. invention_name, technical_description
  2. problem_statement
  3. solution_approach, key_technical_features
  4. domain_classification, statutory_category, inventor_keywords
"""

import json
import re
import os
import asyncio
import numpy as np
import faiss
import time
from datetime import datetime
from summarization import embed_text_titan
from tools.schema_validator import validate_schema
from tools.patentability_classifier_v2 import load_config as load_patentability_config, build_patentability_prompt, validate_classification
from tools.judgeBot import run_judge, _load_config as load_judge_config
from utils.rate_limiter import BedrockRateLimiter, CircuitBreaker, invoke_bedrock_with_retry


# 4 targeted RAG queries, each mapped to the fields they fill
RAG_QUERIES = [
    {
        "query": "What is the invention name and technical description, including specific process parameters, materials, dimensions, and operational details?",
        "fields": ["invention_name", "technical_description"],
        "prompt_instructions": (
            "Return this EXACT JSON structure:\n"
            "{\n"
            '  "invention_name": "concise name (max 10 words)",\n'
            '  "technical_description": "4-6 sentences describing the technical approach",\n'
            '  "citations": {\n'
            '    "invention_name": ["quote 1: [section_id]", "quote 2: [section_id]", ...],\n'
            '    "technical_description": ["quote 1: [section_id]", "quote 2: [section_id]", "quote 3: [section_id]", ...]\n'
            "  }\n"
            "}\n"
            "IMPORTANT for technical_description:\n"
            "- Include specific quantitative parameters disclosed in the document: flow rates, speeds, temperatures, voltages, dimensions, concentrations, frequencies, timing values, etc.\n"
            "- Include specific materials, grades, or compositions (e.g., 'NdFeB grade 42', 'LORD MRF-140CG', 'ZEP e-beam resist').\n"
            "- Include preparation or fabrication steps that are part of the inventive process (e.g., dilution ratios, sonication, deposition passes).\n"
            "- Include specific layer stacks, physical construction details, or device geometries where disclosed.\n"
            "- These specifics are important for patent claim support — do not omit them in favor of vague summaries.\n"
            "Include as many relevant direct quotes as possible for each field. "
            "Do NOT limit to 1 or 2 — extract every supporting quote you can find.\n"
        ),
    },
    {
        "query": "What problem or limitation in the prior art does this work specifically address?",
        "fields": ["problem_statement"],
        "prompt_instructions": (
            "Return this EXACT JSON structure:\n"
            "{\n"
            '  "problem_statement": "the problem or limitation that exists BEFORE this invention (4-5 sentences)",\n'
            '  "citations": {\n'
            '    "problem_statement": ["quote 1: [section_id]", "quote 2: [section_id]", "quote 3: [section_id]", ...]\n'
            "  }\n"
            "}\n"
            "IMPORTANT:\n"
            "- The problem_statement must describe the GAP or LIMITATION in the current state of the art — "
            "NOT what this invention does or how it works.\n"
            "- Do NOT mention the proposed solution, system, method, or framework.\n"
            "- Focus on: what is difficult, what is missing, what existing approaches fail at, "
            "and why the current state is insufficient.\n"
            "- Distinguish between problems this invention actually solves and remaining open challenges "
            "that the authors identify as future work. Only include the former.\n"
            "- Citations must be problem-stating quotes, not descriptive or background explanations. "
            "Reject any citation that merely defines a concept rather than asserting a limitation.\n"
            "Include as many relevant direct quotes as possible. "
            "Do NOT limit to 1 or 2 — extract every supporting quote you can find.\n"
        ),
    },
    {
        "query": "What is the solution approach, key technical features, differentiating mechanisms, and demonstrated results?",
        "fields": ["solution_approach", "key_technical_features"],
        "prompt_instructions": (
            "Return this EXACT JSON structure:\n"
            "{\n"
            '  "solution_approach": "how it solves the problem (4-5 sentences)",\n'
            '  "key_technical_features": ["feature1", "feature2", "feature3", "feature4", "feature5"],\n'
            '  "citations": {\n'
            '    "solution_approach": ["quote 1: [section_id]", "quote 2: [section_id]", "quote 3: [section_id]", ...],\n'
            '    "key_technical_features": ["quote 1: [section_id]", "quote 2: [section_id]", "quote 3: [section_id]", ...]\n'
            "  }\n"
            "}\n"
            "IMPORTANT for solution_approach:\n"
            "- Be technically specific: name the exact architecture, algorithms, components, and mechanisms.\n"
            "- For example, instead of 'a hierarchical control framework', say "
            "'a two-level hierarchical policy separating base locomotion from arm control'.\n"
            "- Clearly distinguish what has been experimentally demonstrated from what is "
            "expected, proposed, or left as future work. Use language like 'demonstrated X' vs 'the authors expect Y'.\n"
            "- Do NOT repeat the technical_description — solution_approach should focus on "
            "HOW the invention solves the specific problem identified, not re-describe the system.\n"
            "- If the invention includes both a basic/initial algorithm and an optimized version, "
            "describe the full evolution (e.g., 'a two-condition peak-detection check, later replaced by a DFT-based approach').\n"
            "\n"
            "IMPORTANT for key_technical_features:\n"
            "- Each feature should be a concrete, specific, patent-relevant claim element — not vague descriptions.\n"
            "- Include specific quantitative operational parameters as distinct features "
            "(e.g., 'sheath-to-carrier gas flow ratio of 5:1 at working distance of 4-6 mm').\n"
            "- Include differentiating mechanisms that distinguish this invention from prior art "
            "(e.g., 'post-deposition plasma treatment without ink flow for conductivity enhancement').\n"
            "- Include key design principles or architectural decisions disclosed "
            "(e.g., 'default NLOS classification: any signal not meeting LOS criteria is classified as NLOS').\n"
            "- Include demonstrated applications or use cases with concrete results.\n"
            "- Include analytical or mathematical models disclosed (e.g., 'Bingham plastic model with Couette flow approximation').\n"
            "- Include known limitations or performance boundaries if disclosed — these are relevant for claim scoping.\n"
            "Aim for 6-8 features. Include as many relevant direct quotes as possible for each field. "
            "Do NOT limit to 1 or 2 — extract every supporting quote you can find.\n"
        ),
    },
    {
        "query": "What domain, patent statutory category, and technical keywords describe this invention?",
        "fields": ["domain_classification", "statutory_category", "inventor_keywords"],
        "prompt_instructions": (
            "Return this EXACT JSON structure:\n"
            "{\n"
            '  "domain_classification": "e.g., AI/ML, Robotics, Healthcare",\n'
            '  "statutory_category": ["Process", "Machine"],\n'
            '  "inventor_keywords": ["keyword1", "keyword2", "keyword3"],\n'
            '  "citations": {\n'
            '    "domain_classification": ["quote 1: [section_id]", "quote 2: [section_id]", ...],\n'
            '    "statutory_category": ["quote 1: [section_id]", "quote 2: [section_id]", ...],\n'
            '    "inventor_keywords": ["quote 1: [section_id]", "quote 2: [section_id]", ...]\n'
            "  }\n"
            "}\n"
            "IMPORTANT for statutory_category:\n"
            "- statutory_category must be a JSON array listing ALL applicable categories from: "
            "Process, Machine, Manufacture, Composition of Matter.\n"
            "- Consider each independently: a fabrication method → Process; the resulting device → Machine or Manufacture; "
            "a new material or compound → Composition of Matter. Many inventions qualify under multiple categories.\n"
            "- Do not default to a single category — if both a method and an apparatus are disclosed, include both.\n"
            "\n"
            "IMPORTANT for inventor_keywords:\n"
            "- Include specific algorithm names, named techniques, named models, and domain-specific technical terms.\n"
            "- Include terms central to the inventive concept (e.g., 'Walsh-Hadamard codes', 'Couette flow', "
            "'DFT-based LOS/NLOS classification', 'heterogeneous integration').\n"
            "- Aim for 8-12 keywords covering both broad domain terms and specific technical identifiers.\n"
            "Include as many relevant direct quotes as possible for each field. "
            "Do NOT limit to 1 or 2 — extract every supporting quote you can find.\n"
        ),
    },
]


class InventionExtractionAgentRAG:
    """
    RAG-based invention extraction agent.

    Instead of feeding the full document to the LLM, it:
    1. Embeds targeted queries with Titan
    2. Searches FAISS for relevant sections
    3. Passes original section text to the LLM
    4. Merges partial results into a complete invention JSON
    """

    CONFIDENCE_THRESHOLD = 0.85

    def __init__(self, bedrock_client, model_id, sections,
                 k=3, max_iterations=3, confidence_threshold=None,
                 patentability_mode="unified",
                 rate_limiter=None, circuit_breaker=None, log_dir="logs"):
        self.bedrock = bedrock_client
        self.model_id = model_id
        self.sections = sections
        self.k = k
        self.max_iterations = max_iterations
        if confidence_threshold is not None:
            self.CONFIDENCE_THRESHOLD = confidence_threshold
        self.patentability_mode = patentability_mode  # "unified" or "per_facet"
        self.rate_limiter = rate_limiter or BedrockRateLimiter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.log_dir = log_dir
        self.logs = []
        self.index = None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, entry_type, content):
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "type": entry_type,
            "content": content,
        })

    def save_logs(self, filename=None):
        os.makedirs(self.log_dir, exist_ok=True)
        if not filename:
            filename = f"rag_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.log_dir, filename)
        with open(filepath, "w") as f:
            json.dump(self.logs, f, indent=2)
        return filepath

    # ------------------------------------------------------------------
    # FAISS index
    # ------------------------------------------------------------------

    # Summaries that indicate non-inventive boilerplate sections
    BOILERPLATE_SUMMARIES = [
        "reference list of the paper.",
        "paper submission boilerplate.",
        "none",
    ]

    def _build_index(self):
        """Build FAISS index from sections, filtering out boilerplate."""
        all_sections = self.sections

        # Filter out boilerplate sections (references, checklists, ethics, etc.)
        self.sections = [
            s for s in all_sections
            if s.get("summary", "").strip().lower() not in self.BOILERPLATE_SUMMARIES
        ]
        skipped = len(all_sections) - len(self.sections)

        vecs = np.array([s["embedding"] for s in self.sections], dtype=np.float32)
        dim = vecs.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(vecs)

        print(f"  Loaded {len(self.sections)} sections (skipped {skipped} boilerplate), dim={dim}")
        self._log("index_loaded", {"num_sections": len(self.sections), "skipped_boilerplate": skipped, "dim": dim})

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _embed_queries(self):
        """Embed all static queries and facet descriptions into memory."""
        self._query_embeddings = {}

        for rq in RAG_QUERIES:
            q = rq["query"]
            self._query_embeddings[q] = embed_text_titan(q)

        # Embed facet descriptions for per-facet retrieval
        config = load_patentability_config()
        for fid, facet in config.get("facets", {}).items():
            facet_key = f"facet_{fid}"
            self._query_embeddings[facet_key] = embed_text_titan(facet["description"])

        print(f"  Embedded {len(self._query_embeddings)} queries")

    def _retrieve(self, query, k=None):
        """Search FAISS using cached query embedding, return matched sections."""
        k = k or self.k
        query_vec = np.array([self._query_embeddings[query]], dtype=np.float32)
        scores, indices = self.index.search(query_vec, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            section = self.sections[idx]
            results.append({
                "section_id": section["section_id"],
                "title": section.get("title", ""),
                "text": section.get("text", ""),
                "score": float(score),
            })

        self._log("retrieval", {
            "query": query,
            "results": [{"section_id": r["section_id"], "title": r["title"], "score": r["score"]} for r in results],
        })

        return results

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    SYSTEM_PROMPT = (
        "You participate in a ReAct loop. On each turn the user "
        "will ask you to EXTRACT, VALIDATE, or REFINE an invention "
        "description. Always respond with valid JSON only — no "
        "markdown fences, no extra commentary.\n"
        "When you reference evidence, quote short passages from the document.\n\n"
        "After you produce JSON, three tools run automatically:\n"
        "1. SCHEMA_VALIDATION — checks required fields and types. "
        "If errors are found, you will receive an observation and "
        "must fix ALL errors immediately.\n"
        "2. PATENTABILITY_CHECK — applies a 3-facet rubric (Nature "
        "of Innovation, Conceptual Foundation, Practical Application) "
        "to classify the extraction as Scientific Discovery, "
        "Borderline Case, or Potential Invention. If scored low, "
        "focus refinement on concrete mechanisms and measurable "
        "results from the document.\n"
        "3. JUDGE_BOT — an independent LLM (Meta Llama) scores your "
        "extraction on completeness, specificity, consistency, "
        "citation quality, and patent-readiness (each 0-2). You "
        "will see dimension scores and rationales. Use this feedback "
        "to improve weak areas during refinement."
    )

    def _call_llm(self, prompt, max_tokens=2000):
        """Call Bedrock with a single prompt."""
        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "system": [{"type": "text", "text": self.SYSTEM_PROMPT}],
            "messages": [{"role": "user", "content": prompt}],
        })

        result = invoke_bedrock_with_retry(
            self.bedrock,
            model_id=self.model_id,
            body=request_body,
            rate_limiter=self.rate_limiter,
            circuit_breaker=self.circuit_breaker,
        )

        content = result.get("content")
        if not content or not isinstance(content, list) or not content[0].get("text"):
            raise RuntimeError(f"Bedrock returned unexpected response: {result!r:.500}")
        return content[0]["text"]

    def _parse_json_response(self, response):
        """Parse JSON from LLM response."""
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        return None

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _extract_fields(self, rag_query_config):
        """Run one RAG query: retrieve sections, then extract fields via LLM."""
        query = rag_query_config["query"]
        fields = rag_query_config["fields"]
        instructions = rag_query_config["prompt_instructions"]

        print(f"\n  RAG Query: {query}")
        print(f"  Target fields: {fields}")

        # Retrieve relevant sections
        retrieved = self._retrieve(query)
        for r in retrieved:
            print(f"    [{r['section_id']}] {r['title']} (score: {r['score']:.4f})")

        # Build context from retrieved section texts
        context_parts = []
        for r in retrieved:
            context_parts.append(f"--- [{r['section_id']}] {r['title']} ---\n{r['text']}")
        context = "\n\n".join(context_parts)

        # Build extraction prompt
        prompt = (
            f"You are an expert patent/invention analyst. "
            f"Based on the following text sections, extract the requested fields.\n\n"
            f"TEXT:\n{context}\n\n"
            f"EXTRACT:\n{instructions}\n"
            f"Return a JSON object with ONLY the requested fields and a \"citations\" object.\n"
            f"Each citation must be a SHORT direct quote from the text above.\n"
            f"Include at least 3 relevant quotes per field.\n"
            f"Add the section_id of each quote at the end.\n"
            f"Include as many relevant quotes as possible per field.\n"
            f"Return JSON only, no other text."
        )

        response = self._call_llm(prompt, max_tokens=5000)
        self._log("extract_response", {"query": query, "fields": fields, "response": response[:1000]})

        parsed = self._parse_json_response(response)
        if not parsed:
            print(f"    Parse error, retrying...")
            self._log("extract_parse_error", {"query": query, "raw": response[:500]})
            retry_prompt = (
                f"{prompt}\n\n"
                f"Your previous response was not valid JSON. "
                f"Return ONLY a JSON object, no markdown, no commentary."
            )
            retry_response = self._call_llm(retry_prompt)
            self._log("extract_retry_response", {"query": query, "response": retry_response[:1000]})
            parsed = self._parse_json_response(retry_response)
            if not parsed:
                print(f"    Retry also failed for query: {query}")
                self._log("extract_retry_parse_error", {"query": query, "raw": retry_response[:500]})
                return {"parsed": {}, "retrieved": retrieved}

        print(f"    Extracted: {list(parsed.keys())}")
        return {"parsed": parsed, "retrieved": retrieved}

    # ------------------------------------------------------------------
    # Patentability check
    # ------------------------------------------------------------------

    def _build_section_context(self, sections_dict):
        """Build text context from a dict of retrieved sections."""
        parts = []
        for sid, r in sections_dict.items():
            parts.append(f"--- [{r['section_id']}] {r['title']} ---\n{r['text']}")
        return "\n\n".join(parts)

    def _build_rag_patentability_prompt(self, invention, context_text, config=None):
        """Build patentability prompt with inline section text (no cached system prompt)."""
        if config is None:
            config = load_patentability_config()

        facets = config["facets"]
        thresholds = config["classification_thresholds"]
        guardrails = config.get("guardrails", {})

        rubric_lines = []
        for fid in sorted(facets.keys()):
            facet = facets[fid]
            rubric_lines.append(f"Facet {fid} — {facet['name']}")
            rubric_lines.append(f"  Goal: {facet['description']}")
            for score, meaning in facet["scoring"].items():
                rubric_lines.append(f"  Score {score}: {meaning}")
            rubric_lines.append("")
        rubric_text = "\n".join(rubric_lines)

        guardrail_lines = []
        if guardrails.get("facet_a_zero_stops"):
            guardrail_lines.append("- If Facet A score = 0, classify as 'Scientific Discovery' immediately.")
        if guardrails.get("facet_b_zero_stops"):
            guardrail_lines.append("- If Facet B score = 0, classify as 'Scientific Discovery' immediately.")
        guardrail_lines.append("- Use evidence primarily from Methods, Design, and Results sections.")
        guardrail_text = "\n".join(guardrail_lines)

        class_lines = []
        for cls_name, bounds in thresholds.items():
            label = cls_name.replace("_", " ").title()
            class_lines.append(f"  - {bounds['min']}-{bounds['max']}: \"{label}\"")
        class_text = "\n".join(class_lines)

        clean = {k: v for k, v in invention.items() if not k.startswith("_")}

        return (
            "ACTION: CLASSIFY_PATENTABILITY\n\n"
            f"DOCUMENT SECTIONS:\n{context_text}\n\n"
            "Using the document sections above and the invention extraction "
            "below, evaluate whether this work qualifies as a patentable invention.\n\n"
            f"INVENTION EXTRACTION:\n{json.dumps(clean, indent=2)}\n\n"
            f"SCORING RUBRIC:\n{rubric_text}\n"
            f"GUARDRAILS:\n{guardrail_text}\n\n"
            f"CLASSIFICATION RULES (based on total_score = A + B + C):\n{class_text}\n\n"
            "INSTRUCTIONS:\n"
            "1. Read the document sections above carefully.\n"
            "2. Score each facet (A, B, C) with evidence quotes from the sections.\n"
            "3. Apply guardrails before computing total.\n"
            "4. Return ONLY a JSON object with this structure:\n"
            "{\n"
            '  "facets": [\n'
            '    {"facet_id": "A", "facet_name": "...", "score": 0, "evidence_quote": "...", "reasoning": "..."},\n'
            '    {"facet_id": "B", "facet_name": "...", "score": 0, "evidence_quote": "...", "reasoning": "..."},\n'
            '    {"facet_id": "C", "facet_name": "...", "score": 0, "evidence_quote": "...", "reasoning": "..."}\n'
            "  ],\n"
            '  "total_score": 0,\n'
            '  "classification": "Scientific Discovery | Borderline Case | Potential Invention",\n'
            '  "justification": "1-2 sentence summary",\n'
            '  "recommendation": "recommended next action"\n'
            "}\n\n"
            "RULES:\n"
            "- Return ONLY valid JSON, no markdown fences, no extra text.\n"
            "- Quote SHORT passages with section IDs as evidence.\n"
            "- Be objective. A score of 2 means genuinely clear, not just mentioned.\n"
        )

    def _build_facet_prompt(self, invention, context_text, facet_id, facet_config):
        """Build a prompt for scoring a single facet."""
        clean = {k: v for k, v in invention.items() if not k.startswith("_")}
        rubric = f"Facet {facet_id} — {facet_config['name']}\n"
        rubric += f"  Goal: {facet_config['description']}\n"
        for score, meaning in facet_config["scoring"].items():
            rubric += f"  Score {score}: {meaning}\n"

        return (
            f"ACTION: SCORE PATENTABILITY FACET {facet_id}\n\n"
            f"DOCUMENT SECTIONS:\n{context_text}\n\n"
            f"INVENTION EXTRACTION:\n{json.dumps(clean, indent=2)}\n\n"
            f"SCORING RUBRIC:\n{rubric}\n"
            "INSTRUCTIONS:\n"
            f"Score Facet {facet_id} based on the document sections and invention above.\n"
            "Return ONLY a JSON object:\n"
            "{\n"
            f'  "facet_id": "{facet_id}",\n'
            f'  "facet_name": "{facet_config["name"]}",\n'
            '  "score": 0,\n'
            '  "evidence_quote": "short quote from text [section_id]",\n'
            '  "reasoning": "why this score"\n'
            "}\n"
            "Return ONLY valid JSON, no markdown, no extra text.\n"
        )

    def run_patentability_unified(self, invention, retrieved_sections):
        """
        Option 2: Union all retrieved sections, 1 LLM call for all 3 facets.
        """
        config = load_patentability_config()
        if not config.get("enabled", True):
            print("  Patentability check disabled in config")
            return None

        print(f"\n--- Patentability Check (unified, {len(retrieved_sections)} sections) ---")
        context_text = self._build_section_context(retrieved_sections)
        prompt = self._build_rag_patentability_prompt(invention, context_text, config)
        response = self._call_llm(prompt, max_tokens=1500)
        self._log("patentability_response", {"response": response[:1500]})

        parsed = self._parse_json_response(response)
        if not parsed:
            print("  Patentability check: parse error")
            self._log("patentability_parse_error", {"raw": response[:500]})
            return None

        result, errors = validate_classification(parsed, config)
        self._log("patentability_result", {
            "classification": result.get("classification"),
            "total_score": result.get("total_score"),
        })

        classification = result.get("classification", "Unknown")
        total_score = result.get("total_score", 0)
        print(f"  Classification: {classification} (score: {total_score}/6)")
        for facet in result.get("facets", []):
            print(f"    Facet {facet.get('facet_id')}: {facet.get('score')}/2 — {facet.get('reasoning', '')[:80]}")
        print(f"  Justification: {result.get('justification', '')}")

        return result

    def run_patentability_per_facet(self, invention, retrieved_sections):
        """
        Option B: 3 separate LLM calls, one per facet.
        Each facet retrieves its own sections via cached facet embeddings,
        merged with the extraction-retrieved sections for full coverage.
        Runs in parallel (2 concurrent).
        """
        config = load_patentability_config()
        if not config.get("enabled", True):
            print("  Patentability check disabled in config")
            return None

        print(f"\n--- Patentability Check (per-facet, {len(retrieved_sections)} base sections) ---")
        facets_config = config["facets"]

        def _score_facet(facet_id):
            facet_conf = facets_config[facet_id]
            # Retrieve sections targeted to this facet
            facet_key = f"facet_{facet_id}"
            facet_retrieved = self._retrieve(facet_key, k=self.k)
            # Merge with extraction sections (deduped)
            merged = dict(retrieved_sections)
            for r in facet_retrieved:
                merged[r["section_id"]] = r
            print(f"    Facet {facet_id}: {len(merged)} sections ({len(facet_retrieved)} facet-specific)")
            context_text = self._build_section_context(merged)
            prompt = self._build_facet_prompt(invention, context_text, facet_id, facet_conf)
            response = self._call_llm(prompt, max_tokens=500)
            self._log(f"patentability_facet_{facet_id}", {"response": response[:500]})
            parsed = self._parse_json_response(response)
            if not parsed:
                print(f"    Facet {facet_id}: parse error")
                return {"facet_id": facet_id, "facet_name": facet_conf["name"], "score": 0,
                        "evidence_quote": "N/A", "reasoning": "Parse error"}
            return parsed

        # Run 3 facets in parallel (2 concurrent)
        async def _run_facets():
            sem = asyncio.Semaphore(3)
            async def _run_one(fid):
                async with sem:
                    return await asyncio.to_thread(_score_facet, fid)
            tasks = [_run_one(fid) for fid in sorted(facets_config.keys())]
            return await asyncio.gather(*tasks)

        facet_results = asyncio.run(_run_facets())

        # Assemble into full classification result
        assembled = {"facets": list(facet_results)}
        result, errors = validate_classification(assembled, config)
        self._log("patentability_result", {
            "classification": result.get("classification"),
            "total_score": result.get("total_score"),
        })

        classification = result.get("classification", "Unknown")
        total_score = result.get("total_score", 0)
        print(f"  Classification: {classification} (score: {total_score}/6)")
        for facet in result.get("facets", []):
            print(f"    Facet {facet.get('facet_id')}: {facet.get('score')}/2 — {facet.get('reasoning', '')[:80]}")
        print(f"  Justification: {result.get('justification', '')}")

        return result

    # ------------------------------------------------------------------
    # Schema validation with self-fix
    # ------------------------------------------------------------------

    def _run_schema_validation(self, invention, context_text):
        """
        Run schema validation. If invalid, ask LLM to fix errors using
        retrieved sections as context. Returns (possibly corrected) invention.
        """
        ok, errors = validate_schema(invention)
        self._log("schema_validation", {"ok": ok, "errors": errors})

        if ok:
            print("  Schema validation: PASSED")
            return invention

        print(f"  Schema validation: FAILED — {len(errors)} error(s)")
        for err in errors:
            print(f"    - {err}")

        error_list = "\n".join(f"- {e}" for e in errors)
        fix_prompt = (
            "You are an expert patent/invention analyst.\n\n"
            f"DOCUMENT SECTIONS:\n{context_text}\n\n"
            "The following invention extraction JSON failed schema validation:\n\n"
            f"INVENTION:\n{json.dumps(invention, indent=2)}\n\n"
            f"SCHEMA ERRORS:\n{error_list}\n\n"
            "Fix ALL errors and return the corrected JSON. "
            "Use the document sections above for any missing information. "
            "Return ONLY the full corrected JSON object, no other text."
        )

        response = self._call_llm(fix_prompt)
        self._log("schema_fix_response", {"response": response[:1000]})

        fixed = self._parse_json_response(response)
        if fixed:
            ok2, errors2 = validate_schema(fixed)
            self._log("schema_revalidation", {"ok": ok2, "errors": errors2})
            if ok2:
                print("  Schema re-validation: PASSED (fixed)")
                return fixed
            else:
                print(f"  Schema re-validation: still has {len(errors2)} error(s), proceeding anyway")
                return fixed

        print("  Schema fix produced unparseable JSON, keeping original")
        return invention

    # ------------------------------------------------------------------
    # Validation phase (self-assessment)
    # ------------------------------------------------------------------

    def _validate(self, invention, context_text, tool_feedback=""):
        """
        Ask the LLM to self-assess the extraction quality.
        Returns dict with {valid, missing_fields, suggestions, confidence}.
        """
        msg = (
            "ACTION: VALIDATE\n\n"
            f"DOCUMENT SECTIONS:\n{context_text}\n\n"
            "Validate this invention extraction for completeness and accuracy "
            "against the document sections above.\n\n"
            f"INVENTION:\n{json.dumps(invention, indent=2)}\n\n"
        )
        if tool_feedback:
            msg += f"PRIOR analysis result:\n{tool_feedback}\n\n"
        msg += (
            "Important:\n"
            "- The source may be primarily theoretical, analytical, or academic in overall contribution.\n"
            "- This does NOT by itself reduce extraction quality or reviewer confidence.\n"
            "- Your task is to judge the quality of the extraction against the source document.\n"
            "Evaluate:\n"
            "1. Are all required fields present and non-empty?\n"
            "2. Does the extraction faithfully reflect the source, even if the source is primarily theoretical?\n"
            "3. Does it clearly identify any concrete technical process, algorithmic procedure, or implementation details actually disclosed?\n"
            "4. Is the technical description sufficiently specific and source-supported?\n"
            "5. Are the key technical features genuinely technical and not vague marketing language?\n"
            "6. Does the extraction avoid overstating invention potential?\n"
            "7. Does the extraction avoid understating concrete technical content that is present?\n"
            "8. Are the citations accurate and appropriately used?\n"
            "Return JSON with these exact keys:\n"
            "{\n"
            '  "valid": true or false,\n'
            '  "missing_fields": ["field1", "field2"] or [],\n'
            '  "suggestions": "specific improvement suggestions as a single string",\n'
            '  "confidence": 0.0 to 1.0\n'
            "}\n\n"
            "RULES:\n"
            "- confidence must be a number from 0.0 to 1.0.\n"
            "- If extraction is complete and high-quality, confidence >= 0.85.\n"
            "- Use lower confidence only for actual extraction weaknesses, not merely because patentability is low.\n"
            "- Return JSON only, no markdown fences, no other text."
        )
        response = self._call_llm(msg, max_tokens=2000)
        self._log("validate_response", {"response": response})

        parsed = self._parse_json_response(response)
        if not parsed:
            self._log("validation_parse_error", {"raw": response[:500]})
            return {
                "valid": False,
                "missing_fields": ["unknown"],
                "suggestions": "Validator returned non-JSON; please return strict JSON only.",
                "confidence": 0.0,
            }
        return parsed

    @staticmethod
    def _normalize_suggestions(suggestions):
        """Normalize suggestions to string, return (str, is_empty)."""
        if not suggestions:
            return "", True
        if isinstance(suggestions, list):
            suggestions = "\n".join(str(s) for s in suggestions)
        suggestions = str(suggestions).strip()
        if suggestions.lower() in ("none", "n/a", "no suggestions", ""):
            return "", True
        return suggestions, False

    # ------------------------------------------------------------------
    # Refinement phase
    # ------------------------------------------------------------------

    def _refine(self, invention, suggestions, context_text):
        """
        Ask the LLM to improve the extraction based on feedback.
        Returns improved invention dict or None on failure.
        """
        prompt = (
            "ACTION: REFINE\n\n"
            f"DOCUMENT SECTIONS:\n{context_text}\n\n"
            "Improve this invention extraction based on the feedback below. "
            "Re-read the document sections above for additional evidence.\n\n"
            f"CURRENT EXTRACTION:\n{json.dumps(invention, indent=2)}\n\n"
            f"FEEDBACK / SUGGESTIONS:\n{suggestions}\n\n"
            "Return the improved JSON with the SAME structure INCLUDING the "
            '"citations" field. Update citations with fresh quotes from the '
            "document if any text changes.\n\n"
            "IMPORTANT:\n"
            "- Return JSON only, no other text.\n"
            "- Do NOT wrap in ```json fences or any markdown.\n"
            '- Include the "citations" object in the output.\n'
            "- All citations must be short direct quotes from the document."
        )

        response = self._call_llm(prompt)
        self._log("refine_response", {"response": response[:1000]})

        parsed = self._parse_json_response(response)
        if parsed and not parsed.get("parse_error"):
            return parsed
        self._log("refinement_parse_error", {"raw": response[:500]})
        return None

    # ------------------------------------------------------------------
    # JudgeBot (independent confidence calibration)
    # ------------------------------------------------------------------

    def _run_judge(self, invention):
        """
        Run the independent LLM judge (Meta Llama 3.1 70B) on the extraction.
        Returns (judge_confidence, judge_observation) or None on failure.
        """
        print("  Tool: JUDGE_BOT (independent confidence calibration)")

        judge_result = run_judge(
            self.bedrock, invention,
            rate_limiter=self.rate_limiter,
            circuit_breaker=self.circuit_breaker,
        )
        self._log("judge_result", {
            "scores": judge_result.get("scores"),
            "normalized_confidence": judge_result.get("normalized_confidence"),
            "error": judge_result.get("error"),
        })

        if judge_result.get("error"):
            print(f"  Judge error: {judge_result['error']}")
            return None

        judge_confidence = judge_result.get("normalized_confidence", 0.0)
        scores = judge_result.get("scores", {})
        rationales = judge_result.get("rationales", {})
        assessment = judge_result.get("overall_assessment", "")

        print(f"  Judge confidence: {judge_confidence:.2f}")
        for dim, score in scores.items():
            print(f"    {dim}: {score} — {rationales.get(dim, '')}")
        print(f"  Assessment: {assessment}")

        # Build observation string for refinement feedback
        score_lines = []
        for dim, score in scores.items():
            rationale = rationales.get(dim, "")
            score_lines.append(f"- {dim}: {score}/2 — {rationale}")
        score_summary = "\n".join(score_lines)

        judge_observation = (
            "TOOL OBSERVATION: JUDGE_BOT\n\n"
            "An independent LLM judge (Meta Llama 3.1) evaluated your "
            "extraction. Here are the results:\n\n"
            f"Dimension scores:\n{score_summary}\n\n"
            f"Judge confidence: {judge_confidence:.2f}\n"
            f"Assessment: {assessment}\n\n"
            "Take this feedback into account. If the judge scored any "
            "dimension below 2, consider how to improve those areas."
        )

        return judge_confidence, judge_observation

    def _calibrate_confidence(self, self_confidence, judge_confidence):
        """Combine self-reported and judge confidence using judge_config strategy."""
        if judge_confidence is None:
            return self_confidence

        config = load_judge_config()
        strategy = config.get("confidence_combination", "minimum")

        if strategy == "minimum":
            calibrated = min(self_confidence, judge_confidence)
        elif strategy == "average":
            calibrated = (self_confidence + judge_confidence) / 2
        elif strategy == "weighted":
            calibrated = 0.4 * self_confidence + 0.6 * judge_confidence
        else:
            calibrated = min(self_confidence, judge_confidence)

        print(f"  Calibrated confidence: {calibrated:.2f} "
              f"(self={self_confidence:.2f}, judge={judge_confidence:.2f}, "
              f"strategy={strategy})")
        self._log("confidence_calibration", {
            "self_confidence": self_confidence,
            "judge_confidence": judge_confidence,
            "calibrated": calibrated,
            "strategy": strategy,
        })

        return calibrated

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self):
        """
        Run the RAG-based extraction pipeline.

        Returns dict with:
          - success: bool
          - invention: merged invention JSON
          - iterations: number of RAG queries run
        """
        self.logs = []
        print(f"\n{'='*60}")
        print("INVENTION EXTRACTION AGENT (RAG-based)")
        print(f"{'='*60}")
        print(f"Model: {self.model_id}")
        print(f"Sections: {len(self.sections)} in-memory")
        print(f"Top-k retrieval: {self.k}")

        # Build FAISS index + embed queries
        self._build_index()
        self._embed_queries()

        # Run 4 targeted queries in parallel (2 concurrent LLM calls)
        async def _run_parallel():
            sem = asyncio.Semaphore(4)
            async def _run_one(i, rag_config):
                async with sem:
                    print(f"\n--- Query {i}/{len(RAG_QUERIES)} ---")
                    return await asyncio.to_thread(self._extract_fields, rag_config)
            tasks = [_run_one(i, rc) for i, rc in enumerate(RAG_QUERIES, 1)]
            return await asyncio.gather(*tasks)

        results = asyncio.run(_run_parallel())

        invention = {}
        all_citations = {}
        all_retrieved = {}  # deduped by section_id
        for result in results:
            partial = result["parsed"]
            for r in result["retrieved"]:
                all_retrieved[r["section_id"]] = r
            partial_citations = partial.pop("citations", {})
            if isinstance(partial_citations, dict):
                all_citations.update(partial_citations)
            invention.update(partial)

        # Attach merged citations
        invention["citations"] = all_citations

        # Build context from all retrieved sections (reused for all subsequent phases)
        context_text = self._build_section_context(all_retrieved)

        # ==== SCHEMA VALIDATION (with self-fix) ====
        print(f"\n--- Schema Validation ---")
        invention = self._run_schema_validation(invention, context_text)

        # ==== PATENTABILITY CHECK ====
        patentability = None
        pat_config = load_patentability_config()
        if pat_config.get("enabled", True):
            if self.patentability_mode == "per_facet":
                patentability = self.run_patentability_per_facet(invention, all_retrieved)
            else:
                patentability = self.run_patentability_unified(invention, all_retrieved)

            if patentability:
                classification = patentability.get("classification", "")
                if classification == "Scientific Discovery" and pat_config.get("early_stop_on_not_patentable"):
                    print("  STOP: classified as Scientific Discovery (early stop)")
                    return self._finalize(invention, patentability, all_retrieved,
                                          iterations=1, stop_reason="not_patentable",
                                          final_confidence=0.0)

        # ==== VALIDATE / REFINE LOOP ====
        tool_feedback = ""
        if patentability and patentability.get("justification"):
            tool_feedback = (
                f"PATENTABILITY: {patentability.get('classification')} "
                f"(score: {patentability.get('total_score')}/6)\n"
                f"Justification: {patentability.get('justification')}\n"
            )

        final_confidence = 0.0
        stop_reason = "max_iters_reached"
        iterations_run = 0

        for i in range(self.max_iterations):
            iterations_run = i + 1
            print(f"\n--- Validate/Refine iteration {i+1}/{self.max_iterations} ---")

            # VALIDATE
            print("  Action: VALIDATE")
            validation = self._validate(invention, context_text, tool_feedback=tool_feedback)
            tool_feedback = ""  # only pass on first iteration

            self_confidence = float(validation.get("confidence", 0.0))
            suggestions_str, no_suggestions = self._normalize_suggestions(
                validation.get("suggestions")
            )

            print(f"  Self-confidence: {self_confidence:.2f}")
            print(f"  Valid: {validation.get('valid')}")
            if validation.get("missing_fields"):
                print(f"  Missing fields: {validation.get('missing_fields')}")

            final_confidence = self_confidence
            self._log("validation_result", {
                "iteration": i + 1,
                "self_confidence": self_confidence,
                "no_suggestions": no_suggestions,
                "valid": validation.get("valid"),
            })

            # STOP CONDITIONS
            if self_confidence >= self.CONFIDENCE_THRESHOLD:
                stop_reason = f"confidence>={self.CONFIDENCE_THRESHOLD}"
                print(f"  STOP: {stop_reason}")
                break

            if no_suggestions:
                stop_reason = "no_suggestions"
                print(f"  STOP: {stop_reason}")
                break

            # REFINE
            print(f"  Action: REFINE (confidence={self_confidence:.2f} < {self.CONFIDENCE_THRESHOLD})")
            print(f"  Suggestions: {suggestions_str[:100]}...")

            refined = self._refine(invention, suggestions_str, context_text)
            if refined:
                # Schema validate the refinement
                refined = self._run_schema_validation(refined, context_text)
                invention = refined
                print(f"  Refined: {invention.get('invention_name', 'Unknown')}")
            else:
                print("  Refinement parse error, keeping previous version")

        # ==== POST-LOOP JUDGE ====
        print(f"\n--- Post-loop JudgeBot calibration ---")
        judge_result = self._run_judge(invention)
        if judge_result is not None:
            judge_confidence, judge_observation = judge_result
            final_confidence = self._calibrate_confidence(final_confidence, judge_confidence)

            # If judge dragged confidence below threshold, do one final refinement
            if final_confidence < self.CONFIDENCE_THRESHOLD and iterations_run < self.max_iterations:
                print(f"  Judge calibrated confidence {final_confidence:.2f} < {self.CONFIDENCE_THRESHOLD}, running final refinement")
                refined = self._refine(invention, judge_observation, context_text)
                if refined:
                    refined = self._run_schema_validation(refined, context_text)
                    invention = refined
                    print(f"  Refined after judge: {invention.get('invention_name', 'Unknown')}")
                    iterations_run += 1
                    stop_reason = "judge_refinement"

        return self._finalize(invention, patentability, all_retrieved,
                              iterations=iterations_run, stop_reason=stop_reason,
                              final_confidence=final_confidence)

    def _ensure_fields(self, invention):
        """Fill missing fields with defaults."""
        defaults = {
            "invention_name": "Unknown Invention",
            "technical_description": "N/A",
            "problem_statement": "N/A",
            "solution_approach": "N/A",
            "key_technical_features": [],
            "domain_classification": "Unknown",
            "statutory_category": "Process",
            "inventor_keywords": [],
            "citations": {"invention_name": ["N/A"]},
        }
        for key, default in defaults.items():
            if key not in invention or not invention[key]:
                invention[key] = default
        return invention

    def _finalize(self, invention, patentability, all_retrieved,
                  iterations, stop_reason, final_confidence):
        """Build and return the final result dict."""
        invention = self._ensure_fields(invention)
        ok, errors = validate_schema(invention)
        success = ok or (invention.get("invention_name") != "Unknown Invention")

        pat_summary = None
        if patentability:
            pat_summary = {
                "classification": patentability.get("classification"),
                "total_score": patentability.get("total_score"),
                "facets": {
                    f.get("facet_id"): {
                        "name":      f.get("facet_name", f.get("facet_id")),
                        "score":     f.get("score"),
                        "rationale": f.get("reasoning", f.get("rationale", "")),
                    }
                    for f in patentability.get("facets", [])
                },
                "justification": patentability.get("justification"),
                "recommendation": patentability.get("recommendation"),
            }

        self._log("complete", {
            "invention": invention,
            "patentability": pat_summary,
            "iterations": iterations,
            "stop_reason": stop_reason,
            "final_confidence": final_confidence,
        })

        print(f"\n{'='*60}")
        print("EXTRACTION COMPLETE")
        print(f"Invention: {invention.get('invention_name', 'Unknown')}")
        print(f"Fields: {list(invention.keys())}")
        print(f"Citations: {list(invention.get('citations', {}).keys())}")
        if pat_summary:
            print(f"Patentability: {pat_summary['classification']} ({pat_summary['total_score']}/6)")
        print(f"Iterations: {iterations}")
        print(f"Stop reason: {stop_reason}")
        print(f"Final confidence: {final_confidence:.2f}")
        print(f"Schema valid: {ok}")
        print(f"{'='*60}")

        return {
            "success": success,
            "invention": invention,
            "patentability": pat_summary,
            "iterations": iterations,
            "stop_reason": stop_reason,
            "final_confidence": final_confidence,
            "retrieved_sections": all_retrieved,
        }


# if __name__ == "__main__":
#     import boto3
#     from botocore.config import Config
#     start_time = time.time()
#     MODEL_OPUS = "us.anthropic.claude-opus-4-20250514-v1:0"
#     SECTIONS_PATH = "src/storage/sections_with_summary_and_embedding.json"

#     bedrock = boto3.client(
#         service_name="bedrock-runtime",
#         region_name="us-east-2",
#         config=Config(max_pool_connections=10),
#     )

#     agent = InventionExtractionAgentRAG(
#         bedrock_client=bedrock,
#         model_id=MODEL_OPUS,
#         sections_json_path=SECTIONS_PATH,
#         k=4,
#         max_iterations=3,
#         patentability_mode="per_facet",  # or "per_facet"
#     )

#     result = agent.run()
#     print(json.dumps(result["invention"], indent=2))
#     if result.get("patentability"):
#         print(json.dumps(result["patentability"], indent=2))
#     print("time:", time.time()-start_time)