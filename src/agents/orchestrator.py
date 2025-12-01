from typing import Dict, Optional
from llm_client import LLMClient
from utils.logger import InventionLogger
from utils.scoring import InventionScorer
from .document_analysis_agent import DocumentAnalysisAgent
from .extraction_agent import ExtractionAgent
from .classification_agent import ClassificationAgent
from .validation_agent import ValidationAgent
from .refinement_agent import RefinementAgent


class Orchestrator:
    def __init__(self, llm_client: LLMClient, logger: InventionLogger,
                 rate_limiter=None, score_threshold: int = 85,
                 max_iterations: int = 3):
        self.llm = llm_client
        self.logger = logger
        self.rate_limiter = rate_limiter
        self.score_threshold = score_threshold
        self.max_iterations = max_iterations
        self.scorer = InventionScorer()

        self.doc_agent = DocumentAnalysisAgent(
            llm_client, logger, rate_limiter)
        self.ext_agent = ExtractionAgent(llm_client, logger, rate_limiter)
        self.cls_agent = ClassificationAgent(llm_client, logger, rate_limiter)
        self.val_agent = ValidationAgent(llm_client, logger, rate_limiter)
        self.ref_agent = RefinementAgent(llm_client, logger, rate_limiter)

    def orchestrate(self, pdf_path: str) -> Dict:
        self.logger.log_start(pdf_path)

        doc_analysis = self.doc_agent.analyze(pdf_path, iteration=0)

        current_invention = self.ext_agent.extract(
            pdf_path, doc_analysis, iteration=1)

        current_invention = self.cls_agent.classify(
            current_invention, iteration=2)

        iteration = 3
        for refinement_round in range(self.max_iterations):
            validation = self.val_agent.validate(
                current_invention, iteration=iteration)
            current_score = validation.get('score', 0)

            if current_score >= self.score_threshold:
                break

            if not validation.get('needs_refinement', False):
                break

            iteration += 1
            current_invention = self.ref_agent.refine(
                current_invention,
                validation,
                pdf_path,
                iteration=iteration
            )
            iteration += 1

        final_score_result = self.scorer.score_invention(current_invention)
        final_score = final_score_result['total_score']

        output_path = f"data/{pdf_path.split('/')[-1].replace('.pdf', '_inventions.json')}"
        self.logger.log_success(iteration, final_score, output_path)

        return {
            "invention": current_invention,
            "score": final_score_result,
            "iterations": iteration,
            "threshold_met": final_score >= self.score_threshold
        }
