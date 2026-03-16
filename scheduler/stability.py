from __future__ import annotations

from api.schemas import PlanResult, PlannedTask


def evaluate_schedule_stability(previous_plan: PlanResult | None, current_items: list[PlannedTask]) -> tuple[int, int, float]:
    if previous_plan is None:
        return 0, 0, 100.0

    previous_signatures = {
        item.task_id: _signature(item)
        for item in previous_plan.items
        if item.scheduled
    }
    if not previous_signatures:
        return 0, 0, 100.0

    current_signatures = {
        item.task_id: _signature(item)
        for item in current_items
        if item.scheduled
    }

    preserved = 0
    churn = 0
    for task_id, signature in previous_signatures.items():
        if current_signatures.get(task_id) == signature:
            preserved += 1
        else:
            churn += 1

    stability_pct = round((preserved / len(previous_signatures)) * 100.0, 2)
    return preserved, churn, stability_pct


def _signature(item: PlannedTask) -> tuple[tuple[int, int], ...]:
    if item.chunks:
        return tuple((int(start), int(end)) for start, end in item.chunks)
    if item.start_slot is not None and item.end_slot is not None:
        return ((item.start_slot, item.end_slot),)
    return tuple()
