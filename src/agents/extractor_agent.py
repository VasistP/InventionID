from typing import Dict, Any
from .autonomous_agent import AutonomousAgent


class ExtractorAgent(AutonomousAgent):
    def __init__(self, llm_client, logger, tool_registry, rate_limiter=None):
        available_tools = ['pdf_reader', 'llm_extractor',
                           'section_reader', 'quick_validator', 'field_counter']
        super().__init__('ExtractorAgent', llm_client, logger,
                         tool_registry, available_tools, rate_limiter)

    def run(self, pdf_path: str, max_iterations: int = 10) -> Dict[str, Any]:
        self.state = {
            "pdf_path": pdf_path,
            "extraction": {},
            "iteration": 0,
            "agent_role": "extractor",
            "task": "extract invention from PDF"
        }

        for i in range(max_iterations):
            self.state["iteration"] = i + 1

            decision = self.decide_next_action(self.state)

            if decision.get('action') == 'complete':
                break

            params = decision.get('tool_params', {})
            if 'pdf_path' not in params:
                params['pdf_path'] = pdf_path

            decision['tool_params'] = params

            result = self.execute_action(decision, i + 1)

            if result["status"] == "success":
                if decision.get('action') == 'llm_extractor':
                    self.state["extraction"] = result["result"]
                elif decision.get('action') == 'quick_validator':
                    self.state["quick_check"] = result["result"]
                elif decision.get('action') == 'field_counter':
                    self.state["counts"] = result["result"]

            if self.state.get("extraction") and isinstance(self.state["extraction"], dict):
                if len(self.state["extraction"]) >= 8:
                    break

        return self.state.get("extraction", {})
