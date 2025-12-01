from typing import Dict, Any
from .autonomous_agent import AutonomousAgent


class RefinerAgent(AutonomousAgent):
    def __init__(self, llm_client, logger, tool_registry, rate_limiter=None):
        available_tools = ['llm_extractor', 'field_enhancer',
                           'section_reader', 'field_counter', 'quick_validator']
        super().__init__('RefinerAgent', llm_client, logger,
                         tool_registry, available_tools, rate_limiter)

    def run(self, invention: Dict, validation: Dict, pdf_path: str, max_iterations: int = 5) -> Dict[str, Any]:
        self.state = {
            "invention": invention,
            "validation": validation,
            "pdf_path": pdf_path,
            "iteration": 0,
            "refinements": [],
            "agent_role": "refiner",
            "task": "refine invention based on validation issues"
        }

        issues = validation.get("issues", [])
        missing_fields = validation.get("missing_fields", [])

        if not issues and not missing_fields:
            return invention

        for i in range(max_iterations):
            self.state["iteration"] = i + 1

            decision = self.decide_next_action(self.state)

            if decision.get('action') == 'complete':
                break

            params = decision.get('tool_params', {})

            if decision.get('action') == 'section_reader' and 'pdf_path' not in params:
                params['pdf_path'] = pdf_path

            if decision.get('action') == 'field_enhancer':
                if 'invention_context' not in params:
                    params['invention_context'] = invention

            if decision.get('action') == 'llm_extractor':
                if 'pdf_path' not in params:
                    params['pdf_path'] = pdf_path
                if 'context' not in params:
                    params['context'] = f"Issues to fix: {', '.join(issues)}"

            decision['tool_params'] = params

            result = self.execute_action(decision, i + 1)

            if result["status"] == "success":
                if decision.get('action') == 'field_enhancer':
                    field_name = params.get('field_name')
                    if field_name and isinstance(result["result"], str):
                        self.state["invention"][field_name] = result["result"]
                        self.state["refinements"].append(field_name)
                elif decision.get('action') == 'llm_extractor':
                    if isinstance(result["result"], dict):
                        self.state["invention"].update(result["result"])

        return self.state.get("invention", invention)
