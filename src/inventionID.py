"""
Invention Identifier - Extract structured invention data from PDF documents

This script:
1. Reads PDF documents
2. Extracts text content
3. Uses LLM to identify and structure invention disclosures
4. Outputs structured JSON format
"""

from llm_client import LLMClient
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv
from utils.prompt_templates import PromptTemplates
from agents import AutonomousOrchestrator
from utils.logger import InventionLogger

# Add src to path to import modules
sys.path.append(str(Path(__file__).parent / 'src'))


class InventionExtractor:
    """Extract structured invention data from PDF documents"""

    def __init__(self, output_dir: str = "data"):
        """
        Initialize the invention extractor

        Args:
            output_dir: Directory to save output JSON files
        """
        load_dotenv()
        self.llm = None
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    # def extract_text_from_pdf(self, pdf_path: str) -> str:
    #     """
    #     Extract text content from PDF file

    #     Args:
    #         pdf_path: Path to PDF file

    #     Returns:
    #         Extracted text content
    #     """
    #     if PDF_LIBRARY == 'pypdf2':
    #         return self._extract_with_pypdf2(pdf_path)
    #     elif PDF_LIBRARY == 'pdfplumber':
    #         return self._extract_with_pdfplumber(pdf_path)
    #     else:
    #         raise RuntimeError("No PDF parsing library available")

    # def _extract_with_pypdf2(self, pdf_path: str) -> str:
    #     """Extract text using PyPDF2"""
    #     text = []
    #     with open(pdf_path, 'rb') as file:
    #         pdf_reader = PyPDF2.PdfReader(file)
    #         for page_num, page in enumerate(pdf_reader.pages, 1):
    #             page_text = page.extract_text()
    #             if page_text.strip():
    #                 text.append(f"\n--- Page {page_num} ---\n")
    #                 text.append(page_text)
    #     return '\n'.join(text)

    # def _extract_with_pdfplumber(self, pdf_path: str) -> str:
    #     """Extract text using pdfplumber"""
    #     text = []
    #     with pdfplumber.open(pdf_path) as pdf:
    #         for page_num, page in enumerate(pdf.pages, 1):
    #             page_text = page.extract_text()
    #             if page_text and page_text.strip():
    #                 text.append(f"\n--- Page {page_num} ---\n")
    #                 text.append(page_text)
    #     return '\n'.join(text)

    def identify_inventions(self, pdf_path, rate_limiter=None) -> Dict:

        logger = InventionLogger()

        if not self.llm:
            self.llm = LLMClient(rate_limiter=rate_limiter)

        orchestrator = AutonomousOrchestrator(
            llm_client=self.llm,
            logger=logger,
            rate_limiter=rate_limiter
        )

        print("Running autonomous multi-agent extraction pipeline...")
        result = orchestrator.orchestrate(pdf_path)

        invention_data = result["invention"]
        score = result["score"]["total_score"]
        api_calls = result["total_api_calls"]

        print(f"\nExtraction completed:")
        print(f"  Score: {score}/100 {result['score']['rating']}")
        print(f"  API Calls: {api_calls}")
        print(f"  Threshold met: {result['threshold_met']}")
        print(f"  Budget exceeded: {result['budget_exceeded']}")

        return {"1": invention_data}

    def _parse_llm_response(self, response: str) -> Dict:
        """
        Parse LLM response to extract JSON

        Args:
            response: Raw LLM response

        Returns:
            Parsed inventions dictionary
        """
        import re

        # Try to find JSON in markdown code blocks
        pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(pattern, response)

        if match:
            json_str = match.group(1).strip()
        else:
            # Try to find JSON object
            obj_match = re.search(r'\{[\s\S]*\}', response)
            if obj_match:
                json_str = obj_match.group(0)
            else:
                json_str = response.strip()

        # Parse JSON
        inventions = json.loads(json_str)

        # Validate structure
        if not isinstance(inventions, dict):
            raise ValueError("Response is not a dictionary")

        return inventions

    def validate_invention_data(self, inventions: Dict) -> bool:
        """
        Validate the extracted invention data

        Args:
            inventions: Dictionary of inventions

        Returns:
            True if valid, False otherwise
        """
        if not inventions:
            raise ValueError("No inventions data found")

        required_fields = [
            'invention_id', 'invention_name', 'technical_description',
            'problem_statement', 'solution_approach', 'key_technical_features',
            'statutory_category', 'domain_classification', 'inventor_keywords',
            'context'
        ]

        for inv_num, invention in inventions.items():
            if not isinstance(invention, dict):
                print(f"ERROR: Invention {inv_num} is not a dictionary")
                return False

            missing_fields = [
                field for field in required_fields if field not in invention]
            if missing_fields:
                print(
                    f"WARNING: Invention {inv_num} missing fields: {missing_fields}")
                return False

        return True

    def save_inventions(self, inventions: Dict, output_filename: str) -> str:
        """
        Save inventions to JSON file

        Args:
            inventions: Dictionary of inventions
            output_filename: Name of output file

        Returns:
            Path to saved file
        """
        output_path = self.output_dir / output_filename

        with open(output_path, 'w') as f:
            json.dump(inventions, f, indent=2)

        return str(output_path)

    def process_inventions(self, rate_limiter, pdf_path: str, output_filename: Optional[str] = None, ) -> Dict:
        """
        Complete pipeline: PDF → Inventions → JSON

        Args:
            pdf_path: Path to PDF file
            output_filename: Optional output filename (auto-generated if not provided)

        Returns:
            Dictionary of extracted inventions
        """
        print("=" * 80)
        print("INVENTION EXTRACTOR")
        print("=" * 80)

        print("\n[1/3] Identifying inventions using LLM...")
        inventions = self.identify_inventions(
            pdf_path, rate_limiter=rate_limiter)

        if not inventions:
            print("WARNING: No inventions found in document")
            return {}

        print(f"Found {len(inventions)} invention(s)")

        print("\n[2/3] Validating extracted data...")
        if self.validate_invention_data(inventions):
            print("All inventions validated successfully")
        else:
            print("WARNING: Validation warnings (see above)")

        print("\n[3/3] Saving to JSON...")
        if output_filename is None:
            pdf_name = Path(pdf_path).stem
            output_filename = f"{pdf_name}_inventions.json"

        output_path = self.save_inventions(inventions, output_filename)
        print(f"Saved to: {output_path}")

        self._print_summary(inventions)

        return inventions

    def _print_summary(self, inventions: Dict):
        """Print summary of extracted inventions"""
        print("\n" + "=" * 80)
        print("EXTRACTION SUMMARY")
        print("=" * 80)

        for inv_num, invention in inventions.items():
            print(f"\nInvention #{inv_num}:")
            print(f"  ID: {invention.get('invention_id', 'N/A')}")
            print(f"  Name: {invention.get('invention_name', 'N/A')}")
            print(f"  Domain: {invention.get('domain_classification', 'N/A')}")
            print(f"  Category: {invention.get('statutory_category', 'N/A')}")
            print(
                f"  Confidence: {invention.get('context', {}).get('confidence_score', 'N/A')}")
            print(
                f"  Features: {len(invention.get('key_technical_features', []))}")

        print("\n" + "=" * 80)


def main():
    """CLI interface for invention extraction"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Extract structured invention data from PDF documents'
    )
    parser.add_argument(
        'pdf_path',
        help='Path to PDF file'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output JSON filename (auto-generated if not provided)',
        default=None
    )
    parser.add_argument(
        '-d', '--output-dir',
        help='Output directory for JSON files',
        default='data'
    )

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)

    extractor = InventionExtractor(output_dir=args.output_dir)
    inventions = extractor.process_inventions(args.pdf_path, args.output)

    if inventions:
        print("\nExtraction completed successfully!")
        sys.exit(0)
    else:
        print("\nWARNING: No inventions extracted")
        sys.exit(1)


if __name__ == "__main__":
    main()
