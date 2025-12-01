import json
import re
from typing import Dict, Any
from .agent_base import AgentBase
from utils.scoring import InventionScorer


class ValidationAgent(AgentBase):

    def validate(self, invention: Dict, iteration: int = 0) -> Dict[str, Any]:
        thought = "Checking extraction quality and identifying gaps"

        score_result = InventionScorer.score_invention(invention)
        issues_str = json.dumps(score_result['issues'], indent=2)

        prompt = f"""Validate this invention extraction for completeness and quality.

INVENTION: {invention.get('invention_name', 'Unknown')}

CURRENT SCORE: {score_result['total_score']}/100

CURRENT ISSUES:
{issues_str}

Analyze the invention and identify specific gaps or improvements needed.

Return ONLY a JSON object (no markdown, no code blocks):
{{"completeness_score": 75, "issues_found": ["issue1", "issue2"], "missing_elements": ["element1", "element2"], "recommendations": ["recommendation1", "recommendation2"], "needs_refinement": true}}"""

        result = self.execute(thought, prompt, iteration)

        validation = result["observation"]
        validation["score"] = score_result["total_score"]
        validation["detailed_breakdown"] = score_result["breakdown"]

        return validation

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
        return observation.get('completeness_score', 0)

    def _get_action_description(self) -> str:
        return "Validating extraction completeness and quality"

    def _format_observation(self, observation: Dict) -> str:
        score = observation.get('completeness_score', 0)
        issues = len(observation.get('issues_found', []))
        needs = observation.get('needs_refinement', False)
        return f"Score: {score}, Issues: {issues}, Needs refinement: {needs}"
