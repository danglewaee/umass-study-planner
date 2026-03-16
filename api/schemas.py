from __future__ import annotations

from pydantic import BaseModel, Field

SLOTS_PER_DAY = 48
DAYS_PER_WEEK = 7
TOTAL_SLOTS = SLOTS_PER_DAY * DAYS_PER_WEEK


class Task(BaseModel):
    id: str
    name: str
    course: str | None = None
    duration_slots: int = Field(ge=1, le=12)
    deadline_slot: int = Field(ge=0, lt=TOTAL_SLOTS)
    priority: int = Field(default=3, ge=1, le=5)
    difficulty: int = Field(default=3, ge=1, le=5)
    energy_cost: int = Field(default=3, ge=1, le=5)
    allow_split: bool = True


class Commitment(BaseModel):
    id: str
    name: str
    start_slot: int = Field(ge=0, lt=TOTAL_SLOTS)
    end_slot: int = Field(gt=0, le=TOTAL_SLOTS)


class UserPreferences(BaseModel):
    sleep_start_slot: int = Field(default=46, ge=0, lt=SLOTS_PER_DAY)
    sleep_end_slot: int = Field(default=14, ge=0, lt=SLOTS_PER_DAY)
    max_daily_study_slots: int = Field(default=8, ge=1, le=20)
    recovery_slots_per_day: int = Field(default=2, ge=0, le=12)
    preferred_windows: list[tuple[int, int]] = Field(default_factory=lambda: [(16, 22), (28, 38)])


class Scenario(BaseModel):
    tasks: list[Task]
    commitments: list[Commitment] = Field(default_factory=list)
    preferences: UserPreferences = Field(default_factory=UserPreferences)


class PlannedTask(BaseModel):
    task_id: str
    name: str
    scheduled: bool
    start_slot: int | None = None
    end_slot: int | None = None
    day: int | None = None
    chunks: list[tuple[int, int]] = Field(default_factory=list)
    reason: str | None = None


class PlanMetrics(BaseModel):
    missed_deadlines: int
    overload_slots: int
    near_deadline_penalty: int
    schedule_churn: int
    preserved_blocks: int = 0
    schedule_stability_pct: float = 100.0
    fragmentation_penalty: int = 0
    off_window_penalty: int
    solve_time_ms: float
    objective_value: float


class PlanResult(BaseModel):
    items: list[PlannedTask]
    metrics: PlanMetrics


class ReplanRequest(BaseModel):
    scenario: Scenario
    previous_plan: PlanResult


class RLTrainRequest(BaseModel):
    episodes: int = Field(default=60, ge=20, le=300)
    seed: int = Field(default=11, ge=0)
    alpha: float = Field(default=0.35, gt=0.0, le=1.0)
    epsilon: float = Field(default=0.25, ge=0.0, le=1.0)


class RLTrainResponse(BaseModel):
    episodes: int
    unique_states: int
    average_reward: float
    final_epsilon: float
    action_counts: dict[str, int]


class RLReplanResponse(BaseModel):
    chosen_action: str
    encoded_state: tuple[int, int, int, int]
    result: PlanResult


class RLEvaluationRequest(BaseModel):
    training_episodes: int = Field(default=60, ge=20, le=300)
    evaluation_scenarios: int = Field(default=50, ge=10, le=200)
    seed: int = Field(default=11, ge=0)


class SimulationRequest(BaseModel):
    scenarios: int = Field(default=50, ge=1, le=500)
    seed: int = Field(default=7, ge=0)


class BenchmarkResult(BaseModel):
    planner: dict
    baselines: dict[str, dict]
