import json
import re
from typing import Dict, Any
from .agent_base import AgentBase
from utils.scoring import InventionScorer


class RefinementAgent(AgentBase):

    def refine(self, invention: Dict, validation: Dict, pdf_path: str, iteration: int = 0) -> Dict[str, Any]:
        thought = f"Addressing {len(validation.get('issues_found', []))} identified issues"

        issues = validation.get('issues_found', [])
        recommendations = validation.get('recommendations', [])
        issues_str = json.dumps(issues, indent=2)
        recommendations_str = json.dumps(recommendations, indent=2)
        invention_str = json.dumps(invention, indent=2)

        prompt = f"""Refine this invention extraction based on validation feedback.

CURRENT INVENTION: {invention.get('invention_name', 'Unknown')}

IDENTIFIED ISSUES:
{issues_str}

RECOMMENDATIONS:
{recommendations_str}

CURRENT DATA:
{invention_str}

Focus on fixing the identified issues. Return ONLY the COMPLETE refined invention as JSON (no markdown, no code blocks).
Include all fields: invention_id, invention_name, technical_description, problem_statement, solution_approach, key_technical_features, statutory_category, domain_classification, inventor_keywords, context"""

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

    def _calculate_score(self, observation: Dict) -> int:
        result = InventionScorer.score_invention(observation)
        return result["total_score"]

    def _get_action_description(self) -> str:
        return "Refining invention data based on validation feedback"
