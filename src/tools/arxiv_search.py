from concurrent.futures import ThreadPoolExecutor, as_completed

def filter_papers(papers, max_papers=10):
    """Filter to top N papers with sufficient summaries."""
    if not papers:
        return []

    filtered = [p for p in papers if len(p.get("summary", "")) > 50]
    filtered = filtered[:max_papers]

    print(f"  Filtered to {len(filtered)} papers (from {len(papers)} total)")
    for i, p in enumerate(filtered, 1):
        print(f"    {i}. {p['title'][:80]}")

    return filtered


def _analyze_one_paper(invention_desc, paper, llm_call_fn):
    """Analyze a single paper for prior art relevance."""
    paper_text = (
        f"URL: {paper.get('url', '')}\n"
        f"Title: {paper.get('title', 'N/A')}\n"
        f"Authors: {paper.get('authors', 'N/A')}\n"
        f"Published: {paper.get('published', 'N/A')}\n"
        f"Summary: {paper.get('summary', 'N/A')[:400]}"
    )

    prompt = f"""Analyze this academic paper's relevance to the invention as prior art.

INVENTION:
{invention_desc}

PAPER:
{paper_text}

Provide:
1. Relevance score (0.0 to 1.0)
2. Classification: "blocking" (very similar, published before), "relevant" (overlapping techniques), or "related" (same domain but different approach)
3. Key similarities to the invention
4. Key differences from the invention
5. Brief analysis (2-3 sentences)

IMPORTANT: Return ONLY a JSON object with no other text.
Keys: "url", "title", "relevance_score", "classification", "similarities", "differences", "analysis"
"""

    result = llm_call_fn(prompt)
    if isinstance(result, list):
        result = result[0] if result else {}
    return result


def analyze_papers(invention_desc, papers, llm_call_fn, max_workers=3):
    """
    Analyze arxiv papers for prior art relevance (concurrent, one LLM call per paper).

    Parameters
    ----------
    invention_desc : str
    papers : list[dict]
    llm_call_fn : callable
    max_workers : int

    Returns
    -------
    list[dict] — one analysis object per paper.
    """
    if not papers:
        return []

    results = []
    max_workers = min(max_workers, len(papers)) or 1

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_idx = {
            ex.submit(_analyze_one_paper, invention_desc, p, llm_call_fn): i
            for i, p in enumerate(papers)
        }
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results.append((idx, fut.result()))
            except Exception as e:
                print(f"  [WARN] Paper analysis failed: {e}")
                results.append((idx, {}))

    # Sort by original order
    results.sort(key=lambda x: x[0])
    analysis = [r for _, r in results if r]

    print(f"  Analyzed {len(analysis)} papers:")
    for a in analysis:
        print(f"    {a.get('title', '')[:60]}: {a.get('classification')} ({a.get('relevance_score')})")

    return analysis
