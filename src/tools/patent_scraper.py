"""
Google Patents full-text scraper.

Fetches the full abstract and first claim from a patents.google.com page.
Used by Stage 4 to enrich the patent dicts before Stage 4b re-ranks them
by full-text cosine similarity.
"""
import re
import requests
from bs4 import BeautifulSoup


def fetch_patent_full_text(url: str) -> dict:
    """
    Scrape a Google Patents page and return the full abstract and claim 1.

    Returns {"abstract": str, "claim_1": str}; both values are empty strings
    on any failure so callers can safely use .get() with a fallback.
    """
    result = {"abstract": "", "claim_1": ""}
    if not url or "patents.google.com" not in url:
        return result

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        if not r.ok:
            return result

        soup = BeautifulSoup(r.text, "html.parser")

        def _clean(text: str) -> str:
            return re.sub(r"\s+", " ", text or "").strip()

        # ── Full abstract ──────────────────────────────────────────────────
        # Google Patents uses itemprop="abstract" on a <section> wrapping the text.
        # Fallback order: itemprop section → div.abstract → bare <abstract> element.
        for selector in [
            {"name": "section", "attrs": {"itemprop": "abstract"}},
            {"name": "div",     "attrs": {"class": "abstract"}},
            {"name": "abstract"},
        ]:
            node = soup.find(**selector)
            if node:
                text = _clean(node.get_text(separator=" "))
                if len(text) > 40:
                    result["abstract"] = text
                    break

        # ── Claim 1 ────────────────────────────────────────────────────────
        # Google Patents renders claims inside <section itemprop="claims">.
        # Individual claims use custom elements: <claim num="1"><claim-text>...</claim-text></claim>
        # Fallback: first <claim-text> anywhere, then first div with "claim" in its class.
        claims_section = soup.find("section", attrs={"itemprop": "claims"})
        if claims_section:
            first = (
                claims_section.find(attrs={"num": "1"})
                or claims_section.find("claim-text")
                or claims_section.find("div", class_=re.compile(r"\bclaim\b", re.I))
            )
            if first:
                result["claim_1"] = _clean(first.get_text(separator=" "))
        else:
            # Page rendered without the claims section wrapper — try bare element
            ct = soup.find("claim-text")
            if ct:
                result["claim_1"] = _clean(ct.get_text(separator=" "))

    except Exception:
        pass  # Non-fatal: caller falls back to SerpAPI snippet

    return result
