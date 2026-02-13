from typing import Dict, List, Any
import re
def extract_evidence(invention: Dict[str, Any], chunks: List[Dict]) -> Dict[str, Any]:
    """
    Evidence output:
    - checks cited chunk ids exist
    - returns snippets (so you can SEE where it came from)
    """

    cited = invention.get("citations", {})
    chunk_map = {c["id"]: c["text"] for c in chunks}
    chunk_ids = set(chunk_map.keys())

    missing = {}
    evidence_snippets = {}

    total_fields = 0
    ok_fields = 0

    if isinstance(cited, dict):
        for field, ids in cited.items():
            total_fields += 1
            if not isinstance(ids, list):
                missing[field] = ["(citations not a list)"]
                continue

            bad = [x for x in ids if x not in chunk_ids]
            if bad:
                missing[field] = bad
                continue

            ok_fields += 1
            evidence_snippets[field] = []
            for cid in ids:
                txt = chunk_map.get(cid, "")
                evidence_snippets[field].append({
                    "chunk_id": cid,
                    "snippet": txt[:350]  # first 350 chars
                })

    used_chunk_ids = []
    if isinstance(cited, dict):
        for ids in cited.values():
            if isinstance(ids, list):
                used_chunk_ids.extend(ids)

    # keep order, remove duplicates
    seen = set()
    unique_used = []
    for cid in used_chunk_ids:
        if cid not in seen:
            seen.add(cid)
            unique_used.append(cid)

    def _clean_snippet(txt: str, limit: int = 280) -> str:
        # make whitespace clean
        txt = re.sub(r"\s+", " ", (txt or "").strip())

        # if chunk starts mid-word (like "ounds"), show "…"
        if txt and txt[0].islower():
            txt = "…" + txt

        return txt[:limit]

    chunk_snippets = {}
    for cid in unique_used:
        txt = chunk_map.get(cid, "")
        chunk_snippets[cid] = _clean_snippet(txt, limit=280)

    return {
        "has_citations": isinstance(cited, dict) and len(cited) > 0,
        "missing_chunk_ids": missing,

        # keep citations as a simple dict
        "field_refs": cited if isinstance(cited, dict) else {},

        # store snippets ONCE per chunk id
        "chunk_snippets": chunk_snippets
    }