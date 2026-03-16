from __future__ import annotations

from api.schemas import PlanMetrics, PlanResult, PlannedTask, Scenario
from scheduler.utils import blocked_slots, daily_load, fits, preferred_window_slots


def solve_weighted(scenario: Scenario) -> PlanResult:
    blocked = blocked_slots(scenario)
    preferred = preferred_window_slots(scenario)
    occupied: set[int] = set()
    items: list[PlannedTask] = []
    missed = 0
    overload = 0
    cram = 0
    off_window = 0

    def score(task):
        urgency = 336 - task.deadline_slot
        return (task.priority * 12) + (task.difficulty * 7) + urgency - (task.duration_slots * 4)

    for task in sorted(scenario.tasks, key=score, reverse=True):
        chosen = None
        best_penalty = None
        latest_start = max(0, task.deadline_slot - task.duration_slots + 1)
        for start in range(0, latest_start + 1):
            day = start // 48
            if not fits(task, start, blocked, occupied):
                continue
            added_overload = max(0, daily_load(occupied, day) + task.duration_slots - scenario.preferences.max_daily_study_slots)
            added_off_window = sum(1 for slot in range(start, start + task.duration_slots) if slot not in preferred)
            penalty = (added_overload * 10) + added_off_window + abs(start - max(0, task.deadline_slot - 16))
            if best_penalty is None or penalty < best_penalty:
                best_penalty = penalty
                chosen = start

        if chosen is None:
            missed += 1
            items.append(PlannedTask(task_id=task.id, name=task.name, scheduled=False, reason="no feasible slot"))
            continue

        for slot in range(chosen, chosen + task.duration_slots):
            occupied.add(slot)
            if slot not in preferred:
                off_window += 1
        if task.deadline_slot - chosen <= 12:
            cram += 1
        day = chosen // 48
        overload += max(0, daily_load(occupied, day) - scenario.preferences.max_daily_study_slots)
        items.append(
            PlannedTask(
                task_id=task.id,
                name=task.name,
                scheduled=True,
                start_slot=chosen,
                end_slot=chosen + task.duration_slots,
                day=day,
                chunks=[(chosen, chosen + task.duration_slots)],
            )
        )

    return PlanResult(
        items=items,
        metrics=PlanMetrics(
            missed_deadlines=missed,
            overload_slots=overload,
            near_deadline_penalty=cram,
            schedule_churn=0,
            preserved_blocks=0,
            schedule_stability_pct=100.0,
            fragmentation_penalty=0,
            off_window_penalty=off_window,
            solve_time_ms=0.0,
            objective_value=float((1000 * missed) + (200 * overload) + (80 * cram) + (25 * off_window)),
        ),
    )
