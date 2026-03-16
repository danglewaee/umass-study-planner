# Adaptive Study Planning Engine

A constraint-aware weekly study planner built around scheduling, replanning, and simulation instead of generic productivity UI.

## MVP
- CP-SAT planner for weekly schedules
- greedy heuristic baselines
- replanning with schedule stability penalty
- RL-assisted repair policy selection across multiple replanning strategies
- scenario simulation and benchmark harness
- FastAPI endpoints for planning, replanning, RL-assisted replanning, and simulation

## Run
```bash
python -m venv .venv
.venv\\Scripts\\python -m pip install -r requirements.txt
.venv\\Scripts\\python -m uvicorn api.main:app --port 8200
```

## Verify
```bash
.venv\\Scripts\\python -m unittest discover -s tests -v
.venv\\Scripts\\python benchmarks\\compare.py
.venv\\Scripts\\python benchmarks\\compare_rl.py
```

## Resume goal
Turn a student scheduling app into a measurable optimization/systems project.

## RL Extension
- `CP-SAT` remains the feasibility-preserving planner for initial schedules.
- A simulation-trained tabular RL agent selects between replanning strategies such as `stability_aware` and `deadline_rescue` after disruptions.
- Benchmarks live in `benchmarks/compare.py` and `benchmarks/compare_rl.py`.
