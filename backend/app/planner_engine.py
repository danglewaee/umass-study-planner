from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from .models import FixedCommitment, PlanStrategy, Task, UserPreferences, WeeklyPlanResponse
from .planner import generate_weekly_plan


@dataclass(frozen=True)
class PlannerRequest:
    tasks: list[Task]
    week_start: date
    preferences: UserPreferences
    strategy: PlanStrategy = PlanStrategy.stability_aware
    previous_plan: WeeklyPlanResponse | None = None
    commitments: list[FixedCommitment] = field(default_factory=list)


class PlannerEngine(Protocol):
    name: str

    def generate_plan(self, request: PlannerRequest) -> WeeklyPlanResponse:
        ...


@dataclass(frozen=True)
class HeuristicPlannerEngine:
    name: str = "heuristic_v1"

    def generate_plan(self, request: PlannerRequest) -> WeeklyPlanResponse:
        plan = generate_weekly_plan(
            request.tasks,
            request.week_start,
            request.preferences,
            strategy=request.strategy,
            previous_plan=request.previous_plan,
            commitments=request.commitments,
        )
        return plan.model_copy(update={"engine_used": self.name})


_DEFAULT_ENGINE_NAME = "heuristic_v1"
_ENGINES: dict[str, PlannerEngine] = {
    _DEFAULT_ENGINE_NAME: HeuristicPlannerEngine(),
}


def available_planner_engines() -> list[str]:
    return sorted(_ENGINES)


def default_planner_engine() -> PlannerEngine:
    return _ENGINES[_DEFAULT_ENGINE_NAME]


def get_planner_engine(name: str | None = None) -> PlannerEngine:
    if not name:
        return default_planner_engine()
    try:
        return _ENGINES[name]
    except KeyError as exc:
        available = ", ".join(available_planner_engines())
        raise ValueError(f"Unknown planner engine '{name}'. Available engines: {available}") from exc


def generate_plan(request: PlannerRequest, engine_name: str | None = None) -> WeeklyPlanResponse:
    return get_planner_engine(engine_name).generate_plan(request)
