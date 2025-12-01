from typing import Dict, Any
from llm_client import LLMClient
from utils.logger import InventionLogger
from utils.scoring import InventionScorer
from .tools import ToolRegistry
from .extractor_agent import ExtractorAgent
from .validator_agent import ValidatorAgent
from .refiner_agent import RefinerAgent
import config


class AutonomousOrchestrator:
    def __init__(self, llm_client: LLMClient, logger: InventionLogger, rate_limiter=None):

        self.logger = logger
        self.llm = llm_client
        self.rate_limiter = rate_limiter
        self.scorer = InventionScorer()
        self.tool_registry = ToolRegistry(llm_client, rate_limiter)

        self.extractor = ExtractorAgent(
            llm_client, logger, self.tool_registry, rate_limiter)
        self.validator = ValidatorAgent(
            llm_client, logger, self.tool_registry, rate_limiter)
        self.refiner = RefinerAgent(
            llm_client, logger, self.tool_registry, rate_limiter)

        self.api_calls = 0
        self.max_api_calls = config.MAX_API_CALLS_PER_EXTRACTION

    def orchestrate(self, pdf_path: str) -> Dict[str, Any]:
        self.logger.log_start(pdf_path)
        self.api_calls = 0

        extraction_iterations = min(8, self.max_api_calls // 3)
        invention = self.extractor.run(
            pdf_path, max_iterations=extraction_iterations)
        self.api_calls += self.extractor.state.get("iteration", 0)

        if not invention or self.api_calls >= self.max_api_calls:
            return self._finalize({}, 0, self.api_calls)

        validation_iterations = min(2, self.max_api_calls - self.api_calls)
        if validation_iterations <= 0:
            return self._finalize(invention, 0, self.api_calls)

        validation_result = self.validator.run(
            invention, max_iterations=validation_iterations)
        self.api_calls += self.validator.state.get("iteration", 0)
        current_score = validation_result.get("score", 0)

        refinement_rounds = 0
        max_refinement_rounds = 3

        while current_score < 85 and refinement_rounds < max_refinement_rounds and self.api_calls < self.max_api_calls:
            remaining_calls = self.max_api_calls - self.api_calls
            refinement_iterations = min(5, remaining_calls // 2)

            if refinement_iterations <= 0:
                break

            invention = self.refiner.run(
                invention, validation_result, pdf_path, max_iterations=refinement_iterations)
            self.api_calls += self.refiner.state.get("iteration", 0)

            if self.api_calls >= self.max_api_calls:
                break

            validation_iterations = min(2, self.max_api_calls - self.api_calls)
            if validation_iterations <= 0:
                break

            validation_result = self.validator.run(
                invention, max_iterations=validation_iterations)
            self.api_calls += self.validator.state.get("iteration", 0)
            current_score = validation_result.get("score", 0)

            refinement_rounds += 1

            if current_score >= 85:
                break

        return self._finalize(invention, current_score, self.api_calls)

    def _finalize(self, invention: Dict, score: int, total_calls: int) -> Dict[str, Any]:
        final_score_result = self.scorer.score_invention(invention) if invention else {
            "total_score": 0,
            "rating": "⭐ Inadequate",
            "breakdown": {},
            "issues": ["No invention extracted"]
        }

        final_score = final_score_result["total_score"]

        output_path = "data/invention_output.json"
        self.logger.log_success(total_calls, final_score, output_path)

        return {
            "invention": invention,
            "score": final_score_result,
            "total_api_calls": total_calls,
            "threshold_met": final_score >= 85,
            "budget_exceeded": total_calls >= self.max_api_calls
        }
