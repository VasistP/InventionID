#!/usr/bin/env python3
"""
Sub-chunker for Textract section output.

Splits section-level dicts into retrieval-sized chunks (400–1200 tokens,
default target 800) with configurable overlap.  Produces deterministic,
stable chunk IDs suitable for embedding and retrieval pipelines.

Usage as CLI:
    python3 -m src.subchunker --input textract_sections.json --output subchunks.json

Usage as library:
    from src.subchunker import subchunk_sections
    chunks = subchunk_sections(sections)
"""

import json
import os
import re
import sys
import argparse
from math import ceil

# ---------------------------------------------------------------------------
# Debug toggle
# ---------------------------------------------------------------------------
DEBUG_CHUNKING = os.environ.get("DEBUG_CHUNKING", "0") == "1"

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Approximate token count using a whitespace-aware heuristic.

    Heuristic: count whitespace-delimited words, then multiply by 1.35
    to account for sub-word tokenisation (most BPE tokenisers split ~25-30 %
    of English words into multiple tokens).  Falls back to ceil(len/4) when
    text has very few spaces (e.g. CJK or URLs).

    This is intentionally lightweight – no external tokeniser required.
    """
    words = text.split()
    if len(words) < 2:
        return max(1, ceil(len(text) / 4))
    return max(1, ceil(len(words) * 1.35))


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\n([a-z])")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def _normalise_text(text: str) -> str:
    """Clean up common PDF artefacts before splitting."""
    # Fix hyphenated line breaks: "frame-\nwork" → "framework"
    text = _HYPHEN_LINEBREAK_RE.sub(r"\1\2", text)
    # Collapse excessive blank lines
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Splitting helpers
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(
    r"(?<=[.!?])"          # lookbehind: sentence-ending punctuation
    r"(?:\s+)"             # whitespace between sentences
    r"(?=[A-Z\d\[\(\"'])"  # lookahead: next sentence starts with upper/digit/bracket/quote
)


def _split_paragraphs(text: str) -> list[str]:
    """Split on double-newlines (paragraph boundaries)."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences using a lightweight regex tokeniser."""
    sents = _SENTENCE_RE.split(text)
    return [s.strip() for s in sents if s.strip()]


def _split_words(text: str, max_tokens: int) -> list[str]:
    """Last-resort word-count fallback: split text into pieces of ≤ max_tokens."""
    words = text.split()
    pieces: list[str] = []
    buf: list[str] = []
    for w in words:
        buf.append(w)
        if estimate_tokens(" ".join(buf)) >= max_tokens:
            pieces.append(" ".join(buf))
            buf = []
    if buf:
        pieces.append(" ".join(buf))
    return pieces


# ---------------------------------------------------------------------------
# Core: build atomic units then assemble windows
# ---------------------------------------------------------------------------

def _build_atoms(text: str, max_tokens: int) -> list[str]:
    """Break *text* into the smallest reasonable pieces (atoms).

    Priority:
      1. paragraph breaks
      2. sentence breaks (within oversized paragraphs)
      3. word-level fallback (within oversized sentences)

    Every returned atom is ≤ max_tokens (best effort).
    """
    paragraphs = _split_paragraphs(text)
    atoms: list[str] = []

    for para in paragraphs:
        if estimate_tokens(para) <= max_tokens:
            atoms.append(para)
            continue
        # Paragraph too large → split into sentences
        sentences = _split_sentences(para)
        for sent in sentences:
            if estimate_tokens(sent) <= max_tokens:
                atoms.append(sent)
            else:
                # Sentence too large → word fallback
                atoms.extend(_split_words(sent, max_tokens))

    return atoms


