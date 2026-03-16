from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from simulation.runner import run_simulation

OUT = ROOT / "benchmarks" / "latest_results.json"


if __name__ == "__main__":
    results = run_simulation(count=50, seed=7)
    OUT.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
