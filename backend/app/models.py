from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TaskCategory(str, Enum):
    academics = "academics"
    recruiting = "recruiting"
    personal = "personal"
    health = "health"


class TaskStatus(str, Enum):
    pending = "pending"
    scheduled = "scheduled"
    completed = "completed"
    delayed = "delayed"


class PlanStrategy(str, Enum):
    stability_aware = "stability_aware"
    deadline_rescue = "deadline_rescue"
    load_balance = "load_balance"
    focus_windows = "focus_windows"


class CommitmentKind(str, Enum):
    class_session = "class"
    work = "work"
    club = "club"
    commute = "commute"
    personal = "personal"
    health = "health"


class UserPreferences(BaseModel):
    sleep_start: time = time(hour=23, minute=0)
    sleep_end: time = time(hour=7, minute=0)
    focus_start: time = time(hour=9, minute=0)
    focus_end: time = time(hour=18, minute=0)
    max_deep_blocks_per_day: int = 3
    break_minutes: int = 15
    preferred_block_minutes: int = 90


class TaskInput(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = ""
    category: TaskCategory = TaskCategory.academics
    deadline: date
    estimated_minutes: int = Field(ge=15, le=720)
    difficulty: int = Field(ge=1, le=5)
    priority: int = Field(ge=1, le=5)


class Task(TaskInput):
    id: str
    status: TaskStatus = TaskStatus.pending
    created_at: datetime


class BrainDumpRequest(BaseModel):
    text: str = Field(min_length=10, max_length=5000)


class BrainDumpResponse(BaseModel):
    tasks: list[TaskInput]


class FixedCommitmentInput(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    day_of_week: int = Field(ge=0, le=6, description="Monday=0")
    start: time
    end: time
    kind: CommitmentKind = CommitmentKind.class_session
    location: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=240)

    @model_validator(mode="after")
    def validate_time_range(self) -> "FixedCommitmentInput":
        if self.end <= self.start:
            raise ValueError("Commitment end must be after start.")
        return self


class FixedCommitment(FixedCommitmentInput):
    id: str
    created_at: datetime


class GoogleAuthStartResponse(BaseModel):
    authorization_url: str


class GoogleCalendarSummary(BaseModel):
    id: str
    summary: str
    primary: bool = False
    access_role: str = "reader"
    time_zone: str | None = None


class GoogleConnectionStatus(BaseModel):
    configured: bool
    connected: bool
    connected_email: str | None = None
    last_synced_at: datetime | None = None
    message: str | None = None


class GoogleConnection(BaseModel):
    profile_id: str
    email: str
    access_token: str
    refresh_token: str
    scope: str = ""
    token_expiry: datetime | None = None
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime | None = None


class GoogleImportRequest(BaseModel):
    calendar_id: str = "primary"
    lookahead_days: int = Field(default=28, ge=7, le=90)


class GoogleImportResponse(BaseModel):
    calendar_id: str
    imported_commitments: int
    updated_commitments: int
    skipped_events: int
    imported_titles: list[str]
    message: str


class CanvasConnectionInput(BaseModel):
    base_url: str = Field(min_length=10, max_length=160)
    access_token: str = Field(min_length=20, max_length=512)


class CanvasConnectionStatus(BaseModel):
    connected: bool
    base_url: str | None = None
    last_synced_at: datetime | None = None
    message: str | None = None


class CanvasConnection(BaseModel):
    profile_id: str
    base_url: str
    access_token: str
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime | None = None


class CanvasCourseSummary(BaseModel):
    id: int
    name: str
    course_code: str | None = None
    workflow_state: str | None = None


class CanvasImportRequest(BaseModel):
    course_id: int
    course_name: str = Field(default="", max_length=160)
    default_estimated_minutes: int = Field(default=90, ge=15, le=720)
    default_difficulty: int = Field(default=3, ge=1, le=5)


class CanvasImportResponse(BaseModel):
    course_id: int
    course_name: str
    imported_tasks: int
    updated_tasks: int
    skipped_assignments: int
    imported_titles: list[str]
    message: str


class ScheduleBlock(BaseModel):
    id: str
    title: str
    task_id: str | None = None
    day: date
    start: time
    end: time
    kind: Literal["deep_work", "break", "sleep", "buffer", "class", "recovery", "commitment"]
    reasoning: str


class WeeklyPlanRequest(BaseModel):
    week_start: date
    preferences: UserPreferences | None = None
    strategy: PlanStrategy = PlanStrategy.stability_aware
    engine_name: str | None = None


class PlanMetrics(BaseModel):
    scheduled_tasks: int
    unscheduled_tasks: int
    preserved_blocks: int = 0
    schedule_stability_pct: float = 100.0
    overload_days: int = 0
    off_window_blocks: int = 0
    total_deep_work_minutes: int = 0
    focus_alignment_pct: float = 100.0


class WeeklyPlanResponse(BaseModel):
    week_start: date
    blocks: list[ScheduleBlock]
    alerts: list[str]
    score_summary: dict[str, float]
    strategy_used: PlanStrategy = PlanStrategy.stability_aware
    engine_used: str = "heuristic_v1"
    metrics: PlanMetrics | None = None


class PlannerCompareRequest(BaseModel):
    week_start: date
    preferences: UserPreferences | None = None
    strategy: PlanStrategy = PlanStrategy.stability_aware
    engine_names: list[str] = Field(default_factory=list)


class PlannerComparisonEntry(BaseModel):
    engine_name: str
    scheduled_tasks: int
    unscheduled_tasks: int
    preserved_blocks: int
    overload_days: int
    focus_alignment_pct: float
    total_deep_work_minutes: int
    goal_progress: float
    consistency: float
    balance: float
    alert_count: int


class PlannerCompareResponse(BaseModel):
    week_start: date
    strategy: PlanStrategy
    recommended_engine: str
    compared_engines: list[PlannerComparisonEntry]
    highlights: list[str]


class CheckInInput(BaseModel):
    energy_level: int = Field(ge=1, le=5)
    stress_level: int = Field(ge=1, le=5)
    confidence_level: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=500)


class CheckIn(CheckInInput):
    id: str
    created_at: datetime


class UserInsights(BaseModel):
    strongest_window: str
    consistency_risk: str
    overload_risk: str
    guidance: list[str]


class ReplanRequest(BaseModel):
    task_id: str
    week_start: date
    reason: str = Field(default="Task slipped")
    strategy: PlanStrategy | None = None
    engine_name: str | None = None


class RLTrainRequest(BaseModel):
    episodes: int = Field(default=60, ge=20, le=300)
    seed: int = Field(default=11, ge=0)
    engine_name: str | None = None


class RLTrainResponse(BaseModel):
    episodes: int
    unique_states: int
    average_reward: float
    final_epsilon: float
    planner_engine: str
    action_counts: dict[str, int]


class RLReplanResponse(BaseModel):
    chosen_strategy: PlanStrategy
    encoded_state: tuple[int, int, int, int]
    result: WeeklyPlanResponse


class RepairEvaluationRequest(BaseModel):
    training_episodes: int = Field(default=60, ge=20, le=300)
    evaluation_scenarios: int = Field(default=40, ge=10, le=200)
    seed: int = Field(default=11, ge=0)
    engine_name: str | None = None


class HealthResponse(BaseModel):
    status: str
