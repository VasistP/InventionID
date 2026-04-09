# tools/patentability_classifier.py
"""
Patentability classification tool for the ReAct agent.

Runs as a turn in the existing Claude conversation (uses the cached
document sections for free). Applies a 3-facet rubric (A-C) to
classify the invention as:
  - Scientific Discovery (0-2): not patentable
  - Borderline Case (3-4): needs clarification
  - Potential Invention (5-6): proceed with prior art search

All facet definitions and thresholds are configurable via
patentability_config.json.
"""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "patentability_config_Prayoga_v2.json")


def load_config(config_path=None):
    path = config_path or _CONFIG_PATH
    with open(path, "r") as f:
        return json.load(f)


def build_patentability_prompt(invention_json, config=None):
    """
    Build the patentability classification prompt from config.

    This prompt is designed to be sent as a user turn in the existing
    Claude conversation where the document sections are already cached.
    """
    if config is None:
        config = load_config()

    facets = config["facets"]
    thresholds = config["classification_thresholds"]
    guardrails = config.get("guardrails", {})

    # Build rubric section
    rubric_lines = []
    for fid in sorted(facets.keys()):
        facet = facets[fid]
        rubric_lines.append(f"Facet {fid} — {facet['name']}")
        rubric_lines.append(f"  Goal: {facet['description']}")
        for score, meaning in facet["scoring"].items():
            rubric_lines.append(f"  Score {score}: {meaning}")
        rubric_lines.append("")

    rubric_text = "\n".join(rubric_lines)

    # Build guardrails section
    guardrail_lines = []
    if guardrails.get("facet_a_zero_stops"):
        guardrail_lines.append(
            "- If Facet A score = 0, classify as 'Scientific Discovery' immediately."
        )
    if guardrails.get("facet_b_zero_stops"):
        guardrail_lines.append(
            "- If Facet B score = 0, classify as 'Scientific Discovery' immediately."
        )
    guardrail_lines.append(
        "- Use evidence primarily from Methods, Design, and Results sections "
        "— avoid relying only on Abstracts or Introductions."
    )
    guardrail_text = "\n".join(guardrail_lines)

    # Build classification rules
    class_lines = []
    for cls_name, bounds in thresholds.items():
        label = cls_name.replace("_", " ").title()
        class_lines.append(f"  - {bounds['min']}-{bounds['max']}: \"{label}\"")
    class_text = "\n".join(class_lines)

    # Clean invention for display (strip internal fields)
    clean = {k: v for k, v in invention_json.items() if not k.startswith("_")}

    return (
        "ACTION: CLASSIFY_PATENTABILITY\n\n"
        "Using the DOCUMENT SECTIONS cached above and the invention extraction "
        "below, evaluate whether this work qualifies as a patentable invention.\n\n"
        f"INVENTION EXTRACTION:\n{json.dumps(clean, indent=2)}\n\n"
        "SCORING RUBRIC:\n"
        f"{rubric_text}\n"
        "GUARDRAILS:\n"
        f"{guardrail_text}\n\n"
        "CLASSIFICATION RULES (based on total_score = A + B + C):\n"
        f"{class_text}\n\n"
        "INSTRUCTIONS:\n"
        "1. Re-read the relevant document sections (Methods, Results, Design).\n"
        "2. Score each facet (A, B, C) with evidence quotes from the document.\n"
        "3. Apply guardrails before computing total.\n"
        "4. Return ONLY a JSON object with this structure:\n"
        "{\n"
        '  "facets": [\n'
        '    {"facet_id": "A", "facet_name": "...", "score": 0, '
        '"evidence_quote": "...", "reasoning": "..."},\n'
        '    {"facet_id": "B", "facet_name": "...", "score": 0, '
        '"evidence_quote": "...", "reasoning": "..."},\n'
        '    {"facet_id": "C", "facet_name": "...", "score": 0, '
        '"evidence_quote": "...", "reasoning": "..."}\n'
        "  ],\n"
        '  "total_score": 0,\n'
        '  "classification": "Scientific Discovery | Borderline Case | Potential Invention",\n'
        '  "justification": "1-2 sentence summary",\n'
        '  "recommendation": "recommended next action"\n'
        "}\n\n"
        "RULES:\n"
        "- Return ONLY valid JSON, no markdown fences, no extra text.\n"
        "- Quote SHORT passages from the document with section IDs as evidence.\n"
        "- Be objective. A score of 2 means genuinely clear, not just mentioned.\n"
    )


def validate_classification(parsed, config=None):
    """
    Validate and normalize a patentability classification result.
    Recomputes total_score and classification from individual facet scores
    (doesn't trust the model's arithmetic).

    Returns (normalized_result, errors).
    """
    if config is None:
        config = load_config()

    errors = []

    if not isinstance(parsed, dict):
        return None, ["Response is not a JSON object"]

    facets_list = parsed.get("facets", [])
    if not isinstance(facets_list, list) or len(facets_list) == 0:
        errors.append("Missing or empty 'facets' array")
        return parsed, errors

    thresholds = config["classification_thresholds"]
    guardrails = config.get("guardrails", {})

    # Validate and clamp facet scores
    facet_scores = {}
    for facet in facets_list:
        fid = facet.get("facet_id", "")
        score = facet.get("score", 0)
        score = max(0, min(int(score), 2))
        facet["score"] = score
        facet_scores[fid] = score

        if not facet.get("evidence_quote"):
            errors.append(f"Facet {fid} missing evidence_quote")
        if not facet.get("reasoning"):
            errors.append(f"Facet {fid} missing reasoning")

    # Apply guardrails
    early_stop = False
    if guardrails.get("facet_a_zero_stops") and facet_scores.get("A", 0) == 0:
        early_stop = True
    if guardrails.get("facet_b_zero_stops") and facet_scores.get("B", 0) == 0:
        early_stop = True

    # Recompute total
    total = sum(facet_scores.values())
    parsed["total_score"] = total

    # Recompute classification
    if early_stop:
        parsed["classification"] = "Scientific Discovery"
    elif total <= thresholds["scientific_discovery"]["max"]:
        parsed["classification"] = "Scientific Discovery"
    elif total <= thresholds["borderline_case"]["max"]:
        parsed["classification"] = "Borderline Case"
    else:
        parsed["classification"] = "Potential Invention"

    return parsed, errors
