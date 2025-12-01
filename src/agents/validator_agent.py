from typing import Dict, Any
from .autonomous_agent import AutonomousAgent


class ValidatorAgent(AutonomousAgent):
    def __init__(self, llm_client, logger, tool_registry, rate_limiter=None):
        available_tools = ['validator', 'quick_validator', 'field_counter']
        super().__init__('ValidatorAgent', llm_client, logger,
                         tool_registry, available_tools, rate_limiter)

    def run(self, invention: Dict, max_iterations: int = 3) -> Dict[str, Any]:
        self.state = {
            "invention": invention,
            "validation_results": {},
            "iteration": 0,
            "score": 0
        }

        for i in range(max_iterations):
            self.state["iteration"] = i + 1

            decision = self.decide_next_action(self.state)

            if decision.get('action') == 'complete':
                break

            if 'invention' not in decision.get('tool_params', {}):
                decision['tool_params']['invention'] = invention

            result = self.execute_action(decision, i + 1)

            if result["status"] == "success":
                if decision.get('action') == 'validator':
                    self.state["validation_results"] = result["result"]
                    self.state["score"] = result["result"].get("score", 0)
                    break

        return self.state["validation_results"]
