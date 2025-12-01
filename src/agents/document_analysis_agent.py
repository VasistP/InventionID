import json
import re
from typing import Dict, Any
from .agent_base import AgentBase


class DocumentAnalysisAgent(AgentBase):

    def analyze(self, pdf_path: str, iteration: int = 0) -> Dict[str, Any]:
        thought = "I need to identify sections containing invention disclosures"

        prompt = f"""Analyze this document and identify sections containing invention information.

For each section found, extract:
- section_name: Name/heading of the section
- page_range: Pages where it appears
- content_type: "technical_description", "problem_statement", "solution", or "features"
- key_quotes: 2-3 important sentences from that section

Return ONLY a JSON object with this structure:
``````json
{{
  "sections": [
    {{
      "section_name": "...",
      "page_range": "1-3",
      "content_type": "technical_description",
      "key_quotes": ["quote1", "quote2"]
    }}
  ],
  "total_sections_found": 3,
  "document_has_inventions": true
}}
`````"""

        result = self.execute(thought, prompt, iteration)
        return result["observation"]

    def _parse_response(self, response: str) -> Dict:
        pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(pattern, response)

        if match:
            json_str = match.group(1).strip()
        else:
            obj_match = re.search(r'\{[\s\S]*\}', response)
            json_str = obj_match.group(0) if obj_match else response

        return json.loads(json_str)

    def _get_action_description(self) -> str:
        return "Analyzing PDF structure and identifying invention sections"

    def _format_observation(self, observation: Dict) -> str:
        sections = observation.get('total_sections_found', 0)
        has_inv = observation.get('document_has_inventions', False)
        return f"Found {sections} sections, has_inventions={has_inv}"
