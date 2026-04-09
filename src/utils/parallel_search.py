from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any


def parallel_scholar_queries(
    patent_searcher,
    queries: List[str],
    max_results_per_query: int = 5,
    max_concurrent: int = 3,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Run SerpAPI Google Scholar searches for multiple queries in parallel.

    Returns a list of (query, results_list) tuples, ordered to match `queries`.
    """
    queries = [q for q in queries if q and q.strip()]
    if not queries:
        return []

    def run_query(q: str):
        try:
            print(f"  [SCHOLAR] {q}")
            results = patent_searcher.search_scholar(q, max_results=max_results_per_query)
            print(f"  [SCHOLAR DONE] {q} -> {len(results)} results")
            return q, results
        except Exception as e:
            print(f"  [SCHOLAR ERROR] query={q!r}: {e}")
            return q, []

    results_by_query: List[Tuple[str, List[Dict[str, Any]]]] = []

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_query = {
            executor.submit(run_query, q): q for q in queries
        }
        for future in as_completed(future_to_query):
            q = future_to_query[future]
            try:
                q_res, res = future.result()
            except Exception as e:
                print(f"  [SCHOLAR FATAL] query={q!r} crashed: {e}")
                q_res, res = q, []
            results_by_query.append((q_res, res))

    order = {q: i for i, q in enumerate(queries)}
    results_by_query.sort(key=lambda qr: order[qr[0]])

    return results_by_query


def parallel_search_queries(
    patent_searcher,
    queries: List[str],
    max_results_per_query: int = 10,
    max_concurrent: int = 3,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Run SerpAPI patent searches for multiple queries in parallel.

    Returns a list of (query, results_list) tuples.
    Results are ordered to match the original `queries` order.
    """
    # Deduplicate empty queries, but keep order
    queries = [q for q in queries if q and q.strip()]
    if not queries:
        return []

    def run_query(q: str):
        # Single-call wrapper so we can catch exceptions cleanly
        try:
            print(f"  [SEARCH] {q}")
            results = patent_searcher.search(q, max_results=max_results_per_query)

            print(f"  [DONE] {q} -> {len(results)} results")
            return q, results
        except Exception as e:
            print(f"  [ERROR] query={q!r}: {e}")
            return q, []

    results_by_query: List[Tuple[str, List[Dict[str, Any]]]] = []

    # Thread pool = good for I/O-bound HTTP calls (SerpAPI)
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_query = {
            executor.submit(run_query, q): q for q in queries
        }

        for future in as_completed(future_to_query):
            q = future_to_query[future]
            try:
                q_res, res = future.result()
            except Exception as e:
                print(f"  [FATAL] query={q!r} crashed: {e}")
                q_res, res = q, []
            results_by_query.append((q_res, res))

    # Reorder to match original query order
    order = {q: i for i, q in enumerate(queries)}
    results_by_query.sort(key=lambda qr: order[qr[0]])

    return results_by_query