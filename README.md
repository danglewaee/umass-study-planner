# UMass Study Partner

UMass Study Partner is an adaptive planning system for students who need a week they can actually follow, not just an idealized schedule.

The current build combines a product-facing web app with strategy-aware planning, bounded replanning, and import paths for the student data that actually shapes a week.

## Product framing
- Who uses it:
  overloaded students who are balancing coursework, commitments, and deadline changes week to week
- What decision becomes easier:
  "How should I reshape this week after a slip, a new deadline, or a packed calendar?"
- What evidence exists today:
  internal planner benchmarks, simulation coverage, and end-to-end beta flows in the app

Important:
- This repo is not claiming pilot impact yet.
- Current benchmark claims should be labeled as benchmark or simulation, not real user outcomes.
- The deployable beta is ready for private testing, but evidence from real students still needs a pilot.

## Architecture
- `backend/app`: FastAPI API, SQLite-backed auth/store, strategy-aware weekly planner, saved-plan persistence, and replanning endpoints
- `ml`: repair-policy training and evaluation for RL-assisted strategy selection
- `frontend`: account-aware dashboard for planning, repair runs, imports, and check-ins
- `tests`: planner and API integration coverage for the adaptive repair flow

## What the current build does
- Registers users, creates session tokens, and scopes planner data to authenticated accounts
- Saves the latest weekly plan for a student account so a generated week survives refreshes
- Supports manual task CRUD for beta users who have not connected external systems yet
- Parses brain-dump text into candidate tasks
- Stores recurring fixed commitments such as classes, work shifts, clubs, and commute blocks
- Supports account-scoped Google Calendar connection state and recurring event import into fixed commitments
- Supports account-scoped Canvas connection state and assignment import into academic tasks
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
3. Optional for Google Calendar sync: set these environment variables before starting the API:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI`
   Example redirect URI for local development:
   `http://127.0.0.1:8000/oauth/google/callback`
4. Start the API from the repo root:
   `uvicorn backend.app.main:app --reload`
5. Open `http://127.0.0.1:8000/` in a browser.

The local build stores data in SQLite and now supports both:
- authenticated account sessions for real beta users
- `X-Profile-Id` fallback for local demo mode and automated tests

## Google Calendar Sync
The Google Calendar integration is wired into the API and dashboard, but it only becomes active after you provide Google OAuth credentials.

1. Create a Google Cloud project.
2. Enable the Google Calendar API.
3. Configure the OAuth consent screen.
4. Create an OAuth client of type `Web application`.
5. Add a redirect URI that points back to the FastAPI callback, for example:
   `http://127.0.0.1:8000/oauth/google/callback`
6. Start the backend with the Google env vars set.
7. In the planner page, sign in, click `Connect Google`, authorize the student account, refresh status, then import repeating timed events into fixed commitments.

Current import behavior:
- Only timed events that repeat clearly over the lookahead window are imported into `commitments`
- All-day events and one-off calendar events are skipped on purpose
- Re-importing the same calendar updates existing imported commitments instead of duplicating them

## Canvas Import
The Canvas integration is implemented as a practical prototype path for students: it uses a Canvas base URL plus a personal access token, then imports assignments with due dates into academic tasks.

Typical flow:
1. Find your Canvas base URL, for example `https://umass.instructure.com`
2. Create a personal access token in your Canvas account
3. Open the `Tasks` page in the dashboard
4. Paste the Canvas base URL and token, then click `Connect Canvas`
5. Choose a course and import assignments into tasks

Current import behavior:
- Only assignments with a due date are imported
- Re-importing the same Canvas assignment updates the existing task instead of duplicating it
- Imported tasks are labeled with their Canvas course name to make multi-course planning easier

## Deployable beta checklist
- account auth and session flow
- SQLite persistence for tasks, preferences, commitments, imports, and latest weekly plan
- manual task CRUD
- weekly plan generation and bounded replanning
- Google Calendar recurring-event import
- Canvas assignment import
- dashboard served directly from FastAPI at `/`

This is a reasonable private beta shape.
It is not yet a production launch shape because secrets, OAuth hardening, usage logging, and pilot evidence still need another pass.

## Deploy the beta
Recommended first host: Railway.

Why this is the current recommendation:
- the repo already ships with a Dockerfile
- FastAPI serves the frontend directly, so you only need one web service
- the beta still uses SQLite, so a mounted volume is the shortest path to persistent storage

Suggested Railway setup:
1. Create a new service from this GitHub repo.
2. Let Railway build from the included `Dockerfile`.
3. Add a volume and mount it to a path such as `/data`.
4. Set `STUDY_PARTNER_DB_PATH=/data/study_partner.sqlite3`
5. Set Google env vars if you want Calendar sync:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI`
6. Point the healthcheck to `/health`
7. Open the deployed root URL and create a beta account

Deploy note:
- Railway injects `PORT`; the Dockerfile now respects it automatically.
- If you do not mount a volume, SQLite will be ephemeral and beta user data can disappear on redeploy.

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
- The planner remains hybrid: heuristic and OR-Tools planner engines are both available, and the app can compare them side by side.
- The RL module learns when to apply each repair strategy instead of trying to generate schedules directly.
- Storage now persists to SQLite; PostgreSQL, encrypted token storage, stronger auth hardening, and richer optimization can be added later without rewriting the app shape.
