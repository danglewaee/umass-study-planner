from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ml.repair_selector import TrainedRepairSelector, evaluate_repair_selector, replan_with_selector, train_repair_selector
from . import canvas, google_calendar
from .models import (
    AnalyticsSessionStartInput,
    AuthLoginInput,
    AuthSessionResponse,
    AuthStatusResponse,
    AuthRegisterInput,
    BrainDumpRequest,
    BrainDumpResponse,
    CanvasConnectionInput,
    CanvasConnectionStatus,
    CanvasCourseSummary,
    CanvasImportRequest,
    CanvasImportResponse,
    CheckInInput,
    FixedCommitment,
    FixedCommitmentInput,
    GoogleAuthStartResponse,
    GoogleCalendarSummary,
    GoogleConnectionStatus,
    GoogleImportRequest,
    GoogleImportResponse,
    HealthResponse,
    PlanStrategy,
    PlannerCompareRequest,
    PlannerCompareResponse,
    PlannerComparisonEntry,
    RepairEvaluationRequest,
    RLReplanResponse,
    RLTrainRequest,
    RLTrainResponse,
    ReplanRequest,
    SavedPlanResponse,
    Task,
    TaskInput,
    TaskUpdateInput,
    UsageAnalyticsSummary,
    UserInsights,
    UserPreferences,
    WeeklyPlanRequest,
    WeeklyPlanResponse,
)
from .planner import available_strategies, derive_user_insights, parse_brain_dump
from .planner_engine import (
    PlannerRequest,
    available_planner_engines,
    default_planner_engine,
    generate_plan as generate_plan_with_engine,
)
from .store import DEFAULT_PROFILE_ID, store

app = FastAPI(title="UMass Study Partner API", version="0.1.0")
trained_selector: TrainedRepairSelector | None = None
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def resolve_profile_id(
    authorization: Annotated[str | None, Header()] = None,
    x_profile_id: Annotated[str | None, Header()] = None,
) -> str:
    token = _extract_bearer_token(authorization)
    if token:
        user = store.get_user_by_session_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return user.id
    return (x_profile_id or DEFAULT_PROFILE_ID).strip() or DEFAULT_PROFILE_ID


def require_authenticated_user(authorization: Annotated[str | None, Header()] = None):
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = store.get_user_by_session_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return user, token


def _log_usage(profile_id: str, event_type: str, **metadata: object) -> None:
    store.log_usage_event(profile_id, event_type, metadata=metadata)


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


def _canvas_status(profile_id: str) -> CanvasConnectionStatus:
    connection = store.get_canvas_connection(profile_id)
    if not connection:
        return CanvasConnectionStatus(
            connected=False,
            message="Canvas is not connected for this student profile yet.",
        )
    return CanvasConnectionStatus(
        connected=True,
        base_url=connection.base_url,
        last_synced_at=connection.last_synced_at,
        message="Canvas connected.",
    )


def _ensure_canvas_connection(profile_id: str):
    connection = store.get_canvas_connection(profile_id)
    if not connection:
        raise HTTPException(status_code=404, detail="No Canvas connection found for this student profile.")
    return connection


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/app.js", include_in_schema=False)
def serve_app_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.js")


