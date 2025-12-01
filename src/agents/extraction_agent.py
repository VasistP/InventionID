
import json
import re
from typing import Dict, Any
from .agent_base import AgentBase
from utils.scoring import InventionScorer


class ExtractionAgent(AgentBase):

    def extract(self, pdf_path: str, doc_analysis: Dict, iteration: int = 0) -> Dict[str, Any]:
        thought = "Using identified sections to extract structured invention data"

        sections_summary = self._format_sections(doc_analysis)

        prompt = f"""Extract structured invention data from this document.

IDENTIFIED SECTIONS:
{sections_summary}

Extract the following fields:
1. invention_id: Generate format INV-2024-XXX
2. invention_name: Concise name (max 10 words)
3. technical_description: Detailed description (2-4 sentences)
4. problem_statement: What problem it solves (2-3 sentences)
5. solution_approach: How it solves the problem (2-3 sentences)
6. key_technical_features: List of 5-7 specific technical features
7. statutory_category: One of: "Process", "Machine", "Manufacture", "Composition of Matter"
8. domain_classification: Technical domain (e.g., "AI/ML", "Biotech")
9. inventor_keywords: 5-10 relevant technical keywords
10. context: document_section and confidence_score (0.0-1.0)

Return ONLY a JSON object with these exact fields.
````json
{{
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
    "confidence_score": 0.8
  }}
}}
```"""

        result = self.execute(thought, prompt, iteration)
        return result["observation"]

    def _format_sections(self, doc_analysis: Dict) -> str:
        sections = doc_analysis.get('sections', [])
        formatted = []
        for i, sec in enumerate(sections, 1):
            formatted.append(
                f"{i}. {sec.get('section_name', 'Unknown')} ({sec.get('content_type', 'general')})")
        return "\n".join(formatted)

    def _parse_response(self, response: str) -> Dict:
        pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(pattern, response)

        if match:
            json_str = match.group(1).strip()
        else:
            obj_match = re.search(r'\{[\s\S]*\}', response)
            json_str = obj_match.group(0) if obj_match else response

        return json.loads(json_str)

    def _calculate_score(self, observation: Dict) -> int:
        result = InventionScorer.score_invention(observation)
        return result["total_score"]

    def _get_action_description(self) -> str:
        return "Extracting structured invention fields from document"
