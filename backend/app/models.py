from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


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


class ScheduleBlock(BaseModel):
    id: str
    title: str
    task_id: str | None = None
    day: date
    start: time
    end: time
    kind: Literal["deep_work", "break", "sleep", "buffer", "class", "recovery"]
    reasoning: str


class WeeklyPlanRequest(BaseModel):
    week_start: date
    preferences: UserPreferences | None = None


class WeeklyPlanResponse(BaseModel):
    week_start: date
    blocks: list[ScheduleBlock]
    alerts: list[str]
    score_summary: dict[str, float]


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


class HealthResponse(BaseModel):
    status: str
