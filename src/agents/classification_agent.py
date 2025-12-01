import json
import re
from typing import Dict, Any
from .agent_base import AgentBase


class ClassificationAgent(AgentBase):

    def classify(self, invention: Dict, iteration: int = 0) -> Dict[str, Any]:
        thought = "Analyzing technical features to refine domain classification"

        features_str = json.dumps(invention.get(
            'key_technical_features', []), indent=2)

        prompt = f"""Analyze and refine the classification of this invention.

INVENTION: {invention.get('invention_name', 'Unknown')}

TECHNICAL DESCRIPTION:
{invention.get('technical_description', 'N/A')}

CURRENT FEATURES:
{features_str}

CURRENT DOMAIN: {invention.get('domain_classification', 'Unknown')}

CURRENT CATEGORY: {invention.get('statutory_category', 'Unknown')}

Refine the classification by:
1. Verifying statutory_category is correct (Process/Machine/Manufacture/Composition of Matter)
2. Refining domain_classification to be more specific
3. Adding 2-3 more relevant technical keywords

Return ONLY a JSON object (no markdown, no code blocks):
{{"statutory_category": "Process", "domain_classification": "AI/Machine Learning", "additional_keywords": ["keyword1", "keyword2", "keyword3"], "classification_confidence": 0.9}}"""

        result = self.execute(thought, prompt, iteration)

        refined = invention.copy()
        obs = result["observation"]
        refined['statutory_category'] = obs.get(
            'statutory_category', refined.get('statutory_category'))
        refined['domain_classification'] = obs.get(
            'domain_classification', refined.get('domain_classification'))

        current_keywords = refined.get('inventor_keywords', [])
        new_keywords = obs.get('additional_keywords', [])
        refined['inventor_keywords'] = list(
            set(current_keywords + new_keywords))

        return refined

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
        return None

    def _get_action_description(self) -> str:
        return "Refining domain classification and technical categorization"
