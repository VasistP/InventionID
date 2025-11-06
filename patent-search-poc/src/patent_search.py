"""
Simple patent search using Google Patents
"""
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import time
import json


class GooglePatentsSearcher:
    """
    Simple Google Patents searcher using web scraping
    Note: For production, use official APIs or BigQuery
    """
    
    BASE_URL = "https://patents.google.com"
    
    def search(self, query: str, max_results: int = 20) -> List[Dict]:
        """
        Search Google Patents
        
        Args:
            query: Search query
            max_results: Maximum results to return
            
        Returns:
            List of patent dictionaries
        """
        print(f"🔍 Searching Google Patents for: '{query}'")
        
        # Build search URL
        search_url = f"{self.BASE_URL}/?q={requests.utils.quote(query)}"
        
        try:
            # Make request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(search_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse results
            soup = BeautifulSoup(response.text, 'html.parser')
            results = self._parse_search_results(soup, max_results)
            
            print(f"✓ Found {len(results)} patents")
            return results
            
        except Exception as e:
            print(f"✗ Search error: {e}")
            return []
    
    def _parse_search_results(self, soup: BeautifulSoup, max_results: int) -> List[Dict]:
        """Parse search results from HTML"""
        results = []
        
        # Find result items (this selector may need updating if Google changes their HTML)
        result_items = soup.find_all('search-result-item', limit=max_results)
        
        for item in result_items:
            try:
                # Extract patent data
                patent = {}
                
                # Patent number and URL
                link = item.find('a')
                if link and link.get('href'):
                    patent['url'] = self.BASE_URL + link.get('href')
                    # Extract patent number from URL
                    patent['patent_number'] = link.get('href').split('/')[-1].split('?')[0]
                
                # Title
                title_elem = item.find('span', {'class': 'html'})
                if title_elem:
                    patent['title'] = title_elem.get_text(strip=True)
                
                # Extract metadata if available
                meta = item.find_all('span')
                for span in meta:
                    text = span.get_text(strip=True)
                    if text.startswith('US') or text.startswith('EP') or text.startswith('WO'):
                        patent['patent_number'] = text
                
                if patent:
                    results.append(patent)
                    
            except Exception as e:
                print(f"Error parsing result: {e}")
                continue
        
        return results
    
    def get_patent_details(self, patent_number: str) -> Dict:
        """
        Get detailed information for a specific patent
        
        Args:
            patent_number: Patent number (e.g., US10123456B2)
            
        Returns:
            Patent details dictionary
        """
        print(f"📄 Fetching details for {patent_number}")
        
        url = f"{self.BASE_URL}/patent/{patent_number}"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
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
            details['cpc_codes'] = [elem.get('content', '') for elem in cpc_elems if elem.get('content', '').startswith(('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'))]
            
            # Extract claims (first independent claim)
            claims_section = soup.find('section', {'itemprop': 'claims'})
            if claims_section:
                claim_1 = claims_section.find('div', {'num': '1'})
                if claim_1:
                    details['claim_1'] = claim_1.get_text(strip=True)
            
            return details
            
        except Exception as e:
            print(f"✗ Error fetching details: {e}")
            return {'patent_number': patent_number, 'error': str(e)}


# Test function
if __name__ == "__main__":
    searcher = GooglePatentsSearcher()
    
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