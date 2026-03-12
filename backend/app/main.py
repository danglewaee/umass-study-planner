from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    BrainDumpRequest,
    BrainDumpResponse,
    CheckInInput,
    HealthResponse,
    ReplanRequest,
    Task,
    TaskInput,
    UserInsights,
    UserPreferences,
    WeeklyPlanRequest,
    WeeklyPlanResponse,
)
from .planner import derive_user_insights, generate_weekly_plan, parse_brain_dump
from .store import store

app = FastAPI(title="BalanceOS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/tasks", response_model=list[Task])
def list_tasks() -> list[Task]:
    return store.list_tasks()


@app.post("/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskInput) -> Task:
    return store.add_task(payload)


@app.post("/tasks/brain-dump", response_model=BrainDumpResponse)
def brain_dump(payload: BrainDumpRequest) -> BrainDumpResponse:
    parsed = parse_brain_dump(payload.text)
    tasks = [TaskInput(**item) for item in parsed]
    return BrainDumpResponse(tasks=tasks)


@app.get("/preferences", response_model=UserPreferences)
def get_preferences() -> UserPreferences:
    return store.get_preferences()


@app.put("/preferences", response_model=UserPreferences)
def update_preferences(payload: UserPreferences) -> UserPreferences:
    return store.set_preferences(payload)


@app.post("/planner/generate-week", response_model=WeeklyPlanResponse)
def generate_plan(payload: WeeklyPlanRequest) -> WeeklyPlanResponse:
    preferences = payload.preferences or store.get_preferences()
    if payload.preferences:
        store.set_preferences(payload.preferences)
    return generate_weekly_plan(store.list_tasks(), payload.week_start, preferences)


@app.post("/planner/replan", response_model=WeeklyPlanResponse)
def replan(payload: ReplanRequest) -> WeeklyPlanResponse:
    task = store.mark_delayed(payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    preferences = store.get_preferences()
    plan = generate_weekly_plan(store.list_tasks(), payload.week_start, preferences)
    plan.alerts.append(f"Replanned after delay: {payload.reason}")
    return plan


@app.post("/checkins", response_model=UserInsights)
def create_check_in(payload: CheckInInput) -> UserInsights:
    store.add_check_in(payload)
    return derive_user_insights(store.list_tasks(), payload.stress_level)


@app.get("/insights", response_model=UserInsights)
def get_insights() -> UserInsights:
    latest_stress = store.list_check_ins()[-1].stress_level if store.list_check_ins() else None
    return derive_user_insights(store.list_tasks(), latest_stress)


@app.get("/demo/seed-plan", response_model=WeeklyPlanResponse)
def seed_plan() -> WeeklyPlanResponse:
    today = store.list_tasks()[0].deadline if store.list_tasks() else None
    week_start = today - timedelta(days=today.weekday()) if today else None
    if not week_start:
        raise HTTPException(status_code=400, detail="No tasks available")
    return generate_weekly_plan(store.list_tasks(), week_start, store.get_preferences())
