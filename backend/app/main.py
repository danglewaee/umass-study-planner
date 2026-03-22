from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response
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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


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

