"""
Lightweight patent search using Google Patents
Returns only patent IDs, URLs, and titles (no detailed content)
Detail fetching moved to patent_analyzer module
Uses LLM web search only
"""
import json
import os
from typing import List, Dict
from llm_client import LLMClient
from utils.prompt_templates import PromptTemplates


class GooglePatentsSearcher:
    """
    Lightweight Google Patents searcher using LLM web search
    Returns only: patent_number, url, title
    Note: For production, use official APIs or BigQuery
    """

    BASE_URL = "https://patents.google.com"

    def __init__(self):
        """
        Initialize searcher with LLM web search
        """

        if os.getenv('ANTHROPIC_API_KEY'):
            self.llm = LLMClient(tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
                "allowed_domains": ["patents.google.com"]
            }])
        else:
            self.llm = LLMClient()

    def search(self, query: str, max_results: int = 20) -> List[Dict]:
        """
        Search patents using Claude with web search tool
        Returns only: patent_number, url, title

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of patent dictionaries with format:
            [{"patent_number": "US...", "url": "https://...", "title": "..."}]
        """
        print(f"Searching Google Patents using LLM web search for: '{query}'")

        prompt = PromptTemplates.get_patents(query, max_results)

        try:

            message = self.llm.generate(prompt)
            # message = self.anthropic.messages.create(
            #     model="claude-sonnet-4-5",
            #     max_tokens=4000,
            #     temperature=0.3,
            #     messages=[
            #         {"role": "user", "content": prompt}
            #     ],
            # tools=[{
            #     "type": "web_search_20250305",
            #     "name": "web_search",
            #     "max_uses": 5,
            #     "allowed_domains": ["patents.google.com"]
            # }]
            # )

            print("\n Message:\n", message)
            # # Extract text from response
            # response_text = ""
            # for block in message.content:
            #     if block.type == "text":
            #         response_text += block.text

            response_text = message

            patents = self._extract_json_from_response(response_text)

            normalized_patents = []
            for patent in patents[:max_results]:
                normalized = {
                    'patent_number': patent.get('patent_number', ''),
                    'title': patent.get('title', ''),
                    'url': patent.get('url', '')
                }
                if normalized['patent_number']:  # Only include if we have a patent number
                    normalized_patents.append(normalized)

            print(f"Found {len(normalized_patents)} patents using LLM")
            return normalized_patents

        except json.JSONDecodeError as e:
            print(f"Error: parsing LLM response as JSON: {e}")
            print(f"Response: {response_text[:500]}")
            return []
        except Exception as e:
            print(f"Error: LLM search error: {e}")
            return []

    def _extract_json_from_response(self, response_text: str) -> List[Dict]:
        """
        Extract JSON array from LLM response
        Handles markdown code blocks and plain JSON
        """
        import re

        # Try to find JSON in markdown code blocks
        pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(pattern, response_text)

        if match:
            json_str = match.group(1).strip()
        else:
            # Try to find JSON array without code blocks
            # Look for [ ... ] pattern
            array_match = re.search(r'\[[\s\S]*\]', response_text)
            if array_match:
                json_str = array_match.group(0)
            else:
                # Last resort: try the whole response
                json_str = response_text

        try:
            # Parse and return
            patents = json.loads(json_str)
            if isinstance(patents, list):
                return patents
            else:
                print(f"Error:  Expected JSON array, got: {type(patents)}")
                return []
        except json.JSONDecodeError as e:
            print(f"Error:  Could not parse JSON: {e}")
            print(f"Attempted to parse: {json_str[:200]}...")
            return []


# Test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    searcher = GooglePatentsSearcher()
    results = searcher.search(
        "transformer neural network protein folding", max_results=5)
    print(f"\nFound {len(results)} results:")
    for r in results:
        print(
            f"  - {r.get('patent_number', 'Unknown')}: {r.get('title', 'No title')[:60]}...")
        print(f"    URL: {r.get('url', 'N/A')}")
