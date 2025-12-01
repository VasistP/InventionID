from typing import Dict, Any, List
from llm_client import LLMClient
from utils.logger import InventionLogger
from .tools import ToolRegistry
import json
import re


class AutonomousAgent:
    def __init__(self, agent_name: str, llm_client: LLMClient,
                 logger: InventionLogger, tool_registry: ToolRegistry,
                 available_tools: List[str], rate_limiter=None):
        self.name = agent_name
        self.llm = llm_client
        self.logger = logger
        self.tool_registry = tool_registry
        self.available_tools = tool_registry.get_tools(available_tools)
        self.rate_limiter = rate_limiter
        self.state = {}

    def decide_next_action(self, current_state: Dict) -> Dict[str, Any]:

        state_summary = json.dumps(current_state, indent=2)
        tool_names = list(self.available_tools.keys())

        prompt = f"""You are {self.name}, an autonomous agent working on patent invention extraction.

CURRENT STATE:
{state_summary}

AVAILABLE TOOLS:
{', '.join(tool_names)}

Decide what to do next. Analyze the current state and choose ONE action.

Return ONLY a JSON object:
{{
  "thought": "Your reasoning about what to do next",
  "action": "tool_name or 'complete'",
  "tool_params": {{"param1": "value1"}},
  "reason": "Why you chose this action"
}}

If the task is complete (score >= 85 or all fields adequate), set action to 'complete'."""

        response = self.llm.generate(
            prompt, files=None, max_tokens=1000, temperature=0.5)
        decision = self._parse_json(response)

        self.logger.logger.info(
            f"[{self.name}] DECISION - {decision.get('thought', 'No thought')}")
        self.logger.logger.info(
            f"[{self.name}] ACTION - {decision.get('action', 'unknown')}")

        return decision

    def execute_action(self, decision: Dict, iteration: int) -> Dict[str, Any]:
        action = decision.get('action', 'complete')

        if action == 'complete':
            return {"status": "complete", "result": None}

        if action not in self.available_tools:
            self.logger.logger.warning(f"[{self.name}] Unknown tool: {action}")
            return {"status": "error", "result": f"Unknown tool: {action}"}

        tool = self.available_tools[action]
        params = decision.get('tool_params', {})

        try:
            result = tool(**params)

            self.logger.logger.info(
                f"[{self.name}] OBSERVATION - Tool {action} executed")

            self.logger.log_agent(
                self.name,
                decision.get('thought', ''),
                f"Using tool: {action}",
                str(result)[:200],
                None,
                iteration
            )

            return {"status": "success", "result": result}
        except Exception as e:
            self.logger.logger.error(f"[{self.name}] ERROR - {str(e)}")
            return {"status": "error", "result": str(e)}

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
            return {"thought": "Parse error", "action": "complete", "tool_params": {}}
