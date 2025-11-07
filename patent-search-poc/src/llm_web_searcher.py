"""
LLM-based web search for patents
Uses LLM to search the web and extract patent information
"""
import requests
from typing import List, Dict
from llm_client import LLMClient
import json
import time
from bs4 import BeautifulSoup


class LLMWebSearcher:
    """
    Patent searcher using LLM with web search capabilities
    """

    def __init__(self, llm_client: LLMClient):
        """Initialize with LLM client"""
        self.llm = llm_client
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        # Check if model supports web search (Claude models)
        self.supports_web_search = 'claude' in self.llm.model.lower()

    def search(self, query: str, max_results: int = 20) -> List[Dict]:
        """
        Search for patents using LLM-based web search

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of patent dictionaries
        """
        print(f"🔍 Using LLM {'web search' if self.supports_web_search else 'knowledge'} for: '{query}'")

        # Use LLM to search and extract patent information
        if self.supports_web_search:
            # Claude with web search - use natural language prompt
            search_prompt = f"""
Search the web for US patents related to: "{query}"

Find up to {max_results} relevant patents and provide information about each patent including:
- Patent number (format: US1234567B2 or US20200123456A1)
- Title
- Brief abstract/description
- Why it's relevant to the query

Return the results as a JSON array with this structure:
[
  {{
    "patent_number": "US1234567B2",
    "title": "Patent title here",
    "url": "https://patents.google.com/patent/US1234567B2",
    "abstract": "Brief description of what the patent covers",
    "relevance": "Why this patent is relevant to the query"
  }}
]

Focus on recent patents (2015-2024) when possible.
Search Google Patents or USPTO databases.
Return ONLY the JSON array, nothing else.
"""
        else:
            # OpenAI or other models without web search - use knowledge-based prompt
            search_prompt = f"""
You are a patent search assistant. Based on your knowledge, identify relevant US patents related to: "{query}"

Return a JSON array of up to {max_results} patents with this structure:
[
  {{
    "patent_number": "US1234567B2",
    "title": "Patent title here",
    "url": "https://patents.google.com/patent/US1234567B2",
    "abstract": "Brief description of what the patent covers",
    "relevance": "Why this patent is relevant to the query"
  }}
]

Focus on recent patents (2015-2024) when possible.
Use real patent numbers in the format: US[number][type] (e.g., US10123456B2, US20200123456A1)
Construct the Google Patents URL as: https://patents.google.com/patent/[patent_number]

Return ONLY the JSON array, nothing else.
"""

        try:
            response = self.llm.generate(
                search_prompt,
                max_tokens=2000,
                temperature=0.5,
                use_web_search=self.supports_web_search,
                max_web_searches=5
            )

            # Parse JSON response
            response = response.strip()
            if response.startswith('```'):
                response = response.split('```')[1]
                if response.startswith('json'):
                    response = response[4:]
                response = response.strip()

            patents = json.loads(response)

            # Validate and clean results
            valid_patents = []
            for patent in patents[:max_results]:
                if 'patent_number' in patent and patent['patent_number']:
                    # Ensure URL is properly formatted
                    if 'url' not in patent or not patent['url']:
                        patent['url'] = f"https://patents.google.com/patent/{patent['patent_number']}"
                    valid_patents.append(patent)

            print(f"✓ LLM found {len(valid_patents)} patents")
            return valid_patents

        except json.JSONDecodeError as e:
            print(f"✗ Failed to parse LLM response as JSON: {e}")
            print(f"Response was: {response[:200]}...")
            return self._fallback_search(query, max_results)
        except Exception as e:
            print(f"✗ LLM search error: {e}")
            return self._fallback_search(query, max_results)

    def _fallback_search(self, query: str, max_results: int) -> List[Dict]:
        """
        Fallback search using DuckDuckGo HTML search
        """
        print(f"   Using fallback search method...")

        try:
            # Search DuckDuckGo for Google Patents links
            search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query + ' site:patents.google.com')}"

            response = self.session.get(search_url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            results = []

            # Extract patent links from DuckDuckGo results
            for link in soup.find_all('a', class_='result__a'):
                href = link.get('href', '')
                if 'patents.google.com/patent/' in href:
                    # Extract patent number from URL
                    try:
                        patent_num = href.split('/patent/')[-1].split('/')[0].split('?')[0]
                        if patent_num and len(patent_num) > 5:
                            results.append({
                                'patent_number': patent_num,
                                'title': link.get_text(strip=True),
                                'url': f"https://patents.google.com/patent/{patent_num}",
                                'abstract': 'N/A'
                            })

                            if len(results) >= max_results:
                                break
                    except:
                        continue

            if results:
                print(f"✓ Fallback search found {len(results)} patents")
                return results
            else:
                print(f"✗ Fallback search found no results")
                return []

        except Exception as e:
            print(f"✗ Fallback search error: {e}")
            return []

    def get_patent_details(self, patent_number: str) -> Dict:
        """
        Get detailed information for a specific patent using LLM

        Args:
            patent_number: Patent number (e.g., US10123456B2)

        Returns:
            Patent details dictionary
        """
        print(f"📄 Fetching details for {patent_number} using LLM")

        url = f"https://patents.google.com/patent/{patent_number}"

        # Try to fetch the patent page
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract basic details from meta tags
            details = {
                'patent_number': patent_number,
                'url': url
            }

            # Extract title
            title_elem = soup.find('meta', {'name': 'DC.title'})
            if title_elem:
                details['title'] = title_elem.get('content', '')

            # Extract abstract
            abstract_elem = soup.find('meta', {'name': 'DC.description'})
            if abstract_elem:
                details['abstract'] = abstract_elem.get('content', '')

            # Extract dates
            date_elem = soup.find('meta', {'name': 'DC.date'})
            if date_elem:
                details['publication_date'] = date_elem.get('content', '')

            # Extract inventors
            inventor_elems = soup.find_all('meta', {'name': 'DC.contributor'})
            details['inventors'] = [elem.get('content', '') for elem in inventor_elems]

            # Extract assignee
            assignee_elem = soup.find('meta', {'name': 'DC.publisher'})
            if assignee_elem:
                details['assignee'] = assignee_elem.get('content', '')

            # Extract CPC codes
            cpc_elems = soup.find_all('meta', {'name': 'DC.type'})
            details['cpc_codes'] = [
                elem.get('content', '') for elem in cpc_elems
                if elem.get('content', '').startswith(('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'))
            ]

            # Extract first claim
            claims_section = soup.find('section', {'itemprop': 'claims'})
            if claims_section:
                claim_1 = claims_section.find('div', {'num': '1'})
                if claim_1:
                    details['claim_1'] = claim_1.get_text(strip=True)

            # If we have enough details, return
            if details.get('title') and details.get('abstract'):
                return details

            # Otherwise, use LLM to extract from HTML
            print(f"   Using LLM to extract patent details...")
            return self._llm_extract_details(patent_number, response.text[:10000])

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                print(f"   ⚠ 403 Forbidden - using LLM to generate details...")
                return self._llm_generate_details(patent_number)
            else:
                print(f"✗ HTTP error fetching details: {e}")
                return {'patent_number': patent_number, 'url': url, 'error': str(e)}
        except Exception as e:
            print(f"✗ Error fetching details: {e}")
            return {'patent_number': patent_number, 'url': url, 'error': str(e)}

    def _llm_extract_details(self, patent_number: str, html_content: str) -> Dict:
        """Use LLM to extract patent details from HTML or web search"""

        if self.supports_web_search:
            # Use web search to find patent details directly
            prompt = f"""
Search the web for detailed information about patent {patent_number}.

Find and return a JSON object with:
{{
  "patent_number": "{patent_number}",
  "title": "patent title",
  "abstract": "patent abstract/summary",
  "publication_date": "YYYY-MM-DD",
  "inventors": ["inventor names"],
  "assignee": "assignee/company name",
  "claim_1": "first independent claim text",
  "url": "https://patents.google.com/patent/{patent_number}"
}}

Search Google Patents or USPTO database for accurate information.
Return ONLY the JSON object.
"""
            use_search = True
        else:
            # Extract from HTML content
            prompt = f"""
Extract patent information from this HTML content for patent {patent_number}.

HTML excerpt:
{html_content[:8000]}

Extract and return a JSON object with:
{{
  "patent_number": "{patent_number}",
  "title": "patent title",
  "abstract": "patent abstract/summary",
  "publication_date": "YYYY-MM-DD",
  "inventors": ["inventor names"],
  "assignee": "assignee/company name",
  "claim_1": "first independent claim text",
  "url": "https://patents.google.com/patent/{patent_number}"
}}

Return ONLY the JSON object.
"""
            use_search = False

        try:
            response = self.llm.generate(
                prompt,
                max_tokens=1000,
                temperature=0.2,
                use_web_search=use_search,
                max_web_searches=3
            )
            response = response.strip()
            if response.startswith('```'):
                response = response.split('```')[1]
                if response.startswith('json'):
                    response = response[4:]

            details = json.loads(response)
            details['patent_number'] = patent_number
            details['url'] = f"https://patents.google.com/patent/{patent_number}"
            return details

        except Exception as e:
            print(f"   ⚠ LLM extraction failed: {e}")
            return self._llm_generate_details(patent_number)

    def _llm_generate_details(self, patent_number: str) -> Dict:
        """Use LLM to generate plausible patent details based on patent number"""

        if self.supports_web_search:
            # Use web search as last resort
            prompt = f"""
Search the web for information about patent {patent_number}.

Return a JSON object with:
{{
  "patent_number": "{patent_number}",
  "title": "patent title",
  "abstract": "patent abstract/description",
  "publication_date": "YYYY-MM-DD",
  "inventors": ["inventor names"],
  "assignee": "assignee/company",
  "claim_1": "first claim or N/A",
  "url": "https://patents.google.com/patent/{patent_number}"
}}

If you cannot find the patent, return:
- title: "Patent {patent_number}"
- abstract: "Information not available"
- Other fields: "N/A" or empty arrays

Return ONLY the JSON object.
"""
            use_search = True
        else:
            # Use knowledge-based generation
            prompt = f"""
For patent {patent_number}, provide plausible patent information based on your knowledge.

Return a JSON object with:
{{
  "patent_number": "{patent_number}",
  "title": "likely patent title based on your knowledge",
  "abstract": "likely abstract/description",
  "publication_date": "approximate date if known",
  "inventors": ["likely inventors if known, or empty array"],
  "assignee": "likely assignee/company if known",
  "claim_1": "plausible first claim or N/A",
  "url": "https://patents.google.com/patent/{patent_number}"
}}

If you don't have information about this patent, provide:
- title: "Patent {patent_number}"
- abstract: "Information not available"
- Other fields: "N/A" or empty arrays

Return ONLY the JSON object.
"""
            use_search = False

        try:
            response = self.llm.generate(
                prompt,
                max_tokens=800,
                temperature=0.3,
                use_web_search=use_search,
                max_web_searches=2
            )
            response = response.strip()
            if response.startswith('```'):
                response = response.split('```')[1]
                if response.startswith('json'):
                    response = response[4:]

            details = json.loads(response)
            details['patent_number'] = patent_number
            details['url'] = f"https://patents.google.com/patent/{patent_number}"
            if self.supports_web_search:
                details['source'] = 'web_search'
            else:
                details['source'] = 'llm_generated'
            return details

        except Exception as e:
            print(f"   ✗ LLM generation failed: {e}")
            return {
                'patent_number': patent_number,
                'title': f"Patent {patent_number}",
                'abstract': 'Information not available',
                'url': f"https://patents.google.com/patent/{patent_number}",
                'error': 'Could not fetch details'
            }


# Test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    llm = LLMClient()
    searcher = LLMWebSearcher(llm)

    # Test search
    results = searcher.search("machine learning protein structure", max_results=5)
    print(f"\nFound {len(results)} results:")
    for r in results:
        print(f"  - {r.get('patent_number', 'Unknown')}: {r.get('title', 'No title')[:60]}...")

    # Test details fetch
    if results:
        details = searcher.get_patent_details(results[0]['patent_number'])
        print(f"\nDetails for {details['patent_number']}:")
        print(f"Title: {details.get('title', 'N/A')}")
        print(f"Abstract: {details.get('abstract', 'N/A')[:200]}...")
