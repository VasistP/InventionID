"""
Patent Prior Art Search - Modular System

Simplified version using:
- LLM web search (default)
- Rate limiting
- Lightweight patent search (IDs/URLs/titles only)
- Modular configuration
"""
import json
import os
from typing import Dict, List
from pathlib import Path
from dotenv import load_dotenv
from inventionID import InventionExtractor

# Import core modules
from llm_client import LLMClient
from patent_search import GooglePatentsSearcher
import config
from utils.prompt_templates import PromptTemplates

# Import optional modules based on config
if config.USE_RATE_LIMITING:
    from modules.rate_limiter import RateLimiter


class PatentSearchSystem:
    """Modular patent prior art search system"""

    def __init__(self):
        """Initialize system with configuration"""
        load_dotenv()

        self.rate_limiter = None
        if config.USE_RATE_LIMITING:
            self.rate_limiter = RateLimiter(
                requests_per_minute=config.RATE_LIMIT_RPM,
                min_request_interval=config.MIN_REQUEST_INTERVAL,
                verbose=config.LOG_RATE_LIMIT_WAITS
            )
            print(f"Rate limiting enabled: {config.RATE_LIMIT_RPM} RPM")

        # Core components
        self.llm = LLMClient(
            rate_limiter=self.rate_limiter if config.USE_RATE_LIMITING else None)
        self.searcher = GooglePatentsSearcher(
            rate_limiter=self.rate_limiter if config.USE_RATE_LIMITING else None)

        # Optional components based on config

    def _load_or_extract_invention(self, input_file: str) -> Dict:
        """
        Load invention from JSON or extract from PDF

        Args:
            input_file: Path to JSON or PDF file

        Returns:
            Dictionary containing invention data
        """
        file_path = Path(input_file)

        if not file_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        # Check file extension
        if file_path.suffix.lower() == '.pdf':
            print(f"\n📄 PDF detected: Extracting invention data...")
            print("-" * 80)

            # Extract invention from PDF
            extractor = InventionExtractor(output_dir="data")
            inventions = extractor.process_inventions(
                str(file_path),
                output_filename=None
            )

            if not inventions:
                raise ValueError("No inventions found in PDF")

            # Use first invention if multiple found
            invention_key = list(inventions.keys())[0]
            invention = inventions[invention_key]

            print(f"✅ Extracted invention: {invention['invention_name']}")
            print("-" * 80)

            return invention

        elif file_path.suffix.lower() == '.json':
            print(f"\n📋 JSON detected: Loading invention data...")
            return self._load_invention(input_file)

        else:
            raise ValueError(
                f"Unsupported file type: {file_path.suffix}. Use .pdf or .json")

    def run(self, invention_file: str, output_file: str = None):
        """
        Run patent prior art search

        Args:
            invention_file: Path to invention JSON file
            output_file: Path to output results
        """
        print("=" * 80)
        print("PATENT PRIOR ART SEARCH")
        print("=" * 80)
        # file_path = Path(invention_file)
        # is_pdf = file_path.suffix.lower() == ".pdf"

        # # ==========================================
        # # 0. SCORE INVENTION BEFORE EXTRACTION (PDF ONLY)
        # # ==========================================
        # if is_pdf:
        #     print("\n[0/3] Evaluating invention potential FROM FULL PDF...")

        #     extractor = InventionExtractor(output_dir="data")
        #     full_pdf_text = extractor.extract_text(str(file_path))

        #     # Load rubric & template
        #     with open("Invention_guidelines.json") as f:
        #         guideline = json.load(f)
        #     with open("invention_evaluator_template.json") as f:
        #         evaluator_template = json.load(f)

        #     scoring_prompt = PromptTemplates.generate_invention_assessment_from_pdf(
        #         full_pdf_text,
        #         guideline,
        #         evaluator_template
        #     )

        #     scoring_response = self.llm.generate(scoring_prompt)

        #     try:
        #         invention_score = json.loads(scoring_response)
        #         print("\nInvention Scoring Result:")
        #         print(json.dumps(invention_score, indent=2))

        #         self.invention_score = invention_score
        #     except:
        #         print("\n⚠ Invalid scoring JSON:")
        #         print(scoring_response)
        #         return None

        #     # STOP EARLY if not invention
        #     if invention_score.get("final_classification", "").lower() == "scientific discovery":
        #         print("\n⚠ PDF does not describe an invention. Stopping.")
        #         return invention_score

        #     print("\n✔ Invention detected. Proceeding to extraction...")

        # # ==========================================
        # # 1. Extract or load invention (existing logic)
        # # ==========================================
        # Load invention


        invention = self._load_or_extract_invention(invention_file)
        print(f"\nLoaded: {invention['invention_name']}")

        # Generate search queries
        print(f"\n[1/3] Generating search queries...")
        queries = self._generate_search_queries(invention)
        print(f" Generated {len(queries)} queries")
        if config.VERBOSE_LOGGING:
            for i, q in enumerate(queries, 1):
                print(f"  {i}. {q}")

        # Search patents (lightweight - IDs/URLs only)
        print(
            f"\n[2/3] Searching patents (max: {config.MAX_PATENTS_TO_FETCH})...")
        all_patents = self._search_patents(
            queries, config.MAX_PATENTS_TO_FETCH)
        unique_patents = self._deduplicate_patents(all_patents)
        print(f" Found {len(unique_patents)} unique patents")

        # Generate report
        print(f"\n[3/3] Generating report...")
        report = self._generate_report(invention, unique_patents)

        # Save results
        if output_file:
            self._save_results(report, output_file)
            print(f" Results saved to {output_file}")

        # Print summary
        self._print_summary(report)

        return report

    def _load_invention(self, file_path: str) -> Dict:
        """Load invention disclosure from JSON file"""
        with open(file_path, 'r') as f:
            return json.load(f)

    def _generate_search_queries(self, invention: Dict) -> List[str]:
        """Generate search queries using LLM with rate limiting"""
        prompt = f"""Generate {config.MAX_SEARCH_QUERIES} effective patent search queries for this invention.

INVENTION: {invention['invention_name']}

TECHNICAL DESCRIPTION:
{invention['technical_description']}

PROBLEM:
{invention['problem_statement']}

SOLUTION:
{invention['solution_approach']}

KEY FEATURES:
{json.dumps(invention['key_technical_features'], indent=2)}

Return ONLY a JSON array of {config.MAX_SEARCH_QUERIES} search queries (5-10 words each).
Format: ["query 1", "query 2", ...]
"""

        # Use rate limiter if enabled
        if self.rate_limiter:
            self.rate_limiter.acquire()

        response = self.llm.generate(
            prompt,
            max_tokens=config.DEFAULT_MAX_TOKENS,
            temperature=config.DEFAULT_TEMPERATURE
        )

        # Parse response
        try:
            import re
            pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            match = re.search(pattern, response)
            json_str = match.group(1).strip() if match else response.strip()
            queries = json.loads(json_str)
            return queries[:config.MAX_SEARCH_QUERIES]
        except Exception as e:
            print(f"⚠ LLM parsing failed, using fallback queries")
            return self._get_fallback_queries(invention)

    def _get_fallback_queries(self, invention: Dict) -> List[str]:
        """Generate fallback queries from invention data"""
        return [
            invention['invention_name'],
            ' '.join(invention['key_technical_features'][0].split()[:8]),
            ' '.join(invention.get('inventor_keywords', [])[:5]),
            f"{invention.get('domain_classification', '')} {invention.get('inventor_keywords', [''])[0]}",
            invention['solution_approach'].split('.')[0][:100]
        ][:config.MAX_SEARCH_QUERIES]

    def _search_patents(self, queries: List[str], max_total: int) -> List[Dict]:
        """
        Search for patents using queries
        Returns lightweight results: patent_number, url, title only
        """
        all_patents = []
        results_per_query = max(1, max_total // len(queries))

        for i, query in enumerate(queries, 1):
            if len(all_patents) >= max_total:
                break

            if config.VERBOSE_LOGGING:
                print(f"  Query {i}/{len(queries)}: {query[:50]}...")

            # Use rate limiter if enabled
            if self.rate_limiter:
                self.rate_limiter.acquire()

            patents = self.searcher.search(
                query, max_results=results_per_query)
            all_patents.extend(patents)

        return all_patents[:max_total]

    def _deduplicate_patents(self, patents: List[Dict]) -> List[Dict]:
        """Remove duplicate patents by patent_number"""
        seen = set()
        unique = []

        for patent in patents:
            patent_number = patent.get('patent_number', '')
            if patent_number and patent_number not in seen:
                seen.add(patent_number)
                unique.append(patent)

        return unique

    def _generate_report(self, invention: Dict, patents: List[Dict]) -> Dict:
        """Generate lightweight report (no detailed analysis yet)"""
        return {
            'invention_evaluation': getattr(self, 'invention_score', {}), #NEW
            'invention': {
                'name': invention['invention_name'],
                'domain': invention.get('domain_classification', 'Unknown'),
                'description': invention.get('technical_description', '')[:200]
            },
            'search_metadata': {
                'total_patents_found': len(patents),
                'max_patents_fetched': config.MAX_PATENTS_TO_FETCH,
                'rate_limiting_enabled': config.USE_RATE_LIMITING,
                'detailed_analysis_enabled': config.USE_DETAILED_ANALYSIS
            },
            'patents': patents,
            'note': 'Lightweight search only (IDs/URLs/titles). Enable USE_DETAILED_ANALYSIS for full patent content and relevance analysis.'
        }

    def _save_results(self, report: Dict, output_file: str):
        """Save results to JSON file"""
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(
            output_file) else '.', exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

    def _print_summary(self, report: Dict):
        """Print summary to console"""
        print("\n" + "=" * 80)
        print("SEARCH RESULTS SUMMARY")
        print("=" * 80)

        print(f"\nInvention: {report['invention']['name']}")
        print(f"Domain: {report['invention']['domain']}")
        print(
            f"\nResults: {report['search_metadata']['total_patents_found']} patents found")

        if report['search_metadata']['detailed_analysis_enabled']:
            print("\n Detailed analysis enabled")
        else:
            print("\n⚠ Lightweight mode: Only patent IDs/URLs returned")
            print("  Enable USE_DETAILED_ANALYSIS in config.py for full content")

        # Print patent list with URLs
        print(f"\n📋 PATENTS FOUND:")
        print("-" * 80)
        for i, patent in enumerate(report['patents'][:10], 1):  # Show first 10
            patent_num = patent.get('patent_number', 'Unknown')
            title = patent.get('title', 'No title')[:60]
            url = patent.get('url', 'N/A')
            print(f"\n{i}. {patent_num}")
            print(f"   Title: {title}...")
            print(f"   URL: {url}")

        if len(report['patents']) > 10:
            print(f"\n... and {len(report['patents']) - 10} more patents")

        print("\n" + "=" * 80)

        # Rate limiter stats if enabled
        if self.rate_limiter and config.VERBOSE_LOGGING:
            print("\nRate Limiter Stats:")
            stats = self.rate_limiter.get_stats()
            print(f"  Total requests: {stats['total_requests_tracked']}")
            print(
                f"  Requests in last minute: {stats['requests_in_last_minute']}")
    


def main():
    """Run the patent search system"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Patent Prior Art Search System')
    parser.add_argument(
        '--input',
        default='data/sample_invention.json',
        help='Path to invention JSON or PDF file'
    )
    parser.add_argument(
        '--output',
        default='output/results.json',
        help='Path to output results file'
    )
    parser.add_argument(
        '--config',
        choices=['testing', 'quick_scan', 'budget', 'comprehensive'],
        help='Use a preset configuration'
    )

    args = parser.parse_args()

    # Apply preset configuration if specified
    if args.config:
        config.apply_preset(args.config)
        print(f"\n Applied '{args.config}' preset configuration")

    # Print configuration if verbose
    if config.VERBOSE_LOGGING:
        config.print_config_summary()

    # Create and run system
    system = PatentSearchSystem()
    report = system.run(
        invention_file=args.input,
        output_file=args.output
    )

    print("\n✅ Search completed successfully!")

    # Show what's enabled
    print("\n💡 Current Configuration:")
    print(f"  Rate Limiting: {'' if config.USE_RATE_LIMITING else 'X'}")
    print(f"  Batching: {'' if config.USE_BATCHING else 'X'}")
    print(f"  Summarization: {'' if config.USE_SUMMARIZATION else 'X'}")
    print(f"  Embedding Filter: {'' if config.USE_EMBEDDING_FILTER else 'X'}")
    print(
        f"  Detailed Analysis: {'' if config.USE_DETAILED_ANALYSIS else 'X'}")


if __name__ == "__main__":
    main()
