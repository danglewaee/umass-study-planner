from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class TaskKind(str, Enum):
    academics = "academics"
    recruiting = "recruiting"
    personal = "personal"
    health = "health"


@dataclass
class SimTask:
    id: str
    title: str
    kind: TaskKind
    priority: int
    difficulty: int
    estimated_blocks: int
    blocks_remaining: int
    deadline_day: int
    energy_match: Literal["morning", "midday", "evening"] = "morning"


@dataclass
class UserProfile:
    strongest_window: Literal["morning", "midday", "evening"] = "morning"
    overload_sensitivity: float = 1.0
    procrastination_tendency: float = 0.3
    consistency_preference: float = 0.8
    recovery_need: float = 1.0


@dataclass
class PlannerState:
    tasks: list[SimTask]
    day_index: int = 0
    block_index: int = 0
    sleep_debt_hours: float = 0.0
    stress_level: float = 0.0
    consistency_score: float = 1.0
    completed_priority_points: float = 0.0
    missed_deadlines: int = 0
    overload_events: int = 0


@dataclass
class Action:
    type: Literal["schedule_task", "recovery", "buffer", "defer_task"]
    task_id: str | None = None
    duration_blocks: int = 1


@dataclass
class TransitionResult:
    next_state: PlannerState
    reward: float
    done: bool
    info: dict[str, float | int | str]


@dataclass
class RewardBreakdown:
    goal_progress: float = 0.0
    consistency_gain: float = 0.0
    sleep_penalty: float = 0.0
    overload_penalty: float = 0.0
    deadline_penalty: float = 0.0
    fragility_penalty: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.goal_progress
            + self.consistency_gain
            - self.sleep_penalty
            - self.overload_penalty
            - self.deadline_penalty
            - self.fragility_penalty
        )
