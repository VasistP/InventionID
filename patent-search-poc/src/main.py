"""
Patent Prior Art Search POC - Main Script

This POC demonstrates:
1. Reading invention disclosure JSON
2. Using LLM to generate search queries
3. Searching Google Patents
4. Using LLM to analyze and rank results
5. Generating a simple report
"""
import json
import os
from typing import Dict, List
from dotenv import load_dotenv
from llm_client import LLMClient
from patent_search import GooglePatentsSearcher
import time


class PatentSearchPOC:
    """Simple POC for patent prior art search"""
    
    def __init__(self):
        """Initialize POC"""
        load_dotenv()
        self.llm = LLMClient()
        self.searcher = GooglePatentsSearcher()
    
    def run(self, invention_file: str, output_file: str = None):
        """
        Run complete prior art search
        
        Args:
            invention_file: Path to invention JSON file
            output_file: Path to output results (optional)
        """
        print("=" * 80)
        print("PATENT PRIOR ART SEARCH POC")
        print("=" * 80)
        
        # Step 1: Load invention
        print("\n[STEP 1] Loading invention disclosure...")
        invention = self._load_invention(invention_file)
        print(f"✓ Loaded invention: {invention['invention_name']}")
        
        # Step 2: Generate search queries
        print("\n[STEP 2] Generating search queries using LLM...")
        queries = self._generate_search_queries(invention)
        print(f"✓ Generated {len(queries)} search queries:")
        for i, q in enumerate(queries, 1):
            print(f"   {i}. {q}")
        
        # Step 3: Search patents
        print("\n[STEP 3] Searching patent databases...")
        all_patents = []
        for query in queries[:3]:  # Limit to top 3 queries for POC
            patents = self.searcher.search(query, max_results=10)
            all_patents.extend(patents)
            time.sleep(2)  # Be polite to Google
        
        # Deduplicate
        unique_patents = self._deduplicate_patents(all_patents)
        print(f"✓ Found {len(unique_patents)} unique patents")
        
        # Step 4: Fetch patent details
        print("\n[STEP 4] Fetching patent details...")
        detailed_patents = []
        for i, patent in enumerate(unique_patents[:15], 1):  # Limit to 15 for POC
            print(f"   {i}/{min(15, len(unique_patents))}", end='\r')
            details = self.searcher.get_patent_details(patent['patent_number'])
            detailed_patents.append(details)
            time.sleep(1)  # Be polite
        print(f"✓ Fetched details for {len(detailed_patents)} patents")
        
        # Step 5: Analyze and rank patents
        print("\n[STEP 5] Analyzing patents using LLM...")
        analyzed_patents = self._analyze_patents(invention, detailed_patents)
        print(f"✓ Analyzed {len(analyzed_patents)} patents")
        
        # Step 6: Generate report
        print("\n[STEP 6] Generating report...")
        report = self._generate_report(invention, analyzed_patents)
        
        # Save results
        if output_file:
            self._save_results(report, output_file)
            print(f"✓ Results saved to {output_file}")
        
        # Print summary
        self._print_summary(report)
        
        return report
    
    def _load_invention(self, file_path: str) -> Dict:
        """Load invention disclosure from JSON file"""
        with open(file_path, 'r') as f:
            return json.load(f)
    
    def _generate_search_queries(self, invention: Dict) -> List[str]:
        """Generate search queries using LLM"""
        prompt = f"""
You are a patent search expert. Generate 5 highly effective patent search queries for this invention:

INVENTION: {invention['invention_name']}

TECHNICAL DESCRIPTION:
{invention['technical_description']}

PROBLEM:
{invention['problem_statement']}

SOLUTION:
{invention['solution_approach']}

KEY FEATURES:
{json.dumps(invention['key_technical_features'], indent=2)}

Generate 5 search queries that will find relevant prior art. Each query should:
- Be 5-10 words
- Use technical terminology
- Focus on the core innovation
- Be suitable for Google Patents search

Return ONLY a JSON array of 5 query strings, nothing else.
Example format: ["query one", "query two", "query three", "query four", "query five"]
"""
        
        response = self.llm.generate(prompt, max_tokens=500, temperature=0.3)
        
        try:
            queries = json.loads(response)
            return queries
        except:
            # Fallback: extract from invention
            print("   ⚠ LLM response parsing failed, using fallback queries")
            return [
                invention['invention_name'],
                ' '.join(invention['key_technical_features'][0].split()[:8]),
                ' '.join(invention['inventor_keywords'][:5]),
                f"{invention['domain_classification']} {invention['inventor_keywords'][0]}",
                invention['solution_approach'].split('.')[0][:100]
            ]
    
    def _deduplicate_patents(self, patents: List[Dict]) -> List[Dict]:
        """Remove duplicate patents"""
        seen = set()
        unique = []
        
        for patent in patents:
            num = patent.get('patent_number', '')
            if num and num not in seen:
                seen.add(num)
                unique.append(patent)
        
        return unique
    
    def _analyze_patents(self, invention: Dict, patents: List[Dict]) -> List[Dict]:
        """Analyze each patent for relevance using LLM"""
        analyzed = []
        
        for i, patent in enumerate(patents):
            print(f"   Analyzing patent {i+1}/{len(patents)}", end='\r')
            
            analysis = self._analyze_single_patent(invention, patent)
            
            patent['analysis'] = analysis
            analyzed.append(patent)
        
        # Sort by relevance score
        analyzed.sort(key=lambda x: x['analysis'].get('relevance_score', 0), reverse=True)
        
        return analyzed
    
    def _analyze_single_patent(self, invention: Dict, patent: Dict) -> Dict:
        """Analyze a single patent against the invention"""
        prompt = f"""
You are a patent attorney analyzing prior art. Compare this patent against the invention:

INVENTION:
Name: {invention['invention_name']}
Description: {invention['technical_description']}
Key Features: {json.dumps(invention['key_technical_features'])}

PATENT:
Number: {patent.get('patent_number', 'Unknown')}
Title: {patent.get('title', 'N/A')}
Abstract: {patent.get('abstract', 'N/A')}
Claim 1: {patent.get('claim_1', 'N/A')}

Analyze this patent and provide:
1. Relevance score (0.0-1.0) where:
   - 0.9-1.0 = BLOCKING (anticipates invention, >90% overlap)
   - 0.7-0.89 = RELEVANT (similar solution, 70-89% overlap)
   - 0.5-0.69 = RELATED (adjacent technology, 50-69% overlap)
   - <0.5 = NOT RELEVANT

2. Classification: blocking, relevant, related, or not_relevant

3. Brief analysis: 2-3 sentences explaining technical overlap

4. Key differences: What's different from the invention?

Return ONLY valid JSON in this exact format:
{{
  "relevance_score": 0.X,
  "classification": "blocking|relevant|related|not_relevant",
  "analysis": "Brief analysis here",
  "key_differences": "Key differences here"
}}
"""
        
        try:
            response = self.llm.generate(prompt, max_tokens=800, temperature=0.2)
            
            # Try to parse JSON
            # Sometimes LLM adds markdown code blocks
            response = response.strip()
            if response.startswith('```'):
                response = response.split('```')[1]
                if response.startswith('json'):
                    response = response[4:]
            
            analysis = json.loads(response)
            return analysis
            
        except Exception as e:
            print(f"\n   ⚠ Analysis error for {patent.get('patent_number', 'unknown')}: {e}")
            return {
                'relevance_score': 0.0,
                'classification': 'not_relevant',
                'analysis': 'Analysis failed',
                'key_differences': 'Unknown'
            }
    
    def _generate_report(self, invention: Dict, patents: List[Dict]) -> Dict:
        """Generate final report"""
        # Categorize patents
        blocking = [p for p in patents if p['analysis']['classification'] == 'blocking']
        relevant = [p for p in patents if p['analysis']['classification'] == 'relevant']
        related = [p for p in patents if p['analysis']['classification'] == 'related']
        
        report = {
            'invention': {
                'id': invention['invention_id'],
                'name': invention['invention_name']
            },
            'search_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'summary': {
                'total_patents_analyzed': len(patents),
                'blocking_patents': len(blocking),
                'relevant_patents': len(relevant),
                'related_patents': len(related)
            },
            'risk_assessment': self._assess_risk(blocking, relevant),
            'results': {
                'blocking': blocking[:5],  # Top 5
                'relevant': relevant[:10],  # Top 10
                'related': related[:10]  # Top 10
            }
        }
        
        return report
    
    def _assess_risk(self, blocking: List, relevant: List) -> str:
        """Assess overall patentability risk"""
        if len(blocking) > 0:
            return "HIGH - Blocking prior art identified"
        elif len(relevant) > 3:
            return "MEDIUM - Multiple relevant references found"
        elif len(relevant) > 0:
            return "LOW-MEDIUM - Some relevant prior art exists"
        else:
            return "LOW - No significant blocking art found"
    
    def _save_results(self, report: Dict, output_file: str):
        """Save results to JSON file"""
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
    
    def _print_summary(self, report: Dict):
        """Print summary to console"""
        print("\n" + "=" * 80)
        print("SEARCH RESULTS SUMMARY")
        print("=" * 80)
        
        print(f"\nInvention: {report['invention']['name']}")
        print(f"Search Date: {report['search_date']}")
        
        print(f"\nResults:")
        print(f"  - Total patents analyzed: {report['summary']['total_patents_analyzed']}")
        print(f"  - Blocking patents: {report['summary']['blocking_patents']}")
        print(f"  - Relevant patents: {report['summary']['relevant_patents']}")
        print(f"  - Related patents: {report['summary']['related_patents']}")
        
        print(f"\nRisk Assessment: {report['risk_assessment']}")
        
        # Print blocking patents
        if report['results']['blocking']:
            print(f"\n🚨 BLOCKING PATENTS:")
            for i, patent in enumerate(report['results']['blocking'], 1):
                print(f"\n   {i}. {patent.get('patent_number', 'Unknown')}")
                print(f"      Title: {patent.get('title', 'N/A')[:80]}...")
                print(f"      Score: {patent['analysis']['relevance_score']:.2f}")
                print(f"      Analysis: {patent['analysis']['analysis']}")
        
        # Print top relevant patents
        if report['results']['relevant']:
            print(f"\n📋 TOP RELEVANT PATENTS:")
            for i, patent in enumerate(report['results']['relevant'][:3], 1):
                print(f"\n   {i}. {patent.get('patent_number', 'Unknown')}")
                print(f"      Title: {patent.get('title', 'N/A')[:80]}...")
                print(f"      Score: {patent['analysis']['relevance_score']:.2f}")
                print(f"      Analysis: {patent['analysis']['analysis'][:150]}...")
        
        print("\n" + "=" * 80)


def main():
    """Run the POC"""
    poc = PatentSearchPOC()
    
    # Run search
    report = poc.run(
        invention_file='data/sample_invention.json',
        output_file='output/results.json'
    )
    
    print("\n✅ POC completed successfully!")


if __name__ == "__main__":
    main()