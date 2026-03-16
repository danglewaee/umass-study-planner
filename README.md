# BalanceOS MVP

Student planning system focused on balance, consistency, and adaptive replanning.

## Architecture
- `backend/app`: FastAPI API, task store, strategy-aware weekly planner, and replanning endpoints
- `ml`: repair-policy training and evaluation for RL-assisted strategy selection
- `frontend`: static dashboard that calls the backend API
- `tests`: planner and API integration coverage for the RL-assisted replanning flow

## What the current build does
- Parses brain-dump text into candidate tasks
- Generates weekly plans with one of four planner strategies:
  - `stability_aware`
  - `deadline_rescue`
  - `load_balance`
  - `focus_windows`
- Replans after delayed work while optionally preserving previously scheduled blocks
- Uses an RL-trained repair selector to choose the best replanning strategy for a disruption state
- Captures plan metrics such as preserved blocks, overload days, and focus-window alignment

## RL Pipeline
The RL layer does not replace the planner. It sits on top of the planner as a repair-policy selector:

1. `backend/app/planner.py` generates a baseline weekly plan.
2. A disruption happens, such as a delayed task or urgent follow-up.
3. `ml/repair_selector.py` encodes the repair state and chooses a planner strategy.
4. The planner reruns with `previous_plan` context to preserve useful blocks when possible.
5. API and evaluation endpoints expose the result and compare the learned selector against fixed strategies.

This keeps the repo aligned with the original scaffold while still integrating RL into the actual replanning loop.

## Key API endpoints
- `POST /planner/generate-week`
- `POST /planner/replan`
- `POST /planner/replan-rl`
- `GET /planner/strategies`
- `POST /ml/train-repair-selector`
- `POST /ml/evaluate-repair-selector`

## Run locally
1. Create and activate a virtual environment.
2. Install backend dependencies:
   `pip install -r backend/requirements.txt`
3. Start the API from the repo root:
   `uvicorn backend.app.main:app --reload`
4. Open `frontend/index.html` in a browser.

## Evaluate the RL selector
Train and evaluate the repair selector from the repo root:

```bash
python -m ml.evaluate_repair_selector
```

## Run tests
```bash
python -m unittest discover -s tests -v
```

## Notes
- The planner still uses heuristics, but it now exposes strategy-aware replanning and plan-quality metrics.
- The RL module learns when to apply each repair strategy instead of trying to generate schedules directly.
- Storage is still in-memory; PostgreSQL, Redis, auth, and richer optimization can be added later without rewriting the app shape.
