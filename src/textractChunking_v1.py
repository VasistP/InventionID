#!/usr/bin/env python3
"""
Test Textract Layout Feature
Usage: python test_textract_layout.py <s3_bucket> <s3_key>
"""

import json
import os
import sys
import re
from textractor import Textractor
from textractor.data.constants import TextractFeatures

# DEBUG: set DEBUG_FILTER=1 to print rejected headings and why
DEBUG_FILTER = os.environ.get("DEBUG_FILTER", "0") == "1"

# Keep-list (normalized, case-insensitive)
_ALLOWLIST = {
    "abstract",
    "introduction",
    "related work",
    "related works",
    "background",
    "methods",
    "methodology",
    "approach",
    "experiments",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "bibliography",
    "appendix",
    "appendices",
}

# Reject obvious caption-ish headers
_REJECT_PREFIXES = ("figure", "table", "step", "reason", "turn", "round")

# Matches: "1 Introduction", "2 Related Works", "3.1 Ablation", "1. Introduction"
_NUMBERED_RE = re.compile(r"^\d+(\.\d+)*\.?\s+[A-Za-z]")

def _normalize_heading(s: str) -> str:
    s = (s or "").strip().lower()
    # punctuation -> space, keep letters/digits/underscore
    s = re.sub(r"[^\w\s]", " ", s)
    s = s.replace("_", " ")
    s = " ".join(s.split())
    return s

def is_top_level_heading(title: str):
    """
    Returns (keep: bool, reason: str)
    """
    raw = (title or "").strip()
    if not raw:
        return False, "empty"

    norm = _normalize_heading(raw)

    # too short
    if len(norm) < 4:
        return False, "too_short"

    # reject prefixes like "figure", "step", etc.
    first = norm.split()[0] if norm.split() else ""
    if first in _REJECT_PREFIXES:
        return False, f"reject_prefix:{first}"

    # mostly non-letters heuristic
    letters = sum(1 for c in raw if c.isalpha())
    non_space = sum(1 for c in raw if not c.isspace())
    letters_ratio = (letters / non_space) if non_space else 0.0
    if letters_ratio < 0.4:
        return False, "mostly_non_letters"

    # keep allowlist
    if norm in _ALLOWLIST:
        return True, "allowlist"

    # keep numbered top-level sections
    if _NUMBERED_RE.match(raw):
        return True, "numbered"

    return False, "not_top_level"

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
TOP_LEVEL_NUM_RE = re.compile(r"^\s*\d+\s*[\.)]?\s+[A-Za-z]")

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

# def extract_text_from_s3_by_sections(bucket, key):
#     """Extract text grouped by section headers using Textractor"""
#     extractor = Textractor(profile_name="default")
#     s3_path = f"s3://{bucket}/{key}"
    
#     document = extractor.start_document_analysis(
#         file_source=s3_path,
#         features=[TextractFeatures.LAYOUT],
#         save_image=False
#     )
    
#     chunks = {}
#     chunk_counter = 0
    
#     for page_num, page in enumerate(document.pages, 1):
#         # Collect section headers with their positions
#         headers = []
#         if hasattr(page, 'page_layout') and page.page_layout.section_headers:
#             for header in page.page_layout.section_headers:
#                 headers.append({
#                     'text': header.text.strip(),
#                     'y': header.bbox.y,
#                     'x': header.bbox.x
#                 })
        
#         # Add titles as headers too
#         if hasattr(page, 'page_layout') and page.page_layout.titles:
#             for title in page.page_layout.titles:
#                 headers.append({
#                     'text': title.text.strip(),
#                     'y': title.bbox.y,
#                     'x': title.bbox.x
#                 })
        
#         # Sort headers by position (top to bottom)
#         headers.sort(key=lambda x: (x['y'], x['x']))
        
#         # Get all text lines from the page
#         if not hasattr(page, 'lines') or not page.lines:
#             continue
            
#         # Group lines under headers
#         if headers:
#             for i, header in enumerate(headers):
#                 # Determine the range for this section
#                 start_y = header['y']
#                 end_y = headers[i + 1]['y'] if i + 1 < len(headers) else float('inf')
                
