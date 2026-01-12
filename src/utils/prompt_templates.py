"""
Prompt Templates for Patent Search System

Contains all prompt templates for:
- Potential Invention Identification
- Query generation
- Patent detail fetching
- Patent analysis
- Batch operations

All templates are designed to produce structured JSON outputs.
"""
import json

class PromptTemplates:
    """Collection of prompt templates for patent search operations"""

    @staticmethod
    def generate_search_queries(invention_data: dict, num_queries: int = 5) -> str:
        """
        Generate prompt for creating patent search queries

        Args:
            invention_data: Dictionary containing invention details
            num_queries: Number of queries to generate

        Returns:
            Formatted prompt string
        """
        return f"""Generate {num_queries} highly effective patent search queries for this invention.

INVENTION: {invention_data.get('invention_name', 'Unknown')}

TECHNICAL DESCRIPTION:
{invention_data.get('technical_description', 'N/A')}

PROBLEM STATEMENT:
{invention_data.get('problem_statement', 'N/A')}

SOLUTION APPROACH:
{invention_data.get('solution_approach', 'N/A')}

KEY TECHNICAL FEATURES:
{', '.join(invention_data.get('key_technical_features', []))}

Generate {num_queries} search queries that will find relevant prior art. Each query should be 5-10 words and use technical terminology suitable for Google Patents search.

IMPORTANT: Return ONLY a JSON array with no other text.

Format:
```json
["query 1", "query 2", "query 3", ...]
```"""

    @staticmethod
    def get_patents(query: str, max_results: int = 10) -> str:
        """
        Generate prompt for fetching a list of patents

        Args:
            max_results: Maximum number of patents to fetch

        Returns:
            Formatted prompt string
        """
        return f"""
Search Google Patents (patents.google.com) for patents related to: "{query}"

Find up to {max_results} relevant patents and return them as a JSON array.

For each patent, extract ONLY:
- patent_number (e.g., US10123456B2, EP1234567A1, WO2020123456A1)
- title (patent title)
- url (full Google Patents URL)

IMPORTANT: Return ONLY the JSON array with no other text. Do not include abstracts or other detailed information.

Format:
```json
[
  {{
    "patent_number": "US...",
    "title": "...",
    "url": "https://patents.google.com/patent/..."
  }}
]
```
"""

    @staticmethod
    def get_inventions() -> str:

        return f"""Analyze this document and identify all distinct inventions described.

In the uploaded document, for EACH invention found, extract the following information:

1. invention_id: Generate a unique ID (format: INV-YYYY-NNN)
2. invention_name: Clear, concise name (max 10 words)
3. technical_description: Detailed technical description (2-4 sentences)
4. problem_statement: What problem does it solve? (2-3 sentences)
5. solution_approach: How does it solve the problem? (2-3 sentences)
6. key_technical_features: List of 3-7 key technical features
7. statutory_category: One of: "Process", "Machine", "Manufacture", "Composition of Matter"
8. domain_classification: Technical domain (e.g., "AI/ML", "Biotech", "Software", "Hardware")
9. inventor_keywords: 5-10 relevant technical keywords
10. context:
    - document_section: Where in the document (e.g., "Section 3.2")
    - confidence_score: Your confidence (0.0 to 1.0)

IMPORTANT: Return ONLY a JSON object with inventions numbered as keys ("1", "2", etc.).
If no clear inventions are found, return an empty object: {{}}.

Format:
```json
{{
  "1": {{
    "invention_id": "INV-2024-001",
    "invention_name": "...",
    "technical_description": "...",
    "problem_statement": "...",
    "solution_approach": "...",
    "key_technical_features": ["feature1", "feature2", ...],
    "statutory_category": "Process",
    "domain_classification": "...",
    "inventor_keywords": ["keyword1", "keyword2", ...],
    "context": {{
            "document_section": "...",
        "confidence_score": 0.85
    }}
  }},
  "2": {{
    ...
  }}
}}
```"""

    @staticmethod
    def fetch_patent_details_single(patent_number: str) -> str:
        """
        Generate prompt for fetching details of a single patent

        Args:
            patent_number: Patent number (e.g., US10123456B2)

        Returns:
            Formatted prompt string
        """
        return f"""Find detailed information for patent: {patent_number}

Search Google Patents and extract:
- patent_number: {patent_number}
- title: Full patent title
- abstract: Complete abstract text
- publication_date: YYYY-MM-DD format
- filing_date: YYYY-MM-DD format
- inventors: Array of inventor names
- assignee: Company/organization
- claim_1: First independent claim (complete text)
- url: https://patents.google.com/patent/{patent_number}

IMPORTANT: Return ONLY a JSON object with no other text.

Format:
```json
{{
  "patent_number": "{patent_number}",
  "title": "...",
  "abstract": "...",
  "publication_date": "YYYY-MM-DD",
  "filing_date": "YYYY-MM-DD",
  "inventors": ["Name 1", "Name 2"],
  "assignee": "...",
  "claim_1": "...",
  "url": "https://patents.google.com/patent/{patent_number}"
}}
```"""

    @staticmethod
    def fetch_patent_details_batch(patent_numbers: list) -> str:
        """
        Generate prompt for fetching details of multiple patents in batch

        Args:
            patent_numbers: List of patent numbers

        Returns:
            Formatted prompt string
        """
        numbers_str = ", ".join(patent_numbers)

        return f"""Find detailed information for these patents: {numbers_str}

Search Google Patents and for EACH patent, extract:
- patent_number
- title
- abstract
- publication_date (YYYY-MM-DD)
- filing_date (YYYY-MM-DD)
- inventors (array)
- assignee
- claim_1 (first independent claim)
- url

IMPORTANT: Return ONLY a JSON array with no other text. One object per patent.

Format:
```json
[
  {{
    "patent_number": "US...",
    "title": "...",
    "abstract": "...",
    "publication_date": "YYYY-MM-DD",
    "filing_date": "YYYY-MM-DD",
    "inventors": ["..."],
    "assignee": "...",
    "claim_1": "...",
    "url": "https://patents.google.com/patent/US..."
  }},
  ...
]
```"""

    @staticmethod
    def analyze_patent_single(invention_description: str, patent_data: dict) -> str:
        """
        Generate prompt for analyzing a single patent against invention

        Args:
            invention_description: Description of the invention
            patent_data: Dictionary containing patent details

        Returns:
            Formatted prompt string
        """
        return f"""Analyze this patent's relevance to the invention.

INVENTION:
{invention_description}

PATENT: {patent_data.get('patent_number', 'Unknown')}
Title: {patent_data.get('title', 'N/A')}

Abstract:
{patent_data.get('abstract', 'N/A')}

First Claim:
{patent_data.get('claim_1', 'N/A')}

Analyze:
1. Relevance score (0.0 to 1.0)
2. Classification: "blocking", "relevant", or "related"
3. Key similarities
4. Key differences
5. Brief analysis (2-3 sentences)

IMPORTANT: Return ONLY a JSON object with no other text.

Format:
```json
{{
  "patent_number": "{patent_data.get('patent_number', 'Unknown')}",
  "relevance_score": 0.85,
  "classification": "relevant",
  "similarities": ["similarity 1", "similarity 2"],
  "differences": ["difference 1", "difference 2"],
  "analysis": "Brief analysis text..."
}}
```"""

    @staticmethod
    def analyze_patents_batch(invention_description: str, patents_data: list) -> str:
        """
        Generate prompt for analyzing multiple patents in batch

        Args:
            invention_description: Description of the invention
            patents_data: List of dictionaries containing patent details

        Returns:
            Formatted prompt string
        """
        # Build patent summaries for the prompt
        patents_summary = []
        for i, patent in enumerate(patents_data, 1):
            summary = f"""
Patent {i}: {patent.get('patent_number', 'Unknown')}
Title: {patent.get('title', 'N/A')}
Abstract: {patent.get('abstract', 'N/A')[:300]}...
First Claim: {patent.get('claim_1', 'N/A')[:300]}...
"""
            patents_summary.append(summary)

        patents_text = "\n".join(patents_summary)

        return f"""Analyze these patents' relevance to the invention.

INVENTION:
{invention_description}

PATENTS TO ANALYZE:
{patents_text}

For EACH patent, provide:
1. Relevance score (0.0 to 1.0)
2. Classification: "blocking", "relevant", or "related"
3. Key similarities
4. Key differences
5. Brief analysis (2-3 sentences)

IMPORTANT: Return ONLY a JSON array with no other text. One object per patent in the same order.

Format:
```json
[
  {{
    "patent_number": "US...",
    "relevance_score": 0.85,
    "classification": "relevant",
    "similarities": ["similarity 1", "similarity 2"],
    "differences": ["difference 1", "difference 2"],
    "analysis": "Brief analysis..."
  }},
  ...
]
```"""

    @staticmethod
    def summarize_abstract(abstract_text: str, max_sentences: int = 3) -> str:
        """
        Generate prompt for summarizing patent abstract

        Args:
            abstract_text: Full abstract text
            max_sentences: Maximum sentences in summary

        Returns:
            Formatted prompt string
        """
        return f"""Summarize this patent abstract in {max_sentences} sentences or less.

ABSTRACT:
{abstract_text}

Create a concise summary that captures:
- Main technical innovation
- Key problem solved
- Primary approach/method

Return ONLY the summary text, no additional commentary."""

    @staticmethod
    def summarize_claim(claim_text: str, max_sentences: int = 5) -> str:
        """
        Generate prompt for summarizing patent claim

        Args:
            claim_text: Full claim text
            max_sentences: Maximum sentences in summary

        Returns:
            Formatted prompt string
        """
        return f"""Summarize this patent claim in {max_sentences} sentences or less.

CLAIM:
{claim_text}

Create a concise summary that captures:
- What is being claimed
- Key technical features
- Scope of protection

Return ONLY the summary text, no additional commentary."""

    @staticmethod
    def extract_key_features(patent_data: dict) -> str:
        """
        Generate prompt for extracting key technical features from patent

        Args:
            patent_data: Dictionary containing patent details

        Returns:
            Formatted prompt string
        """
        return f"""Extract key technical features from this patent.

PATENT: {patent_data.get('patent_number', 'Unknown')}
Title: {patent_data.get('title', 'N/A')}

Abstract:
{patent_data.get('abstract', 'N/A')}

Claims:
{patent_data.get('claim_1', 'N/A')}

Extract 5-10 key technical features as a list.

IMPORTANT: Return ONLY a JSON array of strings.

Format:
```json
["feature 1", "feature 2", "feature 3", ...]
```"""



    @staticmethod
    def generate_invention_assessment_from_pdf(
                guideline: dict,
                evaluator_template: dict
    ) -> str:
        """
        First-stage prompt: LLM reads the FULL PDF text and applies
        the invention rubric BEFORE any extraction or patent search.
        """

        return f"""
You are an expert invention evaluator.

You will be given a PDF file as input (already uploaded).
Do NOT repeat or summarize the entire PDF.
Extract only what is needed.

==========================
### INVENTION SCORING RUBRIC (REFERENCE ONLY — DO NOT COPY)
==========================
{json.dumps(guideline, indent=2)}

==========================
### OUTPUT TEMPLATE (FILL THIS OUT — DO NOT COPY)
==========================
{json.dumps(evaluator_template, indent=2)}

==========================
### TASK
==========================
1. Read the uploaded PDF fully.
2. Apply the rubric exactly.
3. Fill in the OUTPUT TEMPLATE.
4. Do NOT repeat the rubric or the template.
5. Do NOT add explanations outside JSON.
6. Do NOT wrap the output in ```json fences.
7. Return ONLY a valid JSON object that matches the OUTPUT TEMPLATE.
"""


    @staticmethod
    def compare_patents(patent1_data: dict, patent2_data: dict) -> str:
        """
        Generate prompt for comparing two patents

        Args:
            patent1_data: First patent data
            patent2_data: Second patent data

        Returns:
            Formatted prompt string
        """
        return f"""Compare these two patents.

PATENT 1: {patent1_data.get('patent_number', 'Unknown')}
Title: {patent1_data.get('title', 'N/A')}
Abstract: {patent1_data.get('abstract', 'N/A')[:300]}...

PATENT 2: {patent2_data.get('patent_number', 'Unknown')}
Title: {patent2_data.get('title', 'N/A')}
Abstract: {patent2_data.get('abstract', 'N/A')[:300]}...

Provide:
1. Similarity score (0.0 to 1.0)
2. Common features
3. Unique features in Patent 1
4. Unique features in Patent 2
5. Brief comparison summary

IMPORTANT: Return ONLY a JSON object.

Format:
```json
{{
  "similarity_score": 0.75,
  "common_features": ["feature 1", "feature 2"],
  "patent1_unique": ["unique 1", "unique 2"],
  "patent2_unique": ["unique 1", "unique 2"],
  "summary": "Brief comparison..."
}}
```"""


