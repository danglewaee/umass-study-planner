from __future__ import annotations

from api.schemas import PlanMetrics, PlanResult, PlannedTask, Scenario
from scheduler.utils import blocked_slots, daily_load, fits, preferred_window_slots


def solve_edf(scenario: Scenario) -> PlanResult:
    blocked = blocked_slots(scenario)
    preferred = preferred_window_slots(scenario)
    occupied: set[int] = set()
    items: list[PlannedTask] = []
    missed = 0
    overload = 0
    cram = 0
    off_window = 0

    for task in sorted(scenario.tasks, key=lambda item: (item.deadline_slot, -item.priority)):
        chosen = None
        latest_start = max(0, task.deadline_slot - task.duration_slots + 1)
        for start in range(0, latest_start + 1):
            day = start // 48
            if daily_load(occupied, day) + task.duration_slots > scenario.preferences.max_daily_study_slots:
                continue
            if fits(task, start, blocked, occupied):
                chosen = start
                break

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
