#!/usr/bin/env python3
"""
Test Textract Layout Feature
Usage: python test_textract_layout.py <s3_bucket> <s3_key>
"""

import json
import os
import sys
import re
import boto3
import time

MAJOR_SECTIONS = {
    "abstract", "introduction", "related work", "related works", "background",
    "methods", "method", "methodology", "approach", "materials and methods",
    "experiments", "experimental setup", "evaluation",
    "results", "discussion", "conclusion", "conclusions",
    "limitations", "future work",
    "acknowledgements", "acknowledgments",
    "references", "bibliography",
    "appendix", "supplementary material", "supplementary"
}

# Matches "1 Introduction" or "1. Introduction" (but NOT "3.1 Something")
# TOP_LEVEL_NUM_RE = re.compile(r"^\s*\d+\s*[\.)]?\s+[A-Za-z]")
TOP_LEVEL_NUM_RE = re.compile(
    r"^\s*(?:\d+|[IVXLCDM]+)\s*[\.)]?\s+[A-Za-z]",
    re.IGNORECASE
)

def is_major_section_header(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False

    tl = t.lower()

    # Reject common non-section labels
    if tl.startswith(("figure", "table", "step ")):   # filters "Step 4. ..." too
        return False
    if tl in {"reason"}:
        return False

    # Normalize: strip leading top-level numbering ("1 ", "1.", "2)")
    norm = re.sub(r"^\s*\d+\s*[\.)]?\s*", "", tl).strip()
    norm = re.sub(r"\s+", " ", norm)

    # Keep: known major unnumbered headings OR top-level numbered headings
    return (norm in MAJOR_SECTIONS) or bool(TOP_LEVEL_NUM_RE.match(t))

def normalize_textract_chunks(chunks: dict,
                              min_text_len: int = 40,
                              min_alnum_ratio: float = 0.25) -> list:
    """
    Collapse your section_normalizer.py into one function:
    - numeric sort chunk keys
    - drop empty / too-short / low-alnum
    - normalize line breaks
    - output list[{section_id,title,text,source_chunk_key}]
    """
    def chunk_num(k: str) -> int:
        m = re.search(r"\d+", k or "")
        return int(m.group()) if m else 0

    sections = []
    sid = 1

    for ck in sorted(chunks.keys(), key=chunk_num):
        cd = chunks.get(ck) or {}
        if len(cd) != 1:
            continue

        title, text = next(iter(cd.items()))
        title = (title or "").strip()
        text = (text or "").strip()

        # Normalize line breaks early
        text = text.replace("\r\n", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Garbage filters
        if not title or not text or len(text) < min_text_len:
            continue

        alnum = sum(ch.isalnum() for ch in text)
        if alnum / max(1, len(text)) < min_alnum_ratio:
            continue

        sections.append({
            "section_id": f"s{sid:02d}",
            "title": title,
            "text": text,
            "source_chunk_key": ck
        })
        sid += 1

    return sections

def extract_text_from_s3_by_sections(bucket, key, include_titles=False):
    """Extract text grouped by MAJOR section headers using Textract Layout."""
    textract_client = boto3.client('textract')

    print(f"  Starting Textract (layout analysis)...")
    response = textract_client.start_document_analysis(
        DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}},
        FeatureTypes=['LAYOUT']
    )
    job_id = response['JobId']

    # Collect all blocks across paginated results
    all_blocks = []
    next_token = None
    while True:
        params = {'JobId': job_id}
        if next_token:
            params['NextToken'] = next_token
        result = textract_client.get_document_analysis(**params)
        if result['JobStatus'] == 'FAILED':
            return None
        if result['JobStatus'] == 'SUCCEEDED':
            all_blocks.extend(result.get('Blocks', []))
            next_token = result.get('NextToken')
            if not next_token:
                break
        else:
            time.sleep(3)

    block_map = {b['Id']: b for b in all_blocks}

    def _get_child_text(block):
        child_ids = [cid for r in block.get('Relationships', []) if r['Type'] == 'CHILD' for cid in r['Ids']]
        lines = []
        for cid in child_ids:
            child = block_map.get(cid, {})
            if child.get('BlockType') == 'LINE' and 'Text' in child:
                lines.append(child['Text'])
        return "\n".join(lines)

    # Build sections from layout blocks (respects column reading order)
    chunks = {}
    chunk_counter = 0
    current_chunk_key = None
    current_title = None

    def _append_text(text):
        nonlocal chunks, current_chunk_key, current_title
        if not text:
            return
        if current_chunk_key and current_title and current_chunk_key in chunks:
            chunks[current_chunk_key][current_title] += "\n" + text

    layout_blocks = [b for b in all_blocks if b['BlockType'] in ('LAYOUT_SECTION_HEADER', 'LAYOUT_TITLE', 'LAYOUT_TEXT')]

    for b in layout_blocks:
        text = _get_child_text(b)
        if not text.strip():
            continue

        if b['BlockType'] == 'LAYOUT_SECTION_HEADER' and is_major_section_header(text):
            if current_title == text.strip() and current_chunk_key:
                continue
            chunk_counter += 1
            current_chunk_key = f"chunk{chunk_counter}"
            current_title = text.strip()
            chunks[current_chunk_key] = {current_title: ""}
        elif b['BlockType'] == 'LAYOUT_TITLE' and include_titles:
            chunk_counter += 1
            current_chunk_key = f"chunk{chunk_counter}"
            current_title = text.strip()
            chunks[current_chunk_key] = {current_title: ""}
        else:
            if current_chunk_key:
                _append_text(text)
            else:
                chunk_counter += 1
                current_chunk_key = f"chunk{chunk_counter}"
                current_title = f"Page 1"
                chunks[current_chunk_key] = {current_title: text}

    return chunks


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_textract_layout.py <bucket> <key>")
        print("Example: python3 src/textractChunking.py patent-pdf-input-786827631714 'input/Kim et al. - 2024 - MDAgents An Adaptive Collaboration of LLMs for Medical Decision-Making.pdf'")
        sys.exit(1)
    
    bucket = sys.argv[1]
    key = sys.argv[2]
    
    chunks = extract_text_from_s3_by_sections(bucket, key)
    sections = normalize_textract_chunks(chunks)
    out_path = os.environ.get("OUT_JSON", "textract_sections.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sections, f, indent=2, ensure_ascii=False)

    print(f"Wrote normalized sections JSON to: {out_path}")

    # --- Optional: produce sub-chunks for retrieval ---
    # if os.environ.get("WRITE_SUBCHUNKS", "0") == "1":
    from subchunker import subchunk_sections

    subchunks = subchunk_sections(sections)
    sub_path = os.environ.get("OUT_SUBCHUNKS_JSON", "textract_subchunks.json")
    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(subchunks, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(subchunks)} sub-chunks to: {sub_path}")