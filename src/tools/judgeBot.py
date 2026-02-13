# tools/judgeBot.py
"""
LLM Judge for invention extraction confidence calibration.

Uses a non-Anthropic model (default: Meta Llama 3.1 70B) via Bedrock
to independently evaluate the quality of an invention extraction.
Scores across configurable rubric dimensions and returns a calibrated
confidence score.

Does NOT need the source document — evaluates the extraction on its
own internal quality, specificity, and consistency.
"""

import json
import os

from utils.rate_limiter import BedrockRateLimiter, CircuitBreaker, invoke_bedrock_with_retry

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "judge_config.json")


def _load_config(config_path=None):
    path = config_path or _CONFIG_PATH
    with open(path, "r") as f:
        return json.load(f)


def _build_rubric_prompt(config):
    """Build the scoring rubric section of the prompt from config."""
    lines = []
    dims = config["dimensions"]
    for i, (name, dim) in enumerate(dims.items(), 1):
        lines.append(f"Dimension {i}: {name.upper()}")
        lines.append(f"  What to evaluate: {dim['description']}")
        for score, meaning in dim["scoring"].items():
            lines.append(f"  Score {score}: {meaning}")
        lines.append("")
    return "\n".join(lines)


def _build_judge_prompt(invention_json, config):
    """Build the full prompt for the judge model."""
    rubric = _build_rubric_prompt(config)
    dims = config["dimensions"]
    dim_names = list(dims.keys())
    max_total = sum(d["max_score"] for d in dims.values())

    score_fields = ", ".join(f'"{n}": <0-{dims[n]["max_score"]}>' for n in dim_names)

    return (
        "You are an expert evaluator for patent invention extractions. "
        "Your job is to judge the QUALITY of an invention extraction JSON "
        "based on a scoring rubric. You do NOT have the source document — "
        "evaluate based on internal quality, specificity, and consistency.\n\n"
        "INVENTION EXTRACTION TO EVALUATE:\n"
        f"{json.dumps(invention_json, indent=2)}\n\n"
        "SCORING RUBRIC:\n"
        f"{rubric}\n"
        f"Total possible score: {max_total} "
        f"(across {len(dims)} dimensions, each 0-{dims[dim_names[0]]['max_score']})\n\n"
        "INSTRUCTIONS:\n"
        "1. Evaluate the extraction against EACH dimension.\n"
        "2. For each dimension, provide a brief rationale (1 sentence) and a score.\n"
        "3. Return your evaluation as JSON with this exact structure:\n"
        "{\n"
        f"  \"scores\": {{{score_fields}}},\n"
        "  \"rationales\": {" + ", ".join(f'"{n}": "<1 sentence>"' for n in dim_names) + "},\n"
        f"  \"total_score\": <sum of all dimension scores, 0-{max_total}>,\n"
        "  \"normalized_confidence\": <total_score / {max_total}, 0.0 to 1.0>,\n"
        "  \"overall_assessment\": \"<1-2 sentence summary>\"\n"
        "}\n\n"
        "RULES:\n"
        "- Return ONLY valid JSON, no markdown fences, no extra text.\n"
        "- Be critical and objective. Do not inflate scores.\n"
        "- A score of 2 means genuinely excellent, not merely acceptable.\n"
    )


def run_judge(bedrock_client, invention_json, config_path=None,
              rate_limiter=None, circuit_breaker=None):
    """
    Run the LLM judge on an invention extraction.

    Parameters
    ----------
    bedrock_client : boto3 bedrock-runtime client
    invention_json : dict
        The invention extraction to evaluate.
    config_path : str, optional
        Path to judge_config.json. Defaults to the one in this directory.
    rate_limiter : BedrockRateLimiter, optional
        Shared rate limiter. Created if not provided.
    circuit_breaker : CircuitBreaker, optional
        Shared circuit breaker. Created if not provided.

    Returns
    -------
    dict with keys:
        - scores: dict of dimension -> score
        - rationales: dict of dimension -> rationale string
        - total_score: int
        - normalized_confidence: float (0.0 - 1.0)
        - overall_assessment: str
        - raw_response: str (for logging)
    Returns a fallback dict on any failure.
    """
    if rate_limiter is None:
        rate_limiter = BedrockRateLimiter()
    if circuit_breaker is None:
        circuit_breaker = CircuitBreaker()

    config = _load_config(config_path)
    model_id = config["model_id"]
    temperature = config.get("temperature", 0.3)
    max_tokens = config.get("max_tokens", 1000)

    # Strip internal fields the judge shouldn't see
    clean = {k: v for k, v in invention_json.items() if not k.startswith("_")}

    prompt = _build_judge_prompt(clean, config)

    request_body = json.dumps({
        "prompt": f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "max_gen_len": max_tokens,
        "temperature": temperature,
    })

    try:
        result = invoke_bedrock_with_retry(
            bedrock_client,
            model_id=model_id,
            body=request_body,
            rate_limiter=rate_limiter,
            circuit_breaker=circuit_breaker,
        )
        raw_text = result.get("generation", "")
    except Exception as e:
        return _fallback_result(f"Judge model call failed: {e}")

    # Parse JSON from response
    parsed = _parse_json(raw_text)
    if not parsed:
        return _fallback_result(f"Judge returned unparseable response", raw_text)

    # Validate and normalize the result
    dims = config["dimensions"]
    max_total = sum(d["max_score"] for d in dims.values())

    scores = parsed.get("scores", {})
    rationales = parsed.get("rationales", {})

    # Recompute total and normalized confidence from individual scores
    # (don't trust the model's arithmetic)
    actual_total = 0
    for dim_name, dim_cfg in dims.items():
        s = scores.get(dim_name, 0)
        # Clamp to valid range
        s = max(0, min(int(s), dim_cfg["max_score"]))
        scores[dim_name] = s
        actual_total += s * dim_cfg.get("weight", 1.0)

    weighted_max = sum(d["max_score"] * d.get("weight", 1.0) for d in dims.values())
    normalized = round(actual_total / weighted_max, 2) if weighted_max > 0 else 0.0

    return {
        "scores": scores,
        "rationales": rationales,
        "total_score": actual_total,
        "normalized_confidence": normalized,
        "overall_assessment": parsed.get("overall_assessment", ""),
        "raw_response": raw_text,
    }


def _parse_json(text):
    """Extract JSON from model response."""
    import re
    text = text.strip()
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


def _fallback_result(error_msg, raw_response=""):
    """Return a safe fallback when the judge fails."""
    return {
        "scores": {},
        "rationales": {},
        "total_score": 0,
        "normalized_confidence": 0.0,
        "overall_assessment": f"Judge evaluation failed: {error_msg}",
        "raw_response": raw_response,
        "error": error_msg,
    }
