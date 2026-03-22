from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from ml.repair_selector import TrainedRepairSelector, evaluate_repair_selector, replan_with_selector, train_repair_selector
from . import google_calendar
from .models import (
    BrainDumpRequest,
    BrainDumpResponse,
    CheckInInput,
    FixedCommitment,
    FixedCommitmentInput,
    GoogleAuthStartResponse,
    GoogleCalendarSummary,
    GoogleConnectionStatus,
    GoogleImportRequest,
    GoogleImportResponse,
    HealthResponse,
    RepairEvaluationRequest,
    RLReplanResponse,
    RLTrainRequest,
    RLTrainResponse,
    ReplanRequest,
    Task,
    TaskInput,
    UserInsights,
    UserPreferences,
    WeeklyPlanRequest,
    WeeklyPlanResponse,
)
from .planner import available_strategies, derive_user_insights, generate_weekly_plan, parse_brain_dump
from .store import DEFAULT_PROFILE_ID, store

app = FastAPI(title="UMass Study Partner API", version="0.1.0")
trained_selector: TrainedRepairSelector | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def resolve_profile_id(x_profile_id: Annotated[str | None, Header()] = None) -> str:
    return (x_profile_id or DEFAULT_PROFILE_ID).strip() or DEFAULT_PROFILE_ID


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _google_status(profile_id: str) -> GoogleConnectionStatus:
    config = google_calendar.settings()
    connection = store.get_google_connection(profile_id)
    if not config.is_configured():
        return GoogleConnectionStatus(
            configured=False,
            connected=connection is not None,
            connected_email=connection.email if connection else None,
            last_synced_at=connection.last_synced_at if connection else None,
            message="Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI to enable Google Calendar sync.",
        )
    if not connection:
        return GoogleConnectionStatus(
            configured=True,
            connected=False,
            message="Google Calendar is configured but not connected for this student profile yet.",
        )
    return GoogleConnectionStatus(
        configured=True,
        connected=True,
        connected_email=connection.email,
        last_synced_at=connection.last_synced_at,
        message="Google Calendar connected.",
    )


