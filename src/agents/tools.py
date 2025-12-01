from typing import Dict, Any, Callable
from llm_client import LLMClient
from utils.scoring import InventionScorer
import json
import re


class ToolRegistry:
    def __init__(self, llm_client: LLMClient, rate_limiter=None):
        self.llm = llm_client
        self.rate_limiter = rate_limiter
        self.scorer = InventionScorer()

    def pdf_reader(self, pdf_path: str) -> Dict[str, Any]:

        prompt = f"Analyze this PDF and extract the main sections. Return JSON with: sections (array of section names), total_pages, has_technical_content (boolean)"

        response = self.llm.generate(
            prompt, files=[pdf_path], max_tokens=2000, temperature=0.3)
        return self._parse_json(response)

    def llm_extractor(self, prompt: str = None, pdf_path: str = None, context: str = None) -> Dict[str, Any]:

        if prompt is None:
            prompt = """Extract a complete patent invention disclosure from this document.

Return ONLY a JSON object (NO markdown, NO code blocks) with these EXACT fields:

{
  "invention_id": "INV-2024-XXX",
  "invention_name": "concise name max 10 words",
  "technical_description": "detailed 2-4 sentences explaining the invention",
  "problem_statement": "2-3 sentences describing the problem being solved",
  "solution_approach": "2-3 sentences explaining how the invention solves it",
  "key_technical_features": ["feature1", "feature2", "feature3", "feature4", "feature5"],
  "statutory_category": "Process or Machine or Manufacture or Composition of Matter",
  "domain_classification": "specific domain like AI/ML, Biotech, Hardware, etc",
  "inventor_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "context": {
    "document_section": "where in document this appears",
    "confidence_score": 0.85
  }
}

CRITICAL REQUIREMENTS:
- Include at least 5 key_technical_features (specific, not generic)
- Include at least 5 inventor_keywords
- All text fields must be complete sentences
- statutory_category MUST be one of the 4 exact options listed
- Return ONLY the JSON object, nothing else"""

        full_prompt = prompt
        if context:
            full_prompt = f"CONTEXT:\n{context}\n\nTASK:\n{prompt}"

        files = [pdf_path] if pdf_path else None
        response = self.llm.generate(
            full_prompt, files=files, max_tokens=4000, temperature=0.3)
        return self._parse_json(response)

    def validator(self, invention: Dict) -> Dict[str, Any]:
        score_result = self.scorer.score_invention(invention)
        return {
            "score": score_result["total_score"],
            "issues": score_result["issues"],
            "breakdown": score_result["breakdown"],
            "valid": score_result["total_score"] >= 85
        }

    def field_enhancer(self, field_name: str, current_value: Any, invention_context: Dict) -> str:

        prompt = f"""Enhance this field for a patent invention disclosure.

Field: {field_name}
Current Value: {current_value}

Invention Context:
{json.dumps(invention_context, indent=2)}

Return an enhanced version of this field that is more specific, detailed, and patent-ready. Return ONLY the enhanced text, no JSON."""

        return self.llm.generate(prompt, files=None, max_tokens=1000, temperature=0.3)

    def _parse_json(self, response: str) -> Dict:
        pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(pattern, response)

        if match:
            json_str = match.group(1).strip()
        else:
            obj_match = re.search(r'\{[\s\S]*\}', response)
            json_str = obj_match.group(0) if obj_match else response

        try:
            return json.loads(json_str)
        except:
            return {"raw_response": response}

    def quick_validator(self, invention: Dict) -> Dict:
        required = [
            'invention_id', 'invention_name', 'technical_description',
            'problem_statement', 'solution_approach', 'key_technical_features',
            'statutory_category', 'domain_classification', 'inventor_keywords',
            'context'
        ]
        missing = [f for f in required if f not in invention or not invention[f]]

        return {
            "complete": len(missing) == 0,
            "missing_fields": missing,
            "field_count": len(required) - len(missing)
        }

    def section_reader(self, pdf_path: str, section_name: str) -> str:

        prompt = f"Extract ONLY the '{section_name}' section from this PDF. Return just the text content from that section, nothing else."

        response = self.llm.generate(
            prompt, files=[pdf_path], max_tokens=2000, temperature=0.3)
        return response

    def field_counter(self, invention: Dict) -> Dict:
        features = invention.get('key_technical_features', [])
        keywords = invention.get('inventor_keywords', [])
        description = invention.get('technical_description', '')
        problem = invention.get('problem_statement', '')
        solution = invention.get('solution_approach', '')

        return {
            "feature_count": len(features),
            "keyword_count": len(keywords),
            "description_length": len(description),
            "problem_length": len(problem),
            "solution_length": len(solution),
            "total_content_length": len(description) + len(problem) + len(solution)
        }

    def get_tools(self, tool_names: list) -> Dict[str, Callable]:
        tools = {}
        for name in tool_names:
            if hasattr(self, name):
                tools[name] = getattr(self, name)
        return tools
