from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rl import evaluate_repair_agent, train_repair_agent

OUT = ROOT / "benchmarks" / "latest_rl_results.json"


if __name__ == "__main__":
    agent = train_repair_agent(episodes=60, seed=11)
    results = evaluate_repair_agent(agent, count=50, seed=1011)
    OUT.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