def _ensure_google_connection(profile_id: str):
    config = google_calendar.settings()
    if not config.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google Calendar sync is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI.",
        )

    connection = store.get_google_connection(profile_id)
    if not connection:
        raise HTTPException(status_code=404, detail="No Google Calendar connection found for this student profile.")

    expiry = _coerce_utc(connection.token_expiry)
    if expiry and expiry <= datetime.now(UTC) + timedelta(minutes=2):
        if not connection.refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Google connection has no refresh token. Reconnect this profile to Google Calendar.",
            )
        try:
            refreshed = google_calendar.refresh_access_token(connection.refresh_token)
        except Exception as exc:  # pragma: no cover - network/provider failure path
            raise HTTPException(status_code=502, detail=f"Failed to refresh Google access token: {exc}") from exc

        connection = store.upsert_google_connection(
            profile_id,
            email=connection.email,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token or connection.refresh_token,
            scope=refreshed.scope or connection.scope,
            token_expiry=refreshed.expires_at,
        )
    return connection


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/integrations/google/status", response_model=GoogleConnectionStatus)
def google_status(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> GoogleConnectionStatus:
    return _google_status(profile_id)


@app.get("/integrations/google/start", response_model=GoogleAuthStartResponse)
def start_google_oauth(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> GoogleAuthStartResponse:
    if not google_calendar.settings().is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google Calendar sync is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI.",
        )
    state = store.create_oauth_state("google", profile_id)
    return GoogleAuthStartResponse(authorization_url=google_calendar.build_authorization_url(state))


@app.get("/oauth/google/callback", response_class=HTMLResponse)
def google_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> HTMLResponse:
    if error:
        return HTMLResponse(
            f"<html><body><h1>Google connection failed</h1><p>{error}</p></body></html>",
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse(
            "<html><body><h1>Missing Google OAuth data</h1><p>Expected both code and state.</p></body></html>",
            status_code=400,
        )

    profile_id = store.consume_oauth_state("google", state)
    if not profile_id:
        return HTMLResponse(
            "<html><body><h1>Expired Google connection state</h1><p>Start the Google connect flow again from the dashboard.</p></body></html>",
            status_code=400,
        )

    try:
        token_bundle = google_calendar.exchange_code_for_tokens(code)
        email = google_calendar.fetch_connected_email(token_bundle.access_token)
        existing = store.get_google_connection(profile_id)
        refresh_token = token_bundle.refresh_token or (existing.refresh_token if existing else "")
        if not refresh_token:
            return HTMLResponse(
                "<html><body><h1>Google connection incomplete</h1><p>No refresh token was returned. Try connecting again and grant offline access.</p></body></html>",
                status_code=400,
            )
        store.upsert_google_connection(
            profile_id,
            email=email,
            access_token=token_bundle.access_token,
            refresh_token=refresh_token,
            scope=token_bundle.scope,
            token_expiry=token_bundle.expires_at,
        )
    except Exception as exc:  # pragma: no cover - network/provider failure path
        return HTMLResponse(
            f"<html><body><h1>Google connection failed</h1><p>{exc}</p></body></html>",
            status_code=502,
        )

    return HTMLResponse(
        "<html><body><h1>Google Calendar connected</h1><p>You can close this tab and refresh the dashboard.</p></body></html>"
    )


@app.get("/integrations/google/calendars", response_model=list[GoogleCalendarSummary])
def google_calendars(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> list[GoogleCalendarSummary]:
    connection = _ensure_google_connection(profile_id)
    try:
        return google_calendar.list_calendars(connection.access_token)
    except Exception as exc:  # pragma: no cover - network/provider failure path
        raise HTTPException(status_code=502, detail=f"Failed to fetch Google calendars: {exc}") from exc


@app.post("/integrations/google/import-commitments", response_model=GoogleImportResponse)
def import_google_commitments(
    payload: GoogleImportRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> GoogleImportResponse:
    connection = _ensure_google_connection(profile_id)
    window_start = datetime.now(UTC)
    window_end = window_start + timedelta(days=payload.lookahead_days)

    try:
        events = google_calendar.list_events(connection.access_token, payload.calendar_id, window_start, window_end)
    except Exception as exc:  # pragma: no cover - network/provider failure path
        raise HTTPException(status_code=502, detail=f"Failed to fetch Google Calendar events: {exc}") from exc

    candidates, skipped_events = google_calendar.infer_weekly_commitments(events)
    imported_commitments = 0
    updated_commitments = 0
    imported_titles: list[str] = []

    for candidate in candidates:
        commitment, created = store.upsert_google_commitment(
            candidate.commitment,
            profile_id,
            external_ref=candidate.source_ref,
            calendar_id=payload.calendar_id,
        )
        imported_titles.append(commitment.title)
        if created:
            imported_commitments += 1
        else:
            updated_commitments += 1

    store.touch_google_sync(profile_id)
    return GoogleImportResponse(
        calendar_id=payload.calendar_id,
        imported_commitments=imported_commitments,
        updated_commitments=updated_commitments,
        skipped_events=skipped_events,
        imported_titles=sorted(set(imported_titles)),
        message=(
            "Imported repeating timed events into fixed commitments. "
            "One-off or all-day events were skipped by design."
        ),
    )


@app.delete("/integrations/google/connection", status_code=204)
def disconnect_google(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Response:
    store.clear_google_connection(profile_id)
    return Response(status_code=204)


@app.get("/tasks", response_model=list[Task])
def list_tasks(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> list[Task]:
    return store.list_tasks(profile_id)


@app.post("/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskInput, profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Task:
    return store.add_task(payload, profile_id)


@app.post("/tasks/brain-dump", response_model=BrainDumpResponse)
def brain_dump(payload: BrainDumpRequest) -> BrainDumpResponse:
    parsed = parse_brain_dump(payload.text)
    tasks = [TaskInput(**item) for item in parsed]
    return BrainDumpResponse(tasks=tasks)


@app.get("/commitments", response_model=list[FixedCommitment])
def list_commitments(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> list[FixedCommitment]:
    return store.list_commitments(profile_id)


@app.post("/commitments", response_model=FixedCommitment, status_code=201)
def create_commitment(
    payload: FixedCommitmentInput,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> FixedCommitment:
    return store.add_commitment(payload, profile_id)


@app.delete("/commitments/{commitment_id}", status_code=204)
def delete_commitment(commitment_id: str, profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Response:
    deleted = store.delete_commitment(commitment_id, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Commitment not found")
    return Response(status_code=204)


@app.get("/preferences", response_model=UserPreferences)
def get_preferences(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> UserPreferences:
    return store.get_preferences(profile_id)


@app.put("/preferences", response_model=UserPreferences)
def update_preferences(
    payload: UserPreferences,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> UserPreferences:
    return store.set_preferences(payload, profile_id)


@app.post("/planner/generate-week", response_model=WeeklyPlanResponse)
def generate_plan(
    payload: WeeklyPlanRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> WeeklyPlanResponse:
    preferences = payload.preferences or store.get_preferences(profile_id)
    if payload.preferences:
        store.set_preferences(payload.preferences, profile_id)
    return generate_weekly_plan(
        store.list_tasks(profile_id),
        payload.week_start,
        preferences,
        strategy=payload.strategy,
        commitments=store.list_commitments(profile_id),
    )


@app.post("/planner/replan", response_model=WeeklyPlanResponse)
def replan(
    payload: ReplanRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> WeeklyPlanResponse:
    current_tasks = store.list_tasks(profile_id)
    preferences = store.get_preferences(profile_id)
    commitments = store.list_commitments(profile_id)
    previous_plan = generate_weekly_plan(current_tasks, payload.week_start, preferences, commitments=commitments)
    task = store.mark_delayed(payload.task_id, profile_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    plan = generate_weekly_plan(
        store.list_tasks(profile_id),
        payload.week_start,
        preferences,
        strategy=payload.strategy or previous_plan.strategy_used,
        previous_plan=previous_plan,
        commitments=commitments,
    )
    plan.alerts.append(f"Replanned after delay: {payload.reason}")
    return plan


@app.post("/planner/replan-rl", response_model=RLReplanResponse)
def replan_with_rl(
    payload: ReplanRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> RLReplanResponse:
    global trained_selector
    current_tasks = store.list_tasks(profile_id)
    preferences = store.get_preferences(profile_id)
    commitments = store.list_commitments(profile_id)
    previous_plan = generate_weekly_plan(current_tasks, payload.week_start, preferences, commitments=commitments)
    task = store.mark_delayed(payload.task_id, profile_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if trained_selector is None:
        trained_selector = train_repair_selector()

    latest_check_ins = store.list_check_ins(profile_id)
    latest_stress = latest_check_ins[-1].stress_level if latest_check_ins else None
    chosen, state, result = replan_with_selector(
        store.list_tasks(profile_id),
        payload.week_start,
        preferences,
        previous_plan,
        payload.task_id,
        trained_selector,
        stress_level=latest_stress,
    )
    result.alerts.append(f"RL-selected repair strategy '{chosen.value}' after delay: {payload.reason}")
    return RLReplanResponse(chosen_strategy=chosen, encoded_state=state, result=result)


@app.get("/planner/strategies")
def list_strategies() -> dict[str, list[str]]:
    return {"strategies": available_strategies()}


@app.post("/checkins", response_model=UserInsights)
def create_check_in(
    payload: CheckInInput,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> UserInsights:
    store.add_check_in(payload, profile_id)
    return derive_user_insights(store.list_tasks(profile_id), payload.stress_level)


@app.get("/insights", response_model=UserInsights)
def get_insights(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> UserInsights:
    latest_check_ins = store.list_check_ins(profile_id)
    latest_stress = latest_check_ins[-1].stress_level if latest_check_ins else None
    return derive_user_insights(store.list_tasks(profile_id), latest_stress)


@app.post("/ml/train-repair-selector", response_model=RLTrainResponse)
def train_selector(payload: RLTrainRequest) -> RLTrainResponse:
    global trained_selector
    trained_selector = train_repair_selector(episodes=payload.episodes, seed=payload.seed)
    return RLTrainResponse(**trained_selector.summary())


@app.post("/ml/evaluate-repair-selector")
def evaluate_selector(payload: RepairEvaluationRequest) -> dict:
    agent = train_repair_selector(episodes=payload.training_episodes, seed=payload.seed)
    return evaluate_repair_selector(agent, count=payload.evaluation_scenarios, seed=payload.seed + 1_000)


@app.get("/demo/seed-plan", response_model=WeeklyPlanResponse)
def seed_plan(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> WeeklyPlanResponse:
    tasks = store.list_tasks(profile_id)
    today = tasks[0].deadline if tasks else None
    week_start = today - timedelta(days=today.weekday()) if today else None
    if not week_start:
        raise HTTPException(status_code=400, detail="No tasks available")
    return generate_weekly_plan(
        tasks,
        week_start,
        store.get_preferences(profile_id),
        commitments=store.list_commitments(profile_id),
    )

