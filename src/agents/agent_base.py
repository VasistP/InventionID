from typing import Dict, Optional, Any
from llm_client import LLMClient
from utils.logger import InventionLogger


class AgentBase:
    def __init__(self, llm_client: LLMClient, logger: InventionLogger,
                 rate_limiter=None):
        self.llm = llm_client(model='gemini')
        self.logger = logger
        self.rate_limiter = rate_limiter
        self.name = self.__class__.__name__

    def execute(self, thought: str, action_prompt: str,
                iteration: int = 0) -> Dict[str, Any]:

        if self.rate_limiter:
            self.rate_limiter.acquire()

        response = self.llm.generate(
            action_prompt,
            files=None,
            max_tokens=4000,
            temperature=0.3
        )

        observation = self._parse_response(response)
        score = self._calculate_score(observation)

        action_desc = self._get_action_description()
        self.logger.log_agent(
            self.name,
            thought,
            action_desc,
            self._format_observation(observation),
            score,
            iteration
        )

        self.logger.log_api_call(self._estimate_cost(action_prompt, response))

        return {
            "thought": thought,
            "action": action_desc,
            "observation": observation,
            "score": score
        }

    def _parse_response(self, response: str) -> Any:
        raise NotImplementedError("Subclass must implement _parse_response")

    def _calculate_score(self, observation: Any) -> Optional[int]:
        return None

    def _get_action_description(self) -> str:
        raise NotImplementedError(
            "Subclass must implement _get_action_description")

    def _format_observation(self, observation: Any) -> str:
        if isinstance(observation, dict):
            return f"Extracted: {observation.get('invention_name', 'Unknown')}"
        return str(observation)

    def _estimate_cost(self, prompt: str, response: str) -> float:
        input_tokens = len(prompt.split()) * 1.3
        output_tokens = len(response.split()) * 1.3
        return (input_tokens * 3 / 1_000_000) + (output_tokens * 15 / 1_000_000)
