from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from .models import FixedCommitment, PlanMetrics, PlanStrategy, Task, TaskStatus, UserPreferences, WeeklyPlanResponse
from .planner import (
    _add_minutes,
    _append_task_block,
    _create_fixed_commitment_blocks,
    _create_sleep_blocks,
    _rank_tasks,
    _task_block_minutes,
    _weekday_offsets,
    get_strategy_profile,
)

try:  # pragma: no cover - exercised only when dependency is installed
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover - dependency may be unavailable in some environments
    cp_model = None


ENGINE_NAME = "ortools_cp_sat"
_STEP_MINUTES = 5


@dataclass(frozen=True)
class CandidateSlot:
    task: Task
    day: date
    day_index: int
    start_minutes: int
    duration_minutes: int
    reserve_end_minutes: int
    preserve_exact: bool
    preserve_day: bool
    score: int


def ortools_available() -> bool:
    return cp_model is not None


class ORToolsPlannerEngine:
    name = ENGINE_NAME

    def generate_plan(self, request) -> WeeklyPlanResponse:
        if cp_model is None:  # pragma: no cover - protected by registry
            raise ValueError("OR-Tools is not installed. Add the 'ortools' dependency to enable this planner engine.")

        profile = get_strategy_profile(request.strategy)
        days = _weekday_offsets(request.week_start)
        week_end = days[-1]
        break_minutes = max(5, request.preferences.break_minutes + profile.break_delta_minutes)
        daily_limit_minutes = int(
            request.preferences.max_deep_blocks_per_day
            * request.preferences.preferred_block_minutes
            * profile.capacity_multiplier
        )
        overflow_limit = daily_limit_minutes + profile.soft_capacity_overflow_minutes
        latest_focus_end = _add_minutes(request.preferences.focus_end, profile.focus_end_extension_minutes)

        base_blocks = _create_sleep_blocks(days, request.preferences)
        commitment_blocks = _create_fixed_commitment_blocks(request.week_start, request.commitments)
        blocks = [*base_blocks, *commitment_blocks]

        fixed_intervals = _build_fixed_intervals(days, commitment_blocks)
        fixed_minutes_by_day = {day: sum(end - start for start, end in fixed_intervals[day]) for day in days}
        previous_task_blocks = {
            block.task_id: block
            for block in (request.previous_plan.blocks if request.previous_plan else [])
            if block.kind == "deep_work" and block.task_id
        }
        ranked_tasks = _rank_tasks(request.tasks, request.week_start, request.strategy)
        rank_positions = {task.id: index for index, task in enumerate(ranked_tasks)}
        candidates = _build_candidates(
            request.tasks,
            request.week_start,
            week_end,
            request.preferences,
            request.strategy,
            latest_focus_end,
            break_minutes,
            fixed_intervals,
            fixed_minutes_by_day,
            previous_task_blocks,
            rank_positions,
        )

        if not candidates:
            return _build_plan_response(
                request,
                blocks,
                scheduled=[],
                previous_task_blocks=previous_task_blocks,
                daily_loads={day: 0 for day in days},
            ).model_copy(update={"engine_used": self.name})

        model = cp_model.CpModel()
        candidate_vars: dict[int, Any] = {}
        task_to_candidates: dict[str, list[Any]] = {}
        day_slot_buckets: dict[tuple[int, int], list[Any]] = {}
        day_load_terms: dict[date, list[Any]] = {day: [] for day in days}

        for index, candidate in enumerate(candidates):
            variable = _new_bool_var(model, f"task_{candidate.task.id}_{candidate.day_index}_{candidate.start_minutes}")
            candidate_vars[index] = variable
            task_to_candidates.setdefault(candidate.task.id, []).append(variable)
            day_load_terms[candidate.day].append(candidate.duration_minutes * variable)

            for slot_minute in range(candidate.start_minutes, candidate.reserve_end_minutes, _STEP_MINUTES):
                day_slot_buckets.setdefault((candidate.day_index, slot_minute), []).append(variable)

        for variables in task_to_candidates.values():
            _add_at_most_one(model, variables)

        for variables in day_slot_buckets.values():
            if len(variables) > 1:
                _add_constraint(model, sum(variables) <= 1)

        for day, terms in day_load_terms.items():
            if terms:
                _add_constraint(model, sum(terms) <= overflow_limit)

        _maximize(model, sum(candidates[index].score * variable for index, variable in candidate_vars.items()))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 8
        status = _solve(solver, model)

        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:  # pragma: no cover - rare failure path
            raise RuntimeError("OR-Tools could not find a feasible schedule.")

        scheduled = [
            candidate
            for index, candidate in enumerate(candidates)
            if _solution_value(solver, candidate_vars[index]) > 0
        ]
        scheduled.sort(key=lambda candidate: (candidate.day, candidate.start_minutes, candidate.task.title))

        response = _build_plan_response(
            request,
            blocks,
            scheduled=scheduled,
            previous_task_blocks=previous_task_blocks,
            daily_loads={day: 0 for day in days},
        )
        return response.model_copy(update={"engine_used": self.name})