#                 # Collect lines that fall within this section
#                 section_lines = []
#                 for line in page.lines:
#                     line_y = line.bbox.y
#                     # Skip the header line itself and get text below it
#                     if line_y > start_y and line_y < end_y:
#                         section_lines.append(line.text.strip())
                
#                 if section_lines:
#                     chunk_counter += 1
#                     chunks[f"chunk{chunk_counter}"] = {
#                         header['text']: "\n".join(section_lines)
#                     }
#         else:
#             # No headers found, just use all text
#             all_text = "\n".join([line.text.strip() for line in page.lines])
#             if all_text:
#                 chunk_counter += 1
#                 chunks[f"chunk{chunk_counter}"] = {
#                     f"Page {page_num}": all_text
#                 }
    
#     return chunks

def extract_text_from_s3_by_sections(bucket, key, include_titles=False):
    """Extract text grouped by MAJOR section headers using Textractor Layout."""
    extractor = Textractor(profile_name="default")
    s3_path = f"s3://{bucket}/{key}"

    document = extractor.start_document_analysis(
        file_source=s3_path,
        features=[TextractFeatures.LAYOUT],
        save_image=False
    )

    chunks = {}
    chunk_counter = 0

    current_chunk_key = None
    current_title = None

    for page_num, page in enumerate(document.pages, 1):
        if not hasattr(page, "lines") or not page.lines:
            continue

        # Collect section headers with their positions
        headers = []
        if hasattr(page, 'page_layout') and page.page_layout.section_headers:
            for header in page.page_layout.section_headers:
                text = header.text.strip()
                keep, reason = is_top_level_heading(text)
                if keep:
                    headers.append({
                        'text': text,
                        'y': header.bbox.y,
                        'x': header.bbox.x
                    })
                elif DEBUG_FILTER:
                    print(f"[filter] page={page_num} reject={reason} text={text!r}")

        # Add titles as headers too (filtered)
        if hasattr(page, 'page_layout') and page.page_layout.titles:
            for title in page.page_layout.titles:
                text = title.text.strip()
                keep, reason = is_top_level_heading(text)
                if keep:
                    headers.append({
                        'text': text,
                        'y': title.bbox.y,
                        'x': title.bbox.x
                    })
                elif DEBUG_FILTER:
                    print(f"[filter] page={page_num} reject={reason} text={text!r}")


        headers.sort(key=lambda x: (x["y"], x["x"]))

        # Helper: append lines to the current chunk
        def _append_to_current(lines):
            nonlocal chunks, current_chunk_key, current_title
            if not lines:
                return
            if current_chunk_key and current_title and current_chunk_key in chunks:
                chunks[current_chunk_key][current_title] += "\n" + "\n".join(lines)

        if headers:
            # If there is content above the first header, treat it as continuation
            first_y = headers[0]["y"]
            carry = [ln.text.strip() for ln in page.lines if ln.bbox.y < first_y]
            _append_to_current([x for x in carry if x])

            for i, h in enumerate(headers):
                start_y = h["y"]
                end_y = headers[i + 1]["y"] if i + 1 < len(headers) else float("inf")

                section_lines = []
                for ln in page.lines:
                    ly = ln.bbox.y
                    if ly > start_y and ly < end_y:
                        s = ln.text.strip()
                        if s:
                            section_lines.append(s)

                if not section_lines:
                    continue

                # If the same major header repeats on a new page, append instead of new chunk
                if current_title == h["text"] and current_chunk_key:
                    _append_to_current(section_lines)
                    continue

                chunk_counter += 1
                current_chunk_key = f"chunk{chunk_counter}"
                current_title = h["text"]
                chunks[current_chunk_key] = {current_title: "\n".join(section_lines)}

        else:
            # No headers on this page -> append the whole page to current section
            page_text = [ln.text.strip() for ln in page.lines if ln.text and ln.text.strip()]
            if page_text:
                if current_chunk_key:
                    _append_to_current(page_text)
                else:
                    chunk_counter += 1
                    current_chunk_key = f"chunk{chunk_counter}"
                    current_title = f"Page {page_num}"
                    chunks[current_chunk_key] = {current_title: "\n".join(page_text)}

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
