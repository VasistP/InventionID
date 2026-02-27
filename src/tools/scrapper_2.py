import re
import time
import requests
import json
from typing import Optional, Dict, Any, Tuple
from urllib.parse import unquote
from bs4 import BeautifulSoup


DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", re.IGNORECASE)


def _clean_doi(candidate: str) -> Optional[str]:
    """Normalize a DOI candidate and strip trailing punctuation artifacts."""
    if not candidate:
        return None
    # print(candidate)
    doi = candidate.strip().strip("<>")
    doi = doi.rstrip(".,;:)]}\"'")

    match = DOI_PATTERN.search(doi)
    print("match:",match)
    if not match:
        return None
    return match.group(0).lower()


def extract_doi(url: str, html: Optional[str] = None) -> Optional[str]:
    """
    Extract DOI from URL first, then optional HTML content (meta tags and raw text).
    Returns normalized DOI string or None.
    """
    # 1) URL-based extraction (most reliable for publisher links).
    decoded_url = unquote(url or "")
    doi = _clean_doi(decoded_url)
    if doi:
        return doi

    if not html:
        return None

    # 2) Meta-tag extraction for publisher pages.
    soup = BeautifulSoup(html, "lxml")
    meta_keys = {
        "citation_doi",
        "dc.identifier",
        "dc.identifier.doi",
        "dc.source",
        "prism.doi",
        "bepress_citation_doi",
    }
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").strip().lower()
        content = (tag.get("content") or "").strip()
        if key in meta_keys and content:
            doi = _clean_doi(content)
            if doi:
                return doi

    # 3) Fallback: scan full HTML text for DOI pattern.
    doi = _clean_doi(html)
    return doi


def extract_abstract(html: str) -> Optional[str]:
    """Extract abstract from common metadata layouts."""
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    def _norm(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    # 1) Metadata description tags
    meta_keys = {"citation_abstract", "dc.description", "description", "og:description"}
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").strip().lower()
        content = _norm(tag.get("content") or "")
        if key in meta_keys and len(content) > 40:
            return content

    # 2) <dt>Abstract</dt><dd>...</dd> layout (your IDEALS sample)
    for dt in soup.find_all("dt"):
        if _norm(dt.get_text()).lower() == "abstract":
            dd = dt.find_next_sibling("dd")
            if dd:
                text = _norm(dd.get_text(" ", strip=True))
                if len(text) > 40:
                    return text

    # 3) Generic abstract containers
    for node in soup.select('[id*="abstract" i], [class*="abstract" i]'):
        text = _norm(node.get_text(" ", strip=True))
        text = re.sub(r"^abstract\s*[:\-]?\s*", "", text, flags=re.IGNORECASE)
        if len(text) > 60:
            return text

    # 4) JSON-LD fallback
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            stack = data if isinstance(data, list) else [data]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    for key in ("abstract", "description"):
                        value = _norm(item.get(key) or "")
                        if len(value) > 40:
                            return value
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)
        except Exception:
            continue

    return None



def _fetch_abstract_crossref(doi: str) -> Optional[str]:
    """Fetch abstract from Crossref API using DOI."""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        r = requests.get(url, timeout=15)
        if not r.ok:
            return None
        data = r.json()
        abstract = (data.get("message") or {}).get("abstract") or ""
        abstract = abstract.strip()
        if not abstract:
            return None
        # Crossref abstracts often contain JATS XML tags — strip them.
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()
        return abstract if len(abstract) > 40 else None
    except requests.RequestException:
        return None


def _fetch_abstract_ss_by_title(title: str) -> Optional[str]:
    """Search Semantic Scholar by title and return the top result's abstract."""
    if not title:
        return None
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {"query": title, "fields": "title,abstract", "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=15)
        if not r.ok:
            return None
        data = r.json()
        results = data.get("data") or []
        if not results:
            return None
        abstract = (results[0].get("abstract") or "").strip()
        return abstract if len(abstract) > 40 else None
    except requests.RequestException:
        return None


def test_scrape(url, title: Optional[str] = None):
    print("=" * 60)
    print(f"Testing URL: {url}")
    print("=" * 60)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "Chrome/120.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )
    except requests.RequestException as e:
        print(f"🚫 Request failed: {e}")
        return

    print("\n---- REQUEST STATUS ----")
    print("Status Code :", response.status_code)
    doi = extract_doi(response.url, response.text)
    print("DOI         :", doi)

    html_doc = response.text.lower()

    # ---- BLOCK DETECTION ----
    if "access denied" in html_doc:
        print("🚫 BLOCKED: Access Denied page")
        return

    if "captcha" in html_doc:
        print("🚫 BLOCKED: CAPTCHA detected")
        return

    if "institutional login" in html_doc:
        print("🚫 PAYWALL / LOGIN WALL")
        return
    
    abstract = extract_abstract(response.text)

    if response.status_code ==200:
        soup = BeautifulSoup(response.text, "lxml")
        print("Page Title:",
            soup.title.get_text(strip=True)
            if soup.title else "None")

        if abstract:
            print("✅ Abstract extracted")
            print(f"Abstract Len: {len(abstract)}")
            # print("Abstract    :", abstract)
        else:
            print("⚠️ Abstract not found in page HTML")

    # Fallback chain: Crossref (by DOI) → Semantic Scholar (by title)
    if response.status_code != 200 or not abstract:
        fallback_abstract = None

        # 1) Crossref — requires DOI
        if doi:
            fallback_abstract = _fetch_abstract_crossref(doi)
            if fallback_abstract:
                print("✅ Abstract extracted from Crossref")
                print(f"Abstract Len: {len(fallback_abstract)}")

        # 2) Semantic Scholar — search by provided title
        if not fallback_abstract:
            fallback_abstract = _fetch_abstract_ss_by_title(title)
            if fallback_abstract:
                print("✅ Abstract extracted from Semantic Scholar (title search)")
                print(f"Abstract Len: {len(fallback_abstract)}")

        if not fallback_abstract:
            print("⚠️ Abstract not found via any fallback")



if __name__ == "__main__":
    test_url = ['https://pubs.acs.org/doi/abs/10.1021/acsomega.4c03017', 'https://www.sciencedirect.com/science/article/pii/S2214860422005711', 
                'https://advanced.onlinelibrary.wiley.com/doi/abs/10.1002/adma.202515033','https://onlinelibrary.wiley.com/doi/abs/10.1002/smtd.202301569',
                'https://www.sciencedirect.com/science/article/pii/S1526612521007362','https://www.ideals.illinois.edu/items/127751','https://www.mdpi.com/2073-4360/17/5/680','https://par.nsf.gov/servlets/purl/10429500']
    # test_url = ['https://www.ideals.illinois.edu/items/127751']
    
    for i in test_url:
        print(i)
        test_scrape(i)
        print()
