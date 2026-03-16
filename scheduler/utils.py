from __future__ import annotations

from api.schemas import DAYS_PER_WEEK, SLOTS_PER_DAY, Commitment, Scenario, TOTAL_SLOTS, Task


def blocked_slots(scenario: Scenario) -> set[int]:
    blocked: set[int] = set()
    for commitment in scenario.commitments:
        blocked.update(range(commitment.start_slot, commitment.end_slot))
    prefs = scenario.preferences
    for day in range(DAYS_PER_WEEK):
        day_start = day * SLOTS_PER_DAY
        if prefs.sleep_start_slot < prefs.sleep_end_slot:
            blocked.update(range(day_start + prefs.sleep_start_slot, day_start + prefs.sleep_end_slot))
        else:
            blocked.update(range(day_start + prefs.sleep_start_slot, day_start + SLOTS_PER_DAY))
            blocked.update(range(day_start, day_start + prefs.sleep_end_slot))
    return blocked


def preferred_window_slots(scenario: Scenario) -> set[int]:
    slots: set[int] = set()
    for day in range(DAYS_PER_WEEK):
        day_start = day * SLOTS_PER_DAY
        for start, end in scenario.preferences.preferred_windows:
            slots.update(range(day_start + start, min(day_start + end, day_start + SLOTS_PER_DAY)))
    return slots


def fits(task: Task, start_slot: int, blocked: set[int], occupied: set[int]) -> bool:
    end_slot = start_slot + task.duration_slots
    if end_slot > TOTAL_SLOTS:
        return False
    for slot in range(start_slot, end_slot):
        if slot in blocked or slot in occupied:
            return False
    return True


def daily_load(occupied: set[int], day: int) -> int:
    day_start = day * SLOTS_PER_DAY
    day_end = day_start + SLOTS_PER_DAY
    return sum(1 for slot in occupied if day_start <= slot < day_end)
