# Plan: Integrate Validation/Refinement/Judge Loop into RAG Agent

## What we're adding to `invention_agent_rag.py`

The Prayoga cached agent has a full ReAct loop after extraction. We'll port these 4 features into the RAG agent, adapted for inline context (no cached system prompt).

## Steps

### 1. Add schema validation with self-fix
Port `_run_schema_validation()` from Prayoga. After merging the 4 extraction results:
- Run `validate_schema(invention)`
- If it fails, build a prompt with the retrieved sections + schema errors + current invention JSON, ask the LLM to fix it
- Re-validate the fixed result
- This replaces the current basic schema check in `run()`

### 2. Add validation phase (self-assessment)
Port `_validation_user_msg()` from Prayoga as `_validate()`:
- Build a prompt with: retrieved sections context + invention JSON + evaluation criteria
- LLM returns `{valid, missing_fields, suggestions, confidence}`
- This gives us a self-reported confidence score and improvement suggestions

### 3. Add refinement phase
Port `_refinement_user_msg()` from Prayoga as `_refine()`:
- If confidence < threshold (0.85) and suggestions exist, build a prompt with: retrieved sections + current invention + suggestions
- LLM returns improved invention JSON
- Run schema validation on the refined result
- Loop: validate → refine → validate until confidence >= threshold or no suggestions or max iterations

### 4. Add JudgeBot integration
Port `_run_judge_validation()` and `_calibrate_confidence()`:
- After the validate/refine loop ends, call `run_judge()` from `tools/judgeBot.py`
- Combine self-confidence and judge confidence using strategy from `judge_config.json`
- If calibrated confidence drops below threshold and iterations remain, do one final refinement with judge feedback

### 5. Update `run()` flow
New flow in `run()`:
```
1. Load index + query cache
2. Extract (4 parallel RAG queries) → merge invention + collected sections
3. Schema validation with self-fix
4. Patentability check (unified or per-facet — configurable)
5. Validate/Refine loop (max_iterations, confidence threshold)
6. JudgeBot post-loop calibration
7. Final refinement if judge drags confidence down
8. Return result
```

### 6. Add `__init__` params
- `max_iterations` (default 3) — for validate/refine loop
- `confidence_threshold` (default 0.85)
- `patentability_mode` (default "unified") — "unified" or "per_facet"

## Key adaptation: no cached system prompt
Every prompt in the RAG agent must include the retrieved section text inline. We already have `_build_section_context()` and `all_retrieved` dict. The validation/refinement/judge prompts will include this context.

## Files modified
- `src/invention_agent_rag.py` — all changes go here
- No changes to `judgeBot.py`, `schema_validator.py`, `patentability_classifier.py` — reuse as-is