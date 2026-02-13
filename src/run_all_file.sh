#!/usr/bin/env bash
set -uo pipefail
export SERPAPI_KEY="a794f1554124f18814caf7a3d1929cf514512e451c3836f93a0a93827b0ecd12"
PYTHON=python3
SCRIPT="src/full_pipeline_cached.py"
LOG_FILE="run.log"

pdfs=(
  # "input/Kim et al. - 2024 - MDAgents An Adaptive Collaboration of LLMs for Medical Decision-Making.pdf"
  # "input/Multi-Quadruped Cooperative Object Transport: Learning Decentralized Pinch-Lift-Move.pdf"
  # "input/OSU-22-05_publication.pdf"
  # "input/OSU-23-14_publication.pdf"
  # "input/OSU-23-35_publication.pdf"
  # "input/OSU-24-36_publication.pdf"
  "input/OSU-24-37_publication.pdf"
  # "input/cyclotomic040425.pdf"
  # "input/fibarray.pdf"
  # "input/OSU-24-48_publication.pdf"
  # "input/OSU-24-65_publication.pdf"
  # "input/OSU-25-13_publication.pdf"
)

# clear old log
# : > "$LOG_FILE"

for pdf in "${pdfs[@]}"; do
  echo "============================================================" | tee -a "$LOG_FILE"
  echo "Running: $pdf" | tee -a "$LOG_FILE"
  echo "============================================================" | tee -a "$LOG_FILE"

  python3 -u "$SCRIPT" "$pdf" 2>&1 | tee -a "$LOG_FILE"
done
