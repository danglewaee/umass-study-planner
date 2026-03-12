# BalanceOS MVP

Python-only scaffold for a student planning system that optimizes for balance, consistency, and progress.

## Structure
- `backend/app`: FastAPI application and planner logic
- `frontend`: static dashboard that calls the backend API

## Planned MVP capabilities
- Brain-dump task intake
- Weekly planner generation
- Adaptive replanning for missed work
- Check-ins and workload alerts
- Personalized schedule heuristics using simple behavioral history

## Run locally
1. Create a virtual environment.
2. Install backend dependencies:
   `pip install -r backend/requirements.txt`
3. Start the API from `balanceos/backend`:
   `uvicorn app.main:app --reload`
4. Open `balanceos/frontend/index.html` in a browser.

## Notes
- The current planner is heuristic-based and uses in-memory storage.
- The project is structured so PostgreSQL, Redis, auth, and richer optimization can be added later without rewriting the app shape.