def _build_candidates(
    tasks: list[Task],
    week_start: date,
    week_end: date,
    preferences: UserPreferences,
    strategy: PlanStrategy,
    latest_focus_end: time,
    break_minutes: int,
    fixed_intervals: dict[date, list[tuple[int, int]]],
    fixed_minutes_by_day: dict[date, int],
    previous_task_blocks: dict[str, Any],
    rank_positions: dict[str, int],
) -> list[CandidateSlot]:
    days = _weekday_offsets(week_start)
    earliest_start = _time_to_minutes(preferences.focus_start)
    latest_end_minutes = _time_to_minutes(latest_focus_end)
    candidates: list[CandidateSlot] = []
    active_tasks = [task for task in tasks if task.status != TaskStatus.completed]

    for task in active_tasks:
        duration_minutes = _task_block_minutes(task, preferences, strategy)
        last_start = latest_end_minutes - duration_minutes
        if last_start < earliest_start:
            continue

        previous_block = previous_task_blocks.get(task.id)
        previous_start = _time_to_minutes(previous_block.start) if previous_block else None

        for day_index, current_day in enumerate(days):
            if current_day > min(task.deadline, week_end):
                continue

            candidate_starts = set(range(earliest_start, last_start + 1, _STEP_MINUTES))
            if previous_block and previous_block.day == current_day and previous_start is not None:
                candidate_starts.add(previous_start)

            for start_minutes in sorted(candidate_starts):
                if start_minutes < earliest_start or start_minutes > last_start:
                    continue
                end_minutes = start_minutes + duration_minutes
                reserve_end = end_minutes + break_minutes
                if _overlaps_fixed(fixed_intervals[current_day], start_minutes, reserve_end):
                    continue

                preserve_exact = bool(
                    previous_block
                    and previous_block.day == current_day
                    and previous_start == start_minutes
                )
                preserve_day = bool(previous_block and previous_block.day == current_day)
                candidates.append(
                    CandidateSlot(
                        task=task,
                        day=current_day,
                        day_index=day_index,
                        start_minutes=start_minutes,
                        duration_minutes=duration_minutes,
                        reserve_end_minutes=reserve_end,
                        preserve_exact=preserve_exact,
                        preserve_day=preserve_day,
                        score=_candidate_score(
                            task=task,
                            strategy=strategy,
                            week_start=week_start,
                            day=current_day,
                            start_minutes=start_minutes,
                            duration_minutes=duration_minutes,
                            fixed_minutes=fixed_minutes_by_day[current_day],
                            rank_index=rank_positions.get(task.id, len(active_tasks)),
                            preserve_exact=preserve_exact,
                            preserve_day=preserve_day,
                        ),
                    )
                )

    return candidates


