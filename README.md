# UMass Study Partner

UMass Study Partner is an adaptive planning system for students who need a week they can actually follow, not just an idealized schedule.

The current build combines a stronger product-facing dashboard with the repo's strategy-aware planning and RL-assisted replanning logic.

## Architecture
- `backend/app`: FastAPI API, task store, strategy-aware weekly planner, and replanning endpoints
- `ml`: repair-policy training and evaluation for RL-assisted strategy selection
- `frontend`: static dashboard for planning, repair runs, and check-ins
- `tests`: planner and API integration coverage for the adaptive repair flow

## What the current build does
- Parses brain-dump text into candidate tasks
- Stores recurring fixed commitments such as classes, work shifts, clubs, and commute blocks
- Generates weekly plans with one of four planner strategies:
  - `stability_aware`
  - `deadline_rescue`
  - `load_balance`
  - `focus_windows`
- Replans after delayed work while optionally preserving previously scheduled blocks
- Trains an RL repair selector and uses it to choose the best replanning strategy for a disruption state
- Surfaces plan metrics such as preserved blocks, overload days, scheduled tasks, and focus-window alignment
- Exposes a dashboard flow for comparing hand-picked repair strategies against RL-selected repair

## Adaptive Repair Loop
The learning layer does not generate schedules directly. It selects the repair policy that should be applied after a disruption:

1. `backend/app/planner.py` generates a baseline weekly plan.
2. A disruption happens, such as a slipped task or urgent follow-up.
3. `ml/repair_selector.py` encodes the repair state and chooses a planner strategy.
4. The planner reruns with `previous_plan` context to preserve useful blocks when possible.
5. The dashboard and API expose the result, including the chosen strategy and plan metrics.

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

The local build now stores data in SQLite and scopes tasks, check-ins, commitments, and preferences by profile id. The frontend defaults to `demo-user`, and the API also accepts `X-Profile-Id` for switching between students.

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
- The planner remains heuristic-based, but it now exposes strategy-aware replanning and plan-quality metrics that are useful in a product demo.
- The RL module learns when to apply each repair strategy instead of trying to generate schedules directly.
- Storage is still in-memory; PostgreSQL, Redis, auth, and richer optimization can be added later without rewriting the app shape.