@app.get("/styles.css", include_in_schema=False)
def serve_styles() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "styles.css")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/auth/register", response_model=AuthSessionResponse, status_code=201)
def register(payload: AuthRegisterInput) -> AuthSessionResponse:
    try:
        user = store.create_user(payload.email, payload.password, payload.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token, expires_at = store.create_session(user.id)
    _log_usage(user.id, "auth_register", source="web_app")
    return AuthSessionResponse(token=token, expires_at=expires_at, user=user)


@app.post("/auth/login", response_model=AuthSessionResponse)
def login(payload: AuthLoginInput) -> AuthSessionResponse:
    user = store.authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token, expires_at = store.create_session(user.id)
    _log_usage(user.id, "auth_login", source="web_app")
    return AuthSessionResponse(token=token, expires_at=expires_at, user=user)


@app.get("/auth/me", response_model=AuthStatusResponse)
def auth_me(session=Depends(require_authenticated_user)) -> AuthStatusResponse:
    user, _ = session
    return AuthStatusResponse(authenticated=True, user=user)


@app.post("/auth/logout", status_code=204)
def logout(session=Depends(require_authenticated_user)) -> Response:
    user, token = session
    _log_usage(user.id, "auth_logout", source="web_app")
    store.delete_session(token)
    return Response(status_code=204)


@app.post("/analytics/session-start", status_code=204)
def analytics_session_start(
    payload: AnalyticsSessionStartInput,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> Response:
    _log_usage(
        profile_id,
        "app_session_started",
        source=payload.source,
        entry_view=payload.entry_view,
        authenticated=payload.authenticated,
    )
    return Response(status_code=204)


@app.get("/analytics/summary", response_model=UsageAnalyticsSummary)
def analytics_summary(
    profile_id: Annotated[str, Depends(resolve_profile_id)],
    days: int = 14,
) -> UsageAnalyticsSummary:
    return store.get_usage_summary(profile_id, window_days=days)


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
    response = GoogleImportResponse(
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
    _log_usage(
        profile_id,
        "google_commitments_imported",
        calendar_id=payload.calendar_id,
        imported_commitments=imported_commitments,
        updated_commitments=updated_commitments,
        skipped_events=skipped_events,
    )
    return response


@app.delete("/integrations/google/connection", status_code=204)
def disconnect_google(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Response:
    store.clear_google_connection(profile_id)
    return Response(status_code=204)


@app.get("/integrations/canvas/status", response_model=CanvasConnectionStatus)
def canvas_status(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> CanvasConnectionStatus:
    return _canvas_status(profile_id)


@app.put("/integrations/canvas/connection", response_model=CanvasConnectionStatus)
def connect_canvas(
    payload: CanvasConnectionInput,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> CanvasConnectionStatus:
    try:
        base_url = canvas.normalize_base_url(payload.base_url)
        canvas.list_courses(base_url, payload.access_token)
    except Exception as exc:  # pragma: no cover - provider/network failure path
        raise HTTPException(status_code=502, detail=f"Failed to connect to Canvas: {exc}") from exc

    store.upsert_canvas_connection(profile_id, base_url=base_url, access_token=payload.access_token)
    return CanvasConnectionStatus(
        connected=True,
        base_url=base_url,
        message="Canvas connected and ready to import assignments.",
    )


@app.get("/integrations/canvas/courses", response_model=list[CanvasCourseSummary])
def canvas_courses(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> list[CanvasCourseSummary]:
    connection = _ensure_canvas_connection(profile_id)
    try:
        return canvas.list_courses(connection.base_url, connection.access_token)
    except Exception as exc:  # pragma: no cover - provider/network failure path
        raise HTTPException(status_code=502, detail=f"Failed to fetch Canvas courses: {exc}") from exc


@app.post("/integrations/canvas/import-assignments", response_model=CanvasImportResponse)
def import_canvas_assignments(
    payload: CanvasImportRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> CanvasImportResponse:
    connection = _ensure_canvas_connection(profile_id)
    course_name = payload.course_name.strip() or f"Canvas course {payload.course_id}"

    try:
        assignments = canvas.list_assignments(connection.base_url, connection.access_token, payload.course_id)
    except Exception as exc:  # pragma: no cover - provider/network failure path
        raise HTTPException(status_code=502, detail=f"Failed to fetch Canvas assignments: {exc}") from exc

    task_candidates, skipped_assignments = canvas.infer_assignment_tasks(
        assignments,
        course_name=course_name,
        default_estimated_minutes=payload.default_estimated_minutes,
        default_difficulty=payload.default_difficulty,
    )

    imported_tasks = 0
    updated_tasks = 0
    imported_titles: list[str] = []
    for assignment_id, task_input in task_candidates:
        task, created = store.upsert_canvas_task(
            task_input,
            profile_id,
            course_id=payload.course_id,
            assignment_id=assignment_id,
        )
        imported_titles.append(task.title)
        if created:
            imported_tasks += 1
        else:
            updated_tasks += 1

    store.touch_canvas_sync(profile_id)
    response = CanvasImportResponse(
        course_id=payload.course_id,
        course_name=course_name,
        imported_tasks=imported_tasks,
        updated_tasks=updated_tasks,
        skipped_assignments=skipped_assignments,
        imported_titles=sorted(set(imported_titles)),
        message="Imported Canvas assignments with due dates into academic tasks.",
    )
    _log_usage(
        profile_id,
        "canvas_assignments_imported",
        course_id=payload.course_id,
        course_name=course_name,
        imported_tasks=imported_tasks,
        updated_tasks=updated_tasks,
        skipped_assignments=skipped_assignments,
    )
    return response


@app.delete("/integrations/canvas/connection", status_code=204)
def disconnect_canvas(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Response:
    store.clear_canvas_connection(profile_id)
    return Response(status_code=204)


@app.get("/tasks", response_model=list[Task])
def list_tasks(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> list[Task]:
    return store.list_tasks(profile_id)


@app.post("/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskInput, profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Task:
    task = store.add_task(payload, profile_id)
    _log_usage(profile_id, "task_created", task_id=task.id, category=task.category.value, priority=task.priority)
    return task


@app.put("/tasks/{task_id}", response_model=Task)
def update_task(
    task_id: str,
    payload: TaskUpdateInput,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> Task:
    updated = store.update_task(task_id, payload, profile_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    _log_usage(profile_id, "task_updated", task_id=updated.id, status=updated.status.value, category=updated.category.value)
    return updated


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, profile_id: Annotated[str, Depends(resolve_profile_id)]) -> Response:
    deleted = store.delete_task(task_id, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    _log_usage(profile_id, "task_deleted", task_id=task_id)
    return Response(status_code=204)


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


@app.get("/plans/latest", response_model=SavedPlanResponse | None)
def latest_plan(
    profile_id: Annotated[str, Depends(resolve_profile_id)],
    week_start: date | None = None,
) -> SavedPlanResponse | None:
    return store.get_latest_saved_plan(profile_id, week_start=week_start.isoformat() if week_start else None)


def _persist_plan(plan: WeeklyPlanResponse, profile_id: str, *, source_action: str) -> WeeklyPlanResponse:
    store.save_weekly_plan(plan, profile_id, source_action=source_action)
    return plan


def _run_planner(
    tasks: list[Task],
    week_start: date,
    preferences: UserPreferences,
    strategy: PlanStrategy = PlanStrategy.stability_aware,
    previous_plan: WeeklyPlanResponse | None = None,
    commitments: list[FixedCommitment] | None = None,
    engine_name: str | None = None,
) -> WeeklyPlanResponse:
    try:
        return generate_plan_with_engine(
            PlannerRequest(
                tasks=tasks,
                week_start=week_start,
                preferences=preferences,
                strategy=strategy,
                previous_plan=previous_plan,
                commitments=commitments or [],
            ),
            engine_name=engine_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _comparison_entry(plan: WeeklyPlanResponse) -> PlannerComparisonEntry:
    metrics = plan.metrics
    return PlannerComparisonEntry(
        engine_name=plan.engine_used,
        scheduled_tasks=metrics.scheduled_tasks if metrics else 0,
        unscheduled_tasks=metrics.unscheduled_tasks if metrics else 0,
        preserved_blocks=metrics.preserved_blocks if metrics else 0,
        overload_days=metrics.overload_days if metrics else 0,
        focus_alignment_pct=metrics.focus_alignment_pct if metrics else 0.0,
        total_deep_work_minutes=metrics.total_deep_work_minutes if metrics else 0,
        goal_progress=plan.score_summary.get("goal_progress", 0.0),
        consistency=plan.score_summary.get("consistency", 0.0),
        balance=plan.score_summary.get("balance", 0.0),
        alert_count=len(plan.alerts),
    )


def _comparison_score(entry: PlannerComparisonEntry) -> float:
    return (
        (entry.goal_progress * 120.0)
        + (entry.consistency * 70.0)
        + (entry.balance * 70.0)
        + (entry.focus_alignment_pct * 0.3)
        + (entry.preserved_blocks * 4.0)
        - (entry.unscheduled_tasks * 28.0)
        - (entry.overload_days * 12.0)
    )


def _comparison_highlights(entries: list[PlannerComparisonEntry], recommended_engine: str) -> list[str]:
    if not entries:
        return ["No planner engines were available to compare."]
    if len(entries) == 1:
        only = entries[0]
        return [f"Only {only.engine_name} is available in this environment, so no side-by-side comparison was run."]

    highlights = [f"{recommended_engine} produced the strongest overall weekly plan on the current inputs."]
    best_scheduled = max(entries, key=lambda item: (item.scheduled_tasks, -item.unscheduled_tasks))
    if best_scheduled.engine_name != recommended_engine or best_scheduled.scheduled_tasks > 0:
        highlights.append(
            f"{best_scheduled.engine_name} scheduled {best_scheduled.scheduled_tasks} task(s) with {best_scheduled.unscheduled_tasks} left out."
        )

    lowest_overload = min(entries, key=lambda item: (item.overload_days, item.alert_count))
    highlights.append(
        f"{lowest_overload.engine_name} kept overload to {lowest_overload.overload_days} day(s)."
    )

    best_focus = max(entries, key=lambda item: item.focus_alignment_pct)
    highlights.append(
        f"{best_focus.engine_name} reached {best_focus.focus_alignment_pct}% focus alignment."
    )
    return highlights[:4]


@app.post("/planner/generate-week", response_model=WeeklyPlanResponse)
def generate_plan(
    payload: WeeklyPlanRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> WeeklyPlanResponse:
    preferences = payload.preferences or store.get_preferences(profile_id)
    if payload.preferences:
        store.set_preferences(payload.preferences, profile_id)
    plan = _run_planner(
        store.list_tasks(profile_id),
        payload.week_start,
        preferences,
        strategy=payload.strategy,
        commitments=store.list_commitments(profile_id),
        engine_name=payload.engine_name,
    )
    _log_usage(
        profile_id,
        "plan_generated",
        week_start=payload.week_start.isoformat(),
        strategy=plan.strategy_used.value,
        engine_used=plan.engine_used,
        scheduled_tasks=plan.metrics.scheduled_tasks if plan.metrics else 0,
        unscheduled_tasks=plan.metrics.unscheduled_tasks if plan.metrics else 0,
    )
    return _persist_plan(plan, profile_id, source_action="generate_week")


@app.post("/planner/compare-engines", response_model=PlannerCompareResponse)
def compare_engines(
    payload: PlannerCompareRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> PlannerCompareResponse:
    preferences = payload.preferences or store.get_preferences(profile_id)
    if payload.preferences:
        store.set_preferences(payload.preferences, profile_id)

    engine_names = payload.engine_names or available_planner_engines()
    deduped_engines = list(dict.fromkeys(engine_names))
    tasks = store.list_tasks(profile_id)
    commitments = store.list_commitments(profile_id)

    entries: list[PlannerComparisonEntry] = []
    for engine_name in deduped_engines:
        plan = _run_planner(
            tasks,
            payload.week_start,
            preferences,
            strategy=payload.strategy,
            commitments=commitments,
            engine_name=engine_name,
        )
        entries.append(_comparison_entry(plan))

    ranked = sorted(entries, key=_comparison_score, reverse=True)
    recommended_engine = ranked[0].engine_name if ranked else default_planner_engine().name
    return PlannerCompareResponse(
        week_start=payload.week_start,
        strategy=payload.strategy,
        recommended_engine=recommended_engine,
        compared_engines=entries,
        highlights=_comparison_highlights(entries, recommended_engine),
    )


@app.post("/planner/replan", response_model=WeeklyPlanResponse)
def replan(
    payload: ReplanRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> WeeklyPlanResponse:
    current_tasks = store.list_tasks(profile_id)
    preferences = store.get_preferences(profile_id)
    commitments = store.list_commitments(profile_id)
    previous_plan = _run_planner(
        current_tasks,
        payload.week_start,
        preferences,
        commitments=commitments,
        engine_name=payload.engine_name,
    )
    task = store.mark_delayed(payload.task_id, profile_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    plan = _run_planner(
        store.list_tasks(profile_id),
        payload.week_start,
        preferences,
        strategy=payload.strategy or previous_plan.strategy_used,
        previous_plan=previous_plan,
        commitments=commitments,
        engine_name=payload.engine_name,
    )
    plan.alerts.append(f"Replanned after delay: {payload.reason}")
    _log_usage(
        profile_id,
        "bounded_replan",
        week_start=payload.week_start.isoformat(),
        reason=payload.reason,
        strategy=plan.strategy_used.value,
        engine_used=plan.engine_used,
        delayed_task_id=payload.task_id,
    )
    return _persist_plan(plan, profile_id, source_action="bounded_replan")


@app.post("/planner/replan-rl", response_model=RLReplanResponse)
def replan_with_rl(
    payload: ReplanRequest,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> RLReplanResponse:
    global trained_selector
    selected_engine = payload.engine_name or default_planner_engine().name
    current_tasks = store.list_tasks(profile_id)
    preferences = store.get_preferences(profile_id)
    commitments = store.list_commitments(profile_id)
    previous_plan = _run_planner(
        current_tasks,
        payload.week_start,
        preferences,
        commitments=commitments,
        engine_name=selected_engine,
    )
    task = store.mark_delayed(payload.task_id, profile_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if trained_selector is None or trained_selector.planner_engine != selected_engine:
        try:
            trained_selector = train_repair_selector(engine_name=selected_engine)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    latest_check_ins = store.list_check_ins(profile_id)
    latest_stress = latest_check_ins[-1].stress_level if latest_check_ins else None
    try:
        chosen, state, result = replan_with_selector(
            store.list_tasks(profile_id),
            payload.week_start,
            preferences,
            previous_plan,
            payload.task_id,
            trained_selector,
            stress_level=latest_stress,
            engine_name=selected_engine,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result.alerts.append(f"RL-selected repair strategy '{chosen.value}' after delay: {payload.reason}")
    _log_usage(
        profile_id,
        "rl_replan",
        week_start=payload.week_start.isoformat(),
        reason=payload.reason,
        chosen_strategy=chosen.value,
        engine_used=result.engine_used,
        delayed_task_id=payload.task_id,
    )
    saved = _persist_plan(result, profile_id, source_action="rl_replan")
    return RLReplanResponse(chosen_strategy=chosen, encoded_state=state, result=saved)


@app.get("/planner/strategies")
def list_strategies() -> dict[str, object]:
    return {
        "strategies": available_strategies(),
        "engines": available_planner_engines(),
        "default_engine": default_planner_engine().name,
    }


@app.post("/checkins", response_model=UserInsights)
def create_check_in(
    payload: CheckInInput,
    profile_id: Annotated[str, Depends(resolve_profile_id)],
) -> UserInsights:
    store.add_check_in(payload, profile_id)
    _log_usage(
        profile_id,
        "checkin_submitted",
        energy_level=payload.energy_level,
        stress_level=payload.stress_level,
        confidence_level=payload.confidence_level,
    )
    return derive_user_insights(store.list_tasks(profile_id), payload.stress_level)


@app.get("/insights", response_model=UserInsights)
def get_insights(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> UserInsights:
    latest_check_ins = store.list_check_ins(profile_id)
    latest_stress = latest_check_ins[-1].stress_level if latest_check_ins else None
    return derive_user_insights(store.list_tasks(profile_id), latest_stress)


@app.post("/ml/train-repair-selector", response_model=RLTrainResponse)
def train_selector(payload: RLTrainRequest) -> RLTrainResponse:
    global trained_selector
    try:
        trained_selector = train_repair_selector(
            episodes=payload.episodes,
            seed=payload.seed,
            engine_name=payload.engine_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RLTrainResponse(**trained_selector.summary())


@app.post("/ml/evaluate-repair-selector")
def evaluate_selector(payload: RepairEvaluationRequest) -> dict:
    try:
        agent = train_repair_selector(
            episodes=payload.training_episodes,
            seed=payload.seed,
            engine_name=payload.engine_name,
        )
        return evaluate_repair_selector(
            agent,
            count=payload.evaluation_scenarios,
            seed=payload.seed + 1_000,
            engine_name=payload.engine_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/demo/seed-plan", response_model=WeeklyPlanResponse)
def seed_plan(profile_id: Annotated[str, Depends(resolve_profile_id)]) -> WeeklyPlanResponse:
    tasks = store.list_tasks(profile_id)
    today = tasks[0].deadline if tasks else None
    week_start = today - timedelta(days=today.weekday()) if today else None
    if not week_start:
        raise HTTPException(status_code=400, detail="No tasks available")
    plan = _run_planner(
        tasks,
        week_start,
        store.get_preferences(profile_id),
        commitments=store.list_commitments(profile_id),
    )
    return _persist_plan(plan, profile_id, source_action="demo_seed")

