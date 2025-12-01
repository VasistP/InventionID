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
            "score": 0,
            "agent_role": "validator",
            "task": "validate invention quality and identify issues"
        }

        validation_done = False

        for i in range(max_iterations):
            self.state["iteration"] = i + 1

            if not validation_done:
                params = {"invention": invention}
                decision = {
                    "thought": "Must validate invention quality",
                    "action": "validator",
                    "tool_params": params
                }

                result = self.execute_action(decision, i + 1)

                if result["status"] == "success":
                    self.state["validation_results"] = result["result"]
                    self.state["score"] = result["result"].get("score", 0)
                    validation_done = True
                    break
            else:
                decision = self.decide_next_action(self.state)

                if decision.get('action') == 'complete':
                    break

                params = decision.get('tool_params', {})
                if 'invention' not in params:
                    params['invention'] = invention

                decision['tool_params'] = params
                result = self.execute_action(decision, i + 1)

        return self.state.get("validation_results", {"score": 0, "issues": ["Validation failed"], "valid": False})