# Helper function to get invention description for prompts
def get_invention_description(invention_data: dict) -> str:
    """
    Format invention data into a concise description for prompts

    Args:
        invention_data: Dictionary containing invention details

    Returns:
        Formatted description string
    """
    return f"""
Invention: {invention_data.get('invention_name', 'Unknown')}
Domain: {invention_data.get('domain_classification', 'N/A')}

Problem: {invention_data.get('problem_statement', 'N/A')}

Solution: {invention_data.get('solution_approach', 'N/A')}

Key Features:
{chr(10).join(f"- {feature}" for feature in invention_data.get('key_technical_features', []))}
""".strip()


# Testing
if __name__ == "__main__":
    print("=" * 80)
    print("TESTING PROMPT TEMPLATES")
    print("=" * 80)

    # Test data
    test_invention = {
        'invention_name': 'Machine Learning Protein Folding System',
        'technical_description': 'A deep learning system for predicting protein structures',
        'problem_statement': 'Traditional methods are slow and inaccurate',
        'solution_approach': 'Use transformer neural networks for structure prediction',
        'key_technical_features': [
            'Transformer architecture',
            'Attention mechanisms',
            'Multi-scale feature extraction'
        ]
    }

    test_patent = {
        'patent_number': 'US10123456B2',
        'title': 'Neural network protein structure prediction',
        'abstract': 'A method for predicting protein structures using deep learning...',
        'claim_1': 'A computer-implemented method comprising...'
    }

    templates = PromptTemplates()

    # Test 1: Query generation
    print("\n[TEST 1] Query Generation Prompt")
    print("-" * 80)
    prompt = templates.generate_search_queries(test_invention, num_queries=3)
    print(prompt[:300] + "...")

    # Test 2: Single patent details
    print("\n[TEST 2] Single Patent Details Prompt")
    print("-" * 80)
    prompt = templates.fetch_patent_details_single('US10123456B2')
    print(prompt[:300] + "...")

    # Test 3: Batch patent details
    print("\n[TEST 3] Batch Patent Details Prompt")
    print("-" * 80)
    prompt = templates.fetch_patent_details_batch(
        ['US10123456B2', 'US10789012B2'])
    print(prompt[:300] + "...")

    # Test 4: Single patent analysis
    print("\n[TEST 4] Single Patent Analysis Prompt")
    print("-" * 80)
    inv_desc = get_invention_description(test_invention)
    prompt = templates.analyze_patent_single(inv_desc, test_patent)
    print(prompt[:300] + "...")

    # Test 5: Batch patent analysis
    print("\n[TEST 5] Batch Patent Analysis Prompt")
    print("-" * 80)
    prompt = templates.analyze_patents_batch(
        inv_desc, [test_patent, test_patent])
    print(prompt[:400] + "...")

    print("\n" + "=" * 80)
    print("ALL TEMPLATES GENERATED SUCCESSFULLY")
    print("=" * 80)
