from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from ml.repair_selector import TrainedRepairSelector, evaluate_repair_selector, replan_with_selector, train_repair_selector
from .models import (
    BrainDumpRequest,
    BrainDumpResponse,
    CheckInInput,
    FixedCommitment,
    FixedCommitmentInput,
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
from .store import store

app = FastAPI(title="UMass Study Partner API", version="0.1.0")
trained_selector: TrainedRepairSelector | None = None

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


@app.get("/commitments", response_model=list[FixedCommitment])
def list_commitments() -> list[FixedCommitment]:
    return store.list_commitments()


@app.post("/commitments", response_model=FixedCommitment, status_code=201)
def create_commitment(payload: FixedCommitmentInput) -> FixedCommitment:
    return store.add_commitment(payload)


@app.delete("/commitments/{commitment_id}", status_code=204)
def delete_commitment(commitment_id: str) -> Response:
    deleted = store.delete_commitment(commitment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Commitment not found")
    return Response(status_code=204)


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
    return generate_weekly_plan(
        store.list_tasks(),
        payload.week_start,
        preferences,
        strategy=payload.strategy,
        commitments=store.list_commitments(),
    )


@app.post("/planner/replan", response_model=WeeklyPlanResponse)
def replan(payload: ReplanRequest) -> WeeklyPlanResponse:
    current_tasks = store.list_tasks()
    preferences = store.get_preferences()
    commitments = store.list_commitments()
    previous_plan = generate_weekly_plan(current_tasks, payload.week_start, preferences, commitments=commitments)
    task = store.mark_delayed(payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    plan = generate_weekly_plan(
        store.list_tasks(),
        payload.week_start,
        preferences,
        strategy=payload.strategy or previous_plan.strategy_used,
        previous_plan=previous_plan,
        commitments=commitments,
    )
    plan.alerts.append(f"Replanned after delay: {payload.reason}")
    return plan


@app.post("/planner/replan-rl", response_model=RLReplanResponse)
def replan_with_rl(payload: ReplanRequest) -> RLReplanResponse:
    global trained_selector
    current_tasks = store.list_tasks()
    preferences = store.get_preferences()
    commitments = store.list_commitments()
    previous_plan = generate_weekly_plan(current_tasks, payload.week_start, preferences, commitments=commitments)
    task = store.mark_delayed(payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if trained_selector is None:
        trained_selector = train_repair_selector()

    latest_stress = store.list_check_ins()[-1].stress_level if store.list_check_ins() else None
    chosen, state, result = replan_with_selector(
        store.list_tasks(),
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
def create_check_in(payload: CheckInInput) -> UserInsights:
    store.add_check_in(payload)
    return derive_user_insights(store.list_tasks(), payload.stress_level)


@app.get("/insights", response_model=UserInsights)
def get_insights() -> UserInsights:
    latest_stress = store.list_check_ins()[-1].stress_level if store.list_check_ins() else None
    return derive_user_insights(store.list_tasks(), latest_stress)


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
def seed_plan() -> WeeklyPlanResponse:
    today = store.list_tasks()[0].deadline if store.list_tasks() else None
    week_start = today - timedelta(days=today.weekday()) if today else None
    if not week_start:
        raise HTTPException(status_code=400, detail="No tasks available")
    return generate_weekly_plan(
        store.list_tasks(),
        week_start,
        store.get_preferences(),
        commitments=store.list_commitments(),
    )

