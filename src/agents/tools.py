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
        if self.rate_limiter:
            self.rate_limiter.acquire()

        prompt = f"Analyze this PDF and extract the main sections. Return JSON with: sections (array of section names), total_pages, has_technical_content (boolean)"

        response = self.llm.generate(
            prompt, files=[pdf_path], max_tokens=2000, temperature=0.3)
        return self._parse_json(response)

    def llm_extractor(self, prompt: str, pdf_path: str = None, context: str = None) -> Dict[str, Any]:
        if self.rate_limiter:
            self.rate_limiter.acquire()

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
        if self.rate_limiter:
            self.rate_limiter.acquire()

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
        if self.rate_limiter:
            self.rate_limiter.acquire()

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
