import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


class InventionLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.agents_dir = self.log_dir / "agents"
        self.agents_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"invention_extraction_{timestamp}.log"

        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.session_start = datetime.now()
        self.total_cost = 0
        self.api_calls = 0

    def log_agent(self, agent_name: str, thought: str, action: str,
                  observation: str, score: Optional[int], iteration: int = 0):
        self.logger.info(f"AGENT - {agent_name}")
        self.logger.info(f'THOUGHT - "{thought}"')
        self.logger.info(f"ACTION - {action}")
        self.logger.info(f'OBSERVATION - "{observation}"')

        if score is not None:
            stars = self._get_stars(score)
            self.logger.info(f"SCORE - {score}/100 {stars}")
        else:
            self.logger.info(f"SCORE - N/A")

        self._save_agent_detail(agent_name, thought, action, observation,
                                score, iteration)

    def log_start(self, pdf_path: str):
        self.logger.info("Starting invention extraction")
        self.logger.info(f"PDF: {pdf_path}")
        self.logger.info("=" * 60)

    def log_success(self, iterations: int, final_score: int, output_path: str):
        self.logger.info("=" * 60)
        stars = self._get_stars(final_score)
        self.logger.info(
            f"SUCCESS - Extraction complete ({iterations} iterations)")
        self.logger.info(f"FINAL_SCORE - {final_score}/100 {stars}")
        self.logger.info(f"OUTPUT - Saved to {output_path}")
        self.logger.info(
            f"COST - ${self.total_cost:.2f} ({self.api_calls} API calls)")

    def log_api_call(self, cost: float):
        self.total_cost += cost
        self.api_calls += 1

    def _get_stars(self, score: int) -> str:
        if score >= 90:
            return "5/5"
        if score >= 80:
            return "4/5"
        if score >= 70:
            return "3/5"
        if score >= 60:
            return "2/5"
        return "1/5"

    def _save_agent_detail(self, agent_name: str, thought: str, action: str,
                           observation: str, score: Optional[int], iteration: int):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{agent_name.lower()}_iter{iteration}_{timestamp}.json"
        filepath = self.agents_dir / filename

        data = {
            "agent": agent_name,
            "timestamp": datetime.now().isoformat(),
            "iteration": iteration,
            "thought": thought,
            "action": action,
            "observation": observation,
            "score": score
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