def _candidate_score(
    task: Task,
    strategy: PlanStrategy,
    week_start: date,
    day: date,
    start_minutes: int,
    duration_minutes: int,
    fixed_minutes: int,
    rank_index: int,
    preserve_exact: bool,
    preserve_day: bool,
) -> int:
    urgency_days = max((task.deadline - week_start).days, 0)
    day_offset = max((day - week_start).days, 0)
    base = (
        20_000
        + (task.priority * 900)
        + (task.difficulty * 180)
        + max(0, 6 - urgency_days) * 260
        + max(0, 10 - rank_index) * 90
    )
    if task.status == TaskStatus.delayed:
        base += 1_400

    if strategy == PlanStrategy.deadline_rescue:
        base += max(0, 6 - day_offset) * 240
        base += max(0, (18 * 60 - start_minutes) // 10)
    elif strategy == PlanStrategy.load_balance:
        base += max(0, 420 - fixed_minutes)
        base += max(0, 3 - abs((task.deadline - day).days)) * 70
    elif strategy == PlanStrategy.focus_windows:
        base += max(0, (12 * 60 - start_minutes) // 3)
        if str(task.category) == "TaskCategory.academics" or str(task.category) == "academics":
            base += 180
    else:
        base += max(0, 4 - abs((task.deadline - day).days)) * 80

    if preserve_exact:
        base += 1_800
    elif preserve_day:
        base += 650

    base -= max(0, duration_minutes - 90) * 2
    return int(base)


def _build_fixed_intervals(days: list[date], commitment_blocks) -> dict[date, list[tuple[int, int]]]:
    intervals = {day: [] for day in days}
    for block in commitment_blocks:
        intervals.setdefault(block.day, []).append((_time_to_minutes(block.start), _time_to_minutes(block.end)))

    for day in intervals:
        intervals[day].sort()
    return intervals


def _overlaps_fixed(intervals: list[tuple[int, int]], start_minutes: int, end_minutes: int) -> bool:
    return any(start_minutes < fixed_end and fixed_start < end_minutes for fixed_start, fixed_end in intervals)


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _minutes_to_time(minutes: int) -> time:
    hours = max(0, min(23, minutes // 60))
    mins = max(0, min(59, minutes % 60))
    return time(hour=hours, minute=mins)


def _build_plan_response(
    request,
    base_blocks,
    scheduled: list[CandidateSlot],
    previous_task_blocks: dict[str, Any],
    daily_loads: dict[date, int],
) -> WeeklyPlanResponse:
    blocks = list(base_blocks)
    scheduled_task_ids: set[str] = set()
    preserved_blocks = 0
    off_window_blocks = 0

    for candidate in scheduled:
        start = _minutes_to_time(candidate.start_minutes)
        _append_task_block(
            blocks,
            candidate.task,
            candidate.day,
            start,
            candidate.duration_minutes,
            max(5, request.preferences.break_minutes + get_strategy_profile(request.strategy).break_delta_minutes),
            preserved=candidate.preserve_exact,
        )
        scheduled_task_ids.add(candidate.task.id)
        daily_loads[candidate.day] += candidate.duration_minutes
        if candidate.preserve_exact:
            preserved_blocks += 1
        if _minutes_to_time(candidate.start_minutes + candidate.duration_minutes) > request.preferences.focus_end:
            off_window_blocks += 1

    total_tasks = len([task for task in request.tasks if task.status != TaskStatus.completed])
    unscheduled_tasks = max(total_tasks - len(scheduled_task_ids), 0)
    overload_days = sum(
        1
        for minutes in daily_loads.values()
        if minutes > request.preferences.max_deep_blocks_per_day * request.preferences.preferred_block_minutes
    )
    previous_deep_blocks = len(previous_task_blocks)
    stability_pct = round((preserved_blocks / previous_deep_blocks) * 100.0, 2) if previous_deep_blocks else 100.0
    focus_alignment_pct = round(
        ((len(scheduled_task_ids) - off_window_blocks) / max(len(scheduled_task_ids), 1)) * 100.0,
        2,
    )

    alerts: list[str] = []
    if unscheduled_tasks:
        alerts.extend(
            [
                f"Could not fit '{task.title}' without breaking current balance constraints."
                for task in request.tasks
                if task.status != TaskStatus.completed and task.id not in scheduled_task_ids
            ]
        )
    if overload_days >= 3:
        alerts.append("Three or more days exceed your preferred deep-work load. Consider dropping or deferring work.")
    if request.strategy == PlanStrategy.deadline_rescue:
        alerts.append("Deadline rescue mode is prioritizing urgent work and allowing more schedule churn.")
    elif request.strategy == PlanStrategy.load_balance:
        alerts.append("Load-balance mode is spreading work more evenly across the week.")
    elif request.strategy == PlanStrategy.focus_windows:
        alerts.append("Focus-window mode is protecting your preferred study windows more aggressively.")
    if not alerts:
        alerts.append("Plan looks balanced. Protect sleep and keep momentum with small daily wins.")

    score_summary = {
        "goal_progress": round(len(scheduled_task_ids) / max(total_tasks, 1), 2),
        "consistency": round(max(0.2, stability_pct / 100 if request.previous_plan else 1 - overload_days / 7), 2),
        "balance": round(max(0.2, 1 - overload_days / 5), 2),
    }
    metrics = PlanMetrics(
        scheduled_tasks=len(scheduled_task_ids),
        unscheduled_tasks=unscheduled_tasks,
        preserved_blocks=preserved_blocks,
        schedule_stability_pct=stability_pct,
        overload_days=overload_days,
        off_window_blocks=off_window_blocks,
        total_deep_work_minutes=sum(daily_loads.values()),
        focus_alignment_pct=focus_alignment_pct,
    )

    ordered_blocks = sorted(blocks, key=lambda block: (block.day, block.start, block.kind))
    return WeeklyPlanResponse(
        week_start=request.week_start,
        blocks=ordered_blocks,
        alerts=alerts,
        score_summary=score_summary,
        strategy_used=request.strategy,
        engine_used=ENGINE_NAME,
        metrics=metrics,
    )


def _call_method(obj: Any, *names: str):
    for name in names:
        method = getattr(obj, name, None)
        if method:
            return method
    raise AttributeError(f"None of the methods {names!r} exist on {type(obj).__name__}.")


def _new_bool_var(model: Any, name: str):
    return _call_method(model, "new_bool_var", "NewBoolVar")(name)


def _add_at_most_one(model: Any, variables: list[Any]) -> None:
    _call_method(model, "add_at_most_one", "AddAtMostOne")(variables)


def _add_constraint(model: Any, expression: Any) -> None:
    _call_method(model, "add", "Add")(expression)


def _maximize(model: Any, expression: Any) -> None:
    _call_method(model, "maximize", "Maximize")(expression)


def _solve(solver: Any, model: Any) -> int:
    return _call_method(solver, "solve", "Solve")(model)


def _solution_value(solver: Any, variable: Any) -> int:
    return _call_method(solver, "value", "Value")(variable)
