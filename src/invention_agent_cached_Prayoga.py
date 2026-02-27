"""
Invention Extraction Agent with Prompt Caching

Uses Claude's prompt caching via Bedrock API to:
1. Cache the entire document as a system prompt prefix (avoids re-processing)
2. Accumulate ReAct reasoning, actions, and suggestions across iterations
   in a multi-turn conversation (the model sees its full history)
3. No chunking — the LLM reads the full document every time (via cache)
"""

import json
import re
import os
from datetime import datetime
from tools.schema_validator import validate_schema
from tools.judgeBot import run_judge, _load_config as load_judge_config
from utils.rate_limiter import BedrockRateLimiter, CircuitBreaker, CircuitBreakerOpenError, invoke_bedrock_with_retry
from tools.patentability_classifier import (
    build_patentability_prompt,
    validate_classification,
    load_config as load_patentability_config,
)


class InventionExtractionAgentCached:
    """
    ReAct-based invention extraction using prompt caching.

    Key differences from the chunk-based agent:
    - The ENTIRE document is placed in the system prompt with cache_control,
      so the model has full context on every turn without re-encoding.
    - A single multi-turn conversation accumulates all reasoning, actions,
      validation feedback, and refinements — the model can reference earlier
      thinking when refining.
    """

    CONFIDENCE_THRESHOLD = 0.85

    def __init__(self, bedrock_client, model_id, max_iterations=6, log_dir="logs",
                 rate_limiter=None, circuit_breaker=None):
        self.bedrock = bedrock_client
        self.model_id = model_id
        self.max_iterations = max_iterations
        self.log_dir = log_dir
        self.logs = []
        self.rate_limiter = rate_limiter or BedrockRateLimiter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    # ------------------------------------------------------------------
    # LLM call — multi-turn with cached system prompt
    # ------------------------------------------------------------------

    def _call_llm(self, system_blocks, messages, max_tokens=4000):
        """
        Call Bedrock with:
        - system_blocks: list of content blocks (the document block has cache_control)
        - messages: accumulated multi-turn conversation
        """
        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "system": system_blocks,
            "messages": messages,
        })

        result = invoke_bedrock_with_retry(
            self.bedrock,
            model_id=self.model_id,
            body=request_body,
            rate_limiter=self.rate_limiter,
            circuit_breaker=self.circuit_breaker,
        )
        usage = result.get("usage", {})
        self._log("llm_usage", {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        })
        content = result.get("content")
        if not content or not isinstance(content, list) or not content[0].get("text"):
            raise RuntimeError(f"Bedrock returned unexpected response structure: {result!r:.500}")
        return content[0]["text"]

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
            filename = f"react_agent_cached_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.log_dir, filename)
        with open(filepath, "w") as f:
            json.dump(self.logs, f, indent=2)
        return filepath

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    def _parse_json_response(self, response):
        text = response.strip()
        # print(text) #TS
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        try:
            # print("A")
            return json.loads(text.strip())
        except json.JSONDecodeError:
            # print("B")
            pass
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                # print("C")
                return json.loads(match.group())
        except json.JSONDecodeError:
            # print("D")
            pass
        # print("E")
        return None
    

    # ------------------------------------------------------------------
    # Build the cached system prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _format_sections_text(sections):
        """
        Format normalized sections into a structured document string.

        Each section is rendered with its title and section ID so the model
        can reference specific sections when citing evidence.
        """
        parts = []
        for sec in sections:
            sid = sec.get("section_id", "")
            title = sec.get("title", "Untitled")
            text = sec.get("text", "")
            parts.append(
                f"--- [{sid}] {title} ---\n{text}"
            )
        return "\n\n".join(parts)

    def _build_system_blocks(self, sections):
        """
        Returns the system prompt as a list of content blocks.

        Block 1 (CACHED): the document text organized by sections — this is
                           the expensive part that we want to cache across turns.
        Block 2: agent instructions (small, changes rarely).

        Parameters
        ----------
        sections : list[dict]
            Normalized sections from textractChunkingv2.normalize_textract_chunks.
            Each dict has keys: section_id, title, text, source_chunk_key.
        """
        document_text = self._format_sections_text(sections)
        return [
            {
                "type": "text",
                "text": (
                    "You are an expert patent / invention analyst. "
                    "Below is the FULL TEXT of a document, organized into "
                    "named sections. Use it as your sole source of evidence "
                    "when answering. Each section is prefixed with its "
                    "section ID (e.g. [s01]) and title.\n\n"
                    "========== DOCUMENT START ==========\n"
                    f"{document_text}\n"
                    "========== DOCUMENT END ==========\n"
                ),
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": (
                    "You participate in a ReAct loop. On each turn the user "
                    "will ask you to EXTRACT, VALIDATE, or REFINE an invention "
                    "description. Always respond with valid JSON only — no "
                    "markdown fences, no extra commentary.\n"
                    "When you reference evidence, quote short passages from the "
                    "document"
                    # "and note the section ID and title "

                    # "(e.g., [s03] Methods).\n\n"
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
                ),
            },
        ]

    # ------------------------------------------------------------------
    # Prompt builders for each phase
    # ------------------------------------------------------------------

    @staticmethod
    def _extraction_user_msg():
        return (
            "ACTION: EXTRACT\n\n"
            "Read the entire document above and extract the invention details.\n\n"
            "Return this exact JSON structure:\n"
            "{\n"
            '  "invention_name": "concise name (max 10 words)",\n'
            '  "technical_description": "2-4 sentences",\n'
            '  "problem_statement": "what problem it solves (2-3 sentences)",\n'
            '  "solution_approach": "how it solves it (2-3 sentences)",\n'
            '  "key_technical_features": ["feature1", "feature2", "feature3", "feature4", "feature5"],\n'
            '  "domain_classification": "e.g., AI/ML, Robotics, Healthcare, etc.",\n'
            '  "statutory_category": "Process, Machine, Manufacture, or Composition of Matter",\n'
            '  "inventor_keywords": ["keyword1", "keyword2", "keyword3"],\n'
            '  "citations": {\n'
            '    "invention_name": ["quoted evidence snippet 1"],\n'
            '    "technical_description": ["quoted evidence snippet 2"],\n'
            '    "problem_statement": ["quoted evidence snippet 3"],\n'
            '    "solution_approach": ["quoted evidence snippet 4"],\n'
            '    "key_technical_features": ["quoted evidence snippet 5"],\n'
            '    "domain_classification": ["quoted evidence snippet 6"],\n'
            '    "statutory_category": ["quoted evidence snippet 7"],\n'
            '    "inventor_keywords": ["quoted evidence snippet 8"]\n'
            "  }\n"
            "}\n\n"
            "IMPORTANT:\n"
            "- Return JSON only, no other text.\n"
            "- All fields must be non-empty.\n"
            '- The "citations" object is REQUIRED and must not be empty.\n'
            "- For EACH field in citations, include 1-3 SHORT direct quotes "
            "from the document that support that field.\n"
        )

    @staticmethod
    def _validation_user_msg(invention_json, tool_feedback=""):
        msg = (
            "ACTION: VALIDATE\n\n"
            "Validate this invention extraction for completeness and accuracy "
            "against the document above.\n\n"
            f"INVENTION:\n{json.dumps(invention_json, indent=2)}\n\n"
        )
        if tool_feedback:
            msg += f"PRIOR TOOL FEEDBACK (take into account):\n{tool_feedback}\n\n"
        msg += (
            "Evaluate:\n"
            "1. Are all required fields present and non-empty?\n"
            "2. Is the technical description specific and detailed enough?\n"
            "3. Are key_technical_features actually technical (not vague)?\n"
            "4. Is the problem_statement clear?\n"
            "5. Does solution_approach explain HOW the invention works?\n"
            "6. Do the citations accurately reflect what the document says?\n\n"
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
            "- Return JSON only, no markdown fences, no other text."
        )
        return msg

    @staticmethod
    def _refinement_user_msg(invention_json, suggestions):
        return (
            "ACTION: REFINE\n\n"
            "Improve this invention extraction based on the feedback below. "
            "Re-read the document above for additional evidence.\n\n"
            f"CURRENT EXTRACTION:\n{json.dumps(invention_json, indent=2)}\n\n"
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

    # ------------------------------------------------------------------
    # Tool: Schema Validation (run-and-observe)
    # ------------------------------------------------------------------

    def _run_schema_validation(self, parsed, system_blocks, messages, phase):
        """
        Run schema validation as a tool observation in the conversation.

        If the schema is valid, returns the parsed invention as-is.
        If invalid, injects the errors as a SCHEMA_VALIDATION observation
        into the conversation and gives the model one chance to fix them.
        Returns the (possibly corrected) invention dict.
        """
        ok, errors = validate_schema(parsed)
        self._log(f"schema_validation_{phase}", {"ok": ok, "errors": errors})

        if ok:
            print(f"  Schema validation: PASSED")
            return parsed

        print(f"  Schema validation: FAILED — {len(errors)} error(s)")
        for err in errors:
            print(f"    - {err}")

        # Feed errors back as a tool observation
        error_list = "\n".join(f"- {e}" for e in errors)
        messages.append({
            "role": "user",
            "content": (
                "TOOL OBSERVATION: SCHEMA_VALIDATION\n\n"
                "Your JSON output failed schema validation with these errors:\n"
                f"{error_list}\n\n"
                "Fix ALL errors and return the corrected JSON. "
                "Return ONLY the full corrected JSON object, no other text."
            ),
        })

        response = self._call_llm(system_blocks, messages, max_tokens=2000)
        self._log(f"schema_fix_response_{phase}", {"response": response[:1000]})
        messages.append({"role": "assistant", "content": response})

        fixed = self._parse_json_response(response)
        if fixed:
            ok2, errors2 = validate_schema(fixed)
            self._log(f"schema_revalidation_{phase}", {"ok": ok2, "errors": errors2})
            if ok2:
                print(f"  Schema re-validation: PASSED (fixed)")
                return fixed
            else:
                print(f"  Schema re-validation: still has {len(errors2)} error(s), proceeding anyway")
                return fixed

        print(f"  Schema fix produced unparseable JSON, keeping original")
        return parsed

    # ------------------------------------------------------------------
    # Tool: JudgeBot — independent confidence calibration
    # ------------------------------------------------------------------

    def _run_judge_validation(self, invention, system_blocks, messages):
        """
        Run the judgeBot tool to get an independent confidence score from
        a non-Anthropic model (Meta Llama 3.1 70B).

        Returns a calibrated confidence by combining the agent's self-reported
        confidence with the judge's score using the strategy in judge_config.json.

        The judge's feedback is injected into the conversation as a tool
        observation so the agent can see exactly what an independent reviewer
        thought of its work.
        """
        print("  Tool: JUDGE_BOT (independent confidence calibration)")

        judge_result = run_judge(
            self.bedrock, invention,
            rate_limiter=self.rate_limiter,
            circuit_breaker=self.circuit_breaker,
        )
        self._log("judge_result", {
            "scores": judge_result.get("scores"),
            "rationales": judge_result.get("rationales"),
            "normalized_confidence": judge_result.get("normalized_confidence"),
            "overall_assessment": judge_result.get("overall_assessment"),
            "error": judge_result.get("error"),
        })

        judge_confidence = judge_result.get("normalized_confidence", 0.0)
        scores = judge_result.get("scores", {})
        rationales = judge_result.get("rationales", {})
        assessment = judge_result.get("overall_assessment", "")

        if judge_result.get("error"):
            print(f"  Judge error: {judge_result['error']}")
            print(f"  Falling back to self-reported confidence only")
            return None  # signal caller to use self-reported confidence

        print(f"  Judge confidence: {judge_confidence:.2f}")
        for dim, score in scores.items():
            rationale = rationales.get(dim, "")
            print(f"    {dim}: {score} — {rationale}")
        print(f"  Assessment: {assessment}")

        # Build observation for the agent's conversation
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
            "dimension below 2, consider how to improve those areas "
            "in refinement."
        )

        return judge_confidence, judge_observation

    def _calibrate_confidence(self, self_confidence, judge_confidence):
        """
        Combine self-reported and judge confidence using the strategy
        from judge_config.json.
        """
        if judge_confidence is None:
            return self_confidence

        config = load_judge_config()
        strategy = config.get("confidence_combination", "minimum")

        if strategy == "minimum":
            calibrated = min(self_confidence, judge_confidence)
        elif strategy == "average":
            calibrated = (self_confidence + judge_confidence) / 2
        elif strategy == "weighted":
            # Trust judge more (0.6) since self-report is optimistic
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
    # Tool: Patentability Classifier (runs in cached Claude conversation)
    # ------------------------------------------------------------------

    def _run_patentability_check(self, invention, system_blocks, messages):
        """
        Run patentability classification as a tool within the existing
        Claude conversation. Since the document sections are already
        cached in the system prompt, this costs only output tokens.

        Applies a 3-facet rubric (A-C) and classifies the invention as:
          - Scientific Discovery (not patentable)
          - Borderline Case (needs work)
          - Potential Invention (proceed)

        Returns dict with classification result, or None on failure.
        The result and feedback are injected into the conversation.
        """
        config = load_patentability_config()
        if not config.get("enabled", True):
            print("  Tool: PATENTABILITY_CHECK — disabled in config, skipping")
            return None

        print("  Tool: PATENTABILITY_CHECK (3-facet rubric)")

        prompt = build_patentability_prompt(invention, config)
        # print(prompt) #TS
        # exit() #TS

        messages.append({
            "role": "user",
            "content": prompt,
        })

        response = self._call_llm(system_blocks, messages, max_tokens=1500)
        self._log("patentability_response", {"response": response[:1500]})
        messages.append({"role": "assistant", "content": response})

        parsed = self._parse_json_response(response)
        if not parsed:
            self._log("patentability_parse_error", {"raw": response[:500]})
            print("  Patentability check: parse error, skipping")
            return None

        result, errors = validate_classification(parsed, config)
        self._log("patentability_result", {
            "classification": result.get("classification"),
            "total_score": result.get("total_score"),
            "facets": result.get("facets"),
            "justification": result.get("justification"),
            "validation_errors": errors,
        })

        classification = result.get("classification", "Unknown")
        total_score = result.get("total_score", 0)
        justification = result.get("justification", "")

        print(f"  Classification: {classification} (score: {total_score}/6)")
        for facet in result.get("facets", []):
            fid = facet.get("facet_id", "?")
            fname = facet.get("facet_name", "")
            fscore = facet.get("score", 0)
            reasoning = facet.get("reasoning", "")
            print(f"    Facet {fid} ({fname}): {fscore}/2 — {reasoning[:80]}")
        print(f"  Justification: {justification}")

        # Inject observation into conversation
        facet_lines = []
        for facet in result.get("facets", []):
            fid = facet.get("facet_id", "?")
            fname = facet.get("facet_name", "")
            fscore = facet.get("score", 0)
            reasoning = facet.get("reasoning", "")
            evidence = facet.get("evidence_quote", "")
            facet_lines.append(
                f"- Facet {fid} ({fname}): {fscore}/2\n"
                f"  Reasoning: {reasoning}\n"
                f"  Evidence: {evidence}"
            )
        facet_summary = "\n".join(facet_lines)

        observation = (
            "TOOL OBSERVATION: PATENTABILITY_CHECK\n\n"
            f"Classification: {classification} (total score: {total_score}/6)\n\n"
            f"Facet scores:\n{facet_summary}\n\n"
            f"Justification: {justification}\n"
            f"Recommendation: {result.get('recommendation', '')}\n\n"
        )

        if classification == "Scientific Discovery":
            observation += (
                "WARNING: This extraction was classified as a Scientific Discovery, "
                "not a patentable invention. During refinement, focus on identifying "
                "concrete mechanisms, systems, or processes described in the paper "
                "that go beyond theoretical contributions. Look for specific "
                "implementations in Methods/Design sections."
            )
        elif classification == "Borderline Case":
            observation += (
                "NOTE: This is a borderline case. During refinement, strengthen "
                "the technical_description and solution_approach with more specific "
                "implementation details. Look for reproducible steps, system "
                "architecture, or measurable improvements in the document."
            )
        else:
            observation += (
                "This extraction appears to describe a patentable invention. "
                "Proceed with prior art search."
            )

        # Return observation text to be merged into the next prompt
        # (instead of appending as a separate user message)
        result["_observation"] = observation
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_suggestions(self, suggestions):
        if suggestions is None:
            return "", True
        if isinstance(suggestions, list):
            suggestions = " ".join(str(s) for s in suggestions)
        suggestions = str(suggestions).strip()
        return suggestions, len(suggestions) == 0

    def _ensure_fields(self, invention):
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
        if invention is None or invention.get("parse_error"):
            return defaults
        for key, default in defaults.items():
            if key not in invention or not invention[key]:
                invention[key] = default
        return invention

    # ------------------------------------------------------------------
    # Main ReAct loop
    # ------------------------------------------------------------------

    def run(self, sections):
        """
        Run the ReAct agent loop.

        Parameters
        ----------
        sections : list[dict]
            Normalized sections from textractChunkingv2.normalize_textract_chunks.
            Each dict has keys: section_id, title, text, source_chunk_key.

        The section-wise document is cached in the system prompt.
        Each iteration appends user/assistant turns so the model
        accumulates all prior reasoning, actions, and suggestions.
        """
        self.logs = []
        total_chars = sum(len(s.get("text", "")) for s in sections)
        self._log("start", {
            "num_sections": len(sections),
            "total_chars": total_chars,
            "section_titles": [s.get("title", "") for s in sections],
        })

        system_blocks = self._build_system_blocks(sections)
        messages = []  # multi-turn conversation accumulator

        print(f"\n{'='*60}")
        print("INVENTION EXTRACTION AGENT (ReAct + Prompt Caching)")
        print(f"{'='*60}")
        print(f"Sections: {len(sections)} | Total chars: {total_chars}")
        print(f"Model: {self.model_id}")
        print(f"Confidence threshold: {self.CONFIDENCE_THRESHOLD}")
        print(f"Section-wise document passed as cached system prefix\n")

        invention = None
        patentability = None
        stop_reason = "max_iters_reached"
        final_confidence = 0.0
        iterations_run = 0

        for i in range(self.max_iterations):
          iterations_run = i + 1
          print(f"--- Iteration {i+1}/{self.max_iterations} ---")
          self._log("iteration_start", {"iteration": i + 1})

          try:
            # ==== EXTRACTION PHASE ====
            if invention is None:
                print("Action: EXTRACT (full document in cache)")

                # Append extraction request to conversation
                messages.append({
                    "role": "user",
                    "content": self._extraction_user_msg(),
                })

                response = self._call_llm(system_blocks, messages, max_tokens=2000)
                self._log("extract_response", {"response": response[:1000]})

                # Append assistant response to conversation history
                messages.append({"role": "assistant", "content": response})

                parsed = self._parse_json_response(response)
                if not parsed:
                    print("  Parse error in extraction, requesting immediate fix...")
                    self._log("extraction_parse_error", {"raw": response[:500]})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON. "
                            "Please try again — return ONLY a JSON object, "
                            "no markdown, no commentary."
                        ),
                    })
                    retry_response = self._call_llm(system_blocks, messages, max_tokens=2000)
                    self._log("extract_retry_response", {"response": retry_response[:1000]})
                    messages.append({"role": "assistant", "content": retry_response})
                    parsed = self._parse_json_response(retry_response)
                    if not parsed:
                        print("  Retry also failed to produce valid JSON, continuing...")
                        self._log("extraction_retry_parse_error", {"raw": retry_response[:500]})
                        continue

                # Run schema validation as a tool observation
                parsed = self._run_schema_validation(
                    parsed, system_blocks, messages, phase="extract"
                )

                invention = parsed
                print(f"  Extracted: {invention.get('invention_name', 'Unknown')}")

                # Run patentability check (uses cached document — free)
                patentability = self._run_patentability_check(
                    invention, system_blocks, messages
                )
                if patentability:
                    pat_config = load_patentability_config()
                    classification = patentability.get("classification", "")

                    if classification == "Scientific Discovery" and pat_config.get("early_stop_on_not_patentable"):
                        stop_reason = "not_patentable"
                        print(f"  STOP: classified as Scientific Discovery (early stop enabled)")
                        break

                    if classification == "Borderline Case" and pat_config.get("force_refine_on_borderline"):
                        print(f"  Borderline case — will force refinement to strengthen extraction")

                # Fall through to validation in the same iteration

            # ==== VALIDATION PHASE ====
            print("Action: VALIDATE")

            # Collect tool feedback to merge into validation prompt
            tool_feedback = ""
            if patentability and patentability.get("_observation"):
                tool_feedback += patentability["_observation"] + "\n\n"

            messages.append({
                "role": "user",
                "content": self._validation_user_msg(invention, tool_feedback=tool_feedback),
            })

            response = self._call_llm(system_blocks, messages, max_tokens=600)
            self._log("validate_response", {"response": response})

            messages.append({"role": "assistant", "content": response})

            validation = self._parse_json_response(response)
            if not validation:
                self._log("validation_parse_error", {"raw": response[:500]})
                validation = {
                    "valid": False,
                    "missing_fields": ["unknown"],
                    "suggestions": "Validator returned non-JSON; please return strict JSON only.",
                    "confidence": 0.0,
                }

            self_confidence = float(validation.get("confidence", 0.0))
            suggestions_str, no_suggestions = self._normalize_suggestions(
                validation.get("suggestions")
            )

            print(f"  Self-reported confidence: {self_confidence:.2f}")
            print(f"  Suggestions empty: {no_suggestions}")
            print(f"  Valid: {validation.get('valid')}")
            if validation.get("missing_fields"):
                print(f"  Missing fields: {validation.get('missing_fields')}")

            final_confidence = self_confidence

            self._log("validation_result", {
                "iteration": i + 1,
                "self_confidence": self_confidence,
                "no_suggestions": no_suggestions,
                "valid": validation.get("valid"),
                "suggestions_preview": suggestions_str[:200] if suggestions_str else "",
            })

            # ==== STOP CONDITIONS ====
            if self_confidence >= self.CONFIDENCE_THRESHOLD:
                stop_reason = f"confidence>={self.CONFIDENCE_THRESHOLD}"
                print(f"  STOP: {stop_reason}")
                break

            if no_suggestions:
                stop_reason = "no_suggestions"
                print(f"  STOP: {stop_reason}")
                break

            # ==== REFINEMENT PHASE ====
            print(f"  Continuing: confidence={self_confidence:.2f} < {self.CONFIDENCE_THRESHOLD}, has suggestions")
            print("Action: REFINE")
            print(f"  Suggestions: {suggestions_str[:100]}...")

            messages.append({
                "role": "user",
                "content": self._refinement_user_msg(invention, suggestions_str),
            })

            response = self._call_llm(system_blocks, messages, max_tokens=2000)
            self._log("refine_response", {"response": response[:1000]})

            messages.append({"role": "assistant", "content": response})

            parsed = self._parse_json_response(response)
            if parsed and not parsed.get("parse_error"):
                # Run schema validation as a tool observation
                parsed = self._run_schema_validation(
                    parsed, system_blocks, messages, phase="refine"
                )
                invention = parsed
                print(f"  Refined: {invention.get('invention_name', 'Unknown')}")
            else:
                print("  Refinement parse error, keeping previous version")
                self._log("refinement_parse_error", {"raw": response[:500]})

          except CircuitBreakerOpenError as e:
            print(f"  Circuit breaker open: {e}")
            self._log("circuit_breaker_open", {"error": str(e)})
            stop_reason = "circuit_breaker_open"
            break
          except Exception as e:
            print(f"  Iteration {i+1} failed: {e}")
            self._log("iteration_error", {"iteration": i + 1, "error": str(e)})
            stop_reason = f"error_iteration_{i+1}"
            # Continue to next iteration if possible; break if fatal
            if invention is None:
                continue  # retry extraction
            break  # have partial result, stop and return it

        # ==== POST-LOOP JUDGE ====
        if invention is not None and not invention.get("parse_error"):
            print(f"\n--- Post-loop JudgeBot calibration ---")
            judge_result = self._run_judge_validation(
                invention, system_blocks, messages
            )
            if judge_result is not None:
                judge_confidence, judge_observation = judge_result
                final_confidence = self._calibrate_confidence(final_confidence, judge_confidence)

                # If judge dragged confidence below threshold and we have iterations left,
                # do one final refinement pass with judge feedback
                if final_confidence < self.CONFIDENCE_THRESHOLD and iterations_run < self.max_iterations:
                    print(f"  Judge calibrated confidence {final_confidence:.2f} < {self.CONFIDENCE_THRESHOLD}, running final refinement")
                    messages.append({
                        "role": "user",
                        "content": self._refinement_user_msg(invention, judge_observation),
                    })
                    response = self._call_llm(system_blocks, messages, max_tokens=2000)
                    self._log("judge_triggered_refine", {"response": response[:1000]})
                    messages.append({"role": "assistant", "content": response})

                    parsed = self._parse_json_response(response)
                    if parsed and not parsed.get("parse_error"):
                        parsed = self._run_schema_validation(
                            parsed, system_blocks, messages, phase="judge_refine"
                        )
                        invention = parsed
                        print(f"  Refined after judge: {invention.get('invention_name', 'Unknown')}")
                        iterations_run += 1
                        stop_reason = "judge_refinement"

        # ==== FINALIZE ====
        extraction_succeeded = invention is not None and not invention.get("parse_error")
        final_invention = self._ensure_fields(invention)

        # Build patentability summary for return value
        pat_summary = None
        if patentability:
            pat_summary = {
                "classification": patentability.get("classification"),
                "total_score": patentability.get("total_score"),
                "facets": {
                    f.get("facet_id"): f.get("score")
                    for f in patentability.get("facets", [])
                },
                "justification": patentability.get("justification"),
                "recommendation": patentability.get("recommendation"),
            }

        self._log("complete", {
            "invention": final_invention,
            "patentability": pat_summary,
            "iterations": iterations_run,
            "stop_reason": stop_reason,
            "final_confidence": final_confidence,
            "total_conversation_turns": len(messages),
        })

        print(f"\n{'='*60}")
        print("EXTRACTION COMPLETE")
        print(f"Invention: {final_invention.get('invention_name', 'Unknown')}")
        print(f"Citations: {final_invention.get('citations', {})}")
        if pat_summary:
            print(f"Patentability: {pat_summary['classification']} ({pat_summary['total_score']}/6)")
        print(f"Iterations: {iterations_run}")
        print(f"Stop reason: {stop_reason}")
        print(f"Final confidence: {final_confidence:.2f}")
        print(f"Conversation turns: {len(messages)}")

        return {
            "success": extraction_succeeded,
            "invention": final_invention,
            "patentability": pat_summary,
            "iterations": iterations_run,
            "stop_reason": stop_reason,
            "confidence": final_confidence,
            "conversation_turns": len(messages),
        }
