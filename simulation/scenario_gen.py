from __future__ import annotations

import random

from api.schemas import Commitment, Scenario, Task, UserPreferences


def generate_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    tasks = []
    commitments = []

    for idx in range(rng.randint(12, 18)):
        duration_slots = rng.randint(2, 6)
        deadline_day = rng.randint(1, 6)
        deadline_slot = (deadline_day * 48) + rng.randint(18, 42)
        tasks.append(
            Task(
                id=f"task-{idx}",
                name=f"Task {idx}",
                course=f"CICS-{100 + (idx % 4)}",
                duration_slots=duration_slots,
                deadline_slot=min(deadline_slot, 335),
                priority=rng.randint(1, 5),
                difficulty=rng.randint(1, 5),
                energy_cost=rng.randint(1, 5),
            )
        )

    for day in range(5):
        class_start = (day * 48) + 18
        commitments.append(Commitment(id=f"class-{day}-1", name="Lecture", start_slot=class_start, end_slot=class_start + 4))
        lab_start = (day * 48) + 30
        commitments.append(Commitment(id=f"class-{day}-2", name="Lab", start_slot=lab_start, end_slot=lab_start + 3))

    preferences = UserPreferences(
        sleep_start_slot=46,
        sleep_end_slot=14,
        max_daily_study_slots=rng.randint(8, 10),
        recovery_slots_per_day=2,
        preferred_windows=[(16, 22), (28, 38)],
    )
    return Scenario(tasks=tasks, commitments=commitments, preferences=preferences)
