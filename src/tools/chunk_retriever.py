# tools/chunk_retriever.py
import re
from typing import List, Dict, Tuple

def get_chunks(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[Dict]:
    """
    Split text into overlapping chunks.
    Returns list of dicts: {id, text, start_char, end_char}
    """
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    i = 0
    cid = 0
    n = len(text)

    while i < n:
        end = min(i + chunk_size, n)
        chunk_text = text[i:end]
        chunks.append({
            "id": f"c{cid}",
            "text": chunk_text,
            "start_char": i,
            "end_char": end
        })
        cid += 1
        if end == n:
            break
        i = max(0, end - overlap)

    return chunks

def _score_chunk_simple(chunk_text: str, query: str) -> int:
    """
    Very simple keyword scoring:
    count of query terms found in chunk.
    """
    q_terms = [t.lower() for t in re.findall(r"[a-zA-Z0-9]+", query) if len(t) > 2]
    c = chunk_text.lower()
    score = 0
    for t in set(q_terms):
        if t in c:
            score += 1
    return score

def retrieve_top_chunks(chunks: List[Dict], query: str, k: int = 6) -> List[Dict]:
    scored = []
    for ch in chunks:
        scored.append(( _score_chunk_simple(ch["text"], query), ch ))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for s, c in scored[:k] if s > 0]
    # fallback: if nothing matches, just return first k chunks
    return top if top else chunks[:k]