def _assemble_chunks(
    atoms: list[str],
    target_tokens: int,
    overlap_tokens: int,
    min_tokens: int,
    max_tokens: int,
) -> list[str]:
    """Greedily assemble *atoms* into overlapping chunk windows.

    Each chunk accumulates atoms up to *target_tokens*.  The next chunk starts
    by rewinding *overlap_tokens* worth of atoms from the end of the previous
    chunk so that consecutive chunks share context.
    """
    if not atoms:
        return []

    chunks: list[str] = []
    i = 0
    n = len(atoms)

    while i < n:
        buf: list[str] = []
        buf_tokens = 0
        j = i

        # Fill the current chunk up to target (allow up to max)
        while j < n:
            atom_tok = estimate_tokens(atoms[j])
            # If adding this atom would exceed max and we already have content, stop
            if buf and (buf_tokens + atom_tok) > max_tokens:
                break
            buf.append(atoms[j])
            buf_tokens += atom_tok
            j += 1

        chunk_text = "\n\n".join(buf)
        if chunk_text.strip():
            chunks.append(chunk_text)

        if j >= n:
            break

        # Compute overlap: rewind from j so the next chunk starts with some
        # atoms from the tail of the current one.
        overlap_acc = 0
        rewind = j
        while rewind > i and overlap_acc < overlap_tokens:
            rewind -= 1
            overlap_acc += estimate_tokens(atoms[rewind])

        i = max(rewind, i + 1)  # always advance at least one atom

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def subchunk_sections(
    sections: list[dict],
    target_tokens: int = 800,
    overlap_tokens: int = 100,
    min_tokens: int = 400,
    max_tokens: int = 1200,
) -> list[dict]:
    """Split a list of section dicts into retrieval-sized sub-chunks.

    Parameters
    ----------
    sections : list[dict]
        Each dict must contain at least ``section_id``, ``title``, ``text``.
    target_tokens, overlap_tokens, min_tokens, max_tokens :
        Chunking parameters (in estimated tokens).

    Returns
    -------
    list[dict]
        Chunk dicts with keys: id, section_id, section_title, text,
        chunk_index_in_section, global_chunk_index.
    """
    all_chunks: list[dict] = []
    global_idx = 0

    for sec in sections:
        section_id = sec.get("section_id", "s00")
        section_title = sec.get("title", "")
        raw_text = sec.get("text", "")

        text = _normalise_text(raw_text)

        # Short section → single chunk
        if estimate_tokens(text) <= min_tokens:
            all_chunks.append({
                "id": f"c{global_idx + 1:04d}",
                "section_id": section_id,
                "section_title": section_title,
                "text": text,
                "chunk_index_in_section": 0,
                "global_chunk_index": global_idx,
            })
            global_idx += 1
            if DEBUG_CHUNKING:
                print(
                    f"  [{section_id}] {section_title!r} → 1 chunk "
                    f"(~{estimate_tokens(text)} tok, short-circuit)"
                )
            continue

        atoms = _build_atoms(text, max_tokens)
        chunk_texts = _assemble_chunks(
            atoms, target_tokens, overlap_tokens, min_tokens, max_tokens
        )

        for ci, ct in enumerate(chunk_texts):
            all_chunks.append({
                "id": f"c{global_idx + 1:04d}",
                "section_id": section_id,
                "section_title": section_title,
                "text": ct,
                "chunk_index_in_section": ci,
                "global_chunk_index": global_idx,
            })
            global_idx += 1

        if DEBUG_CHUNKING:
            tok_info = ", ".join(
                str(estimate_tokens(ct)) for ct in chunk_texts
            )
            print(
                f"  [{section_id}] {section_title!r} → {len(chunk_texts)} chunk(s) "
                f"(tok: {tok_info})"
            )

    return all_chunks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sub-chunk Textract sections into retrieval-sized pieces."
    )
    parser.add_argument(
        "--input", required=True, help="Path to sections JSON list"
    )
    parser.add_argument(
        "--output", default="subchunks.json", help="Path to write chunks JSON"
    )
    parser.add_argument("--target", type=int, default=800, help="Target tokens per chunk")
    parser.add_argument("--overlap", type=int, default=100, help="Overlap tokens")
    parser.add_argument("--min-tokens", type=int, default=400, help="Min tokens per chunk")
    parser.add_argument("--max-tokens", type=int, default=1200, help="Max tokens per chunk")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        sections = json.load(f)

    chunks = subchunk_sections(
        sections,
        target_tokens=args.target,
        overlap_tokens=args.overlap,
        min_tokens=args.min_tokens,
        max_tokens=args.max_tokens,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(chunks)} chunks to {args.output}")


if __name__ == "__main__":
    main()