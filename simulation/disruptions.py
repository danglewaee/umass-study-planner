from __future__ import annotations

import random

from api.schemas import Commitment, Scenario, Task

DISRUPTION_TYPES = (
    "urgent_commitment",
    "missed_session",
    "deadline_pull_in",
    "low_energy_day",
)


def list_disruption_types() -> list[str]:
    return list(DISRUPTION_TYPES)


def disruption_type_for_index(index: int) -> str:
    return DISRUPTION_TYPES[index % len(DISRUPTION_TYPES)]


def apply_disruption(
    scenario: Scenario,
    seed: int,
    disruption_type: str | None = None,
    return_type: bool = False,
) -> Scenario | tuple[Scenario, str]:
    rng = random.Random(seed)
    disrupted = scenario.model_copy(deep=True)
    kind = disruption_type or rng.choice(DISRUPTION_TYPES)

    if kind == "urgent_commitment":
        _apply_urgent_commitment(disrupted, seed, rng)
    elif kind == "missed_session":
        _apply_missed_session(disrupted, seed, rng)
    elif kind == "deadline_pull_in":
        if not _apply_deadline_pull_in(disrupted, seed, rng):
            _apply_urgent_commitment(disrupted, seed, rng)
            kind = "urgent_commitment"
    elif kind == "low_energy_day":
        _apply_low_energy_day(disrupted, seed, rng)
    else:
        raise ValueError(f"Unknown disruption type: {kind}")

    if return_type:
        return disrupted, kind
    return disrupted


def _apply_urgent_commitment(disrupted: Scenario, seed: int, rng: random.Random) -> None:
    day = rng.randint(1, 5)
    block_start = (day * 48) + rng.randint(20, 34)
    block_duration = rng.randint(2, 4)
    disrupted.commitments.append(
        Commitment(
            id=f"disruption-urgent-block-{seed}",
            name="Unexpected commitment",
            start_slot=block_start,
            end_slot=min(block_start + block_duration, 336),
        )
    )

    urgent_duration = rng.randint(2, 4)
    urgent_deadline = min(block_start + rng.randint(8, 18), 335)
    disrupted.tasks.append(
        Task(
            id=f"urgent-{seed}",
            name="Urgent task",
            course="disruption",
            duration_slots=urgent_duration,
            deadline_slot=urgent_deadline,
            priority=5,
            difficulty=rng.randint(3, 5),
            energy_cost=rng.randint(3, 5),
        )
    )


def _apply_missed_session(disrupted: Scenario, seed: int, rng: random.Random) -> None:
    day = rng.randint(1, 5)
    preferred_windows = disrupted.preferences.preferred_windows or [(28, 38)]
    window_start, window_end = preferred_windows[rng.randrange(len(preferred_windows))]
    duration = min(rng.randint(4, 6), max(2, window_end - window_start))
    start_offset = max(window_start, window_end - duration)
    block_start = (day * 48) + start_offset
    disrupted.commitments.append(
        Commitment(
            id=f"disruption-missed-session-{seed}",
            name="Missed study session",
            start_slot=block_start,
            end_slot=min(block_start + duration, 336),
        )
    )


def _apply_deadline_pull_in(disrupted: Scenario, seed: int, rng: random.Random) -> bool:
    candidates = [
        task
        for task in disrupted.tasks
        if task.deadline_slot - task.duration_slots >= 20
    ]
    if not candidates:
        return False

    task = rng.choice(candidates)
    new_deadline = max(task.duration_slots + 2, task.deadline_slot - rng.randint(10, 22))
    task.deadline_slot = min(new_deadline, 335)
    task.priority = max(task.priority, 5)
    task.course = f"{task.course or 'course'}-deadline-shock"
    return True


def _apply_low_energy_day(disrupted: Scenario, seed: int, rng: random.Random) -> None:
    day = rng.randint(1, 5)
    midday_start = (day * 48) + rng.randint(22, 26)
    evening_start = (day * 48) + rng.randint(30, 34)
    disrupted.commitments.append(
        Commitment(
            id=f"disruption-recovery-midday-{seed}",
            name="Low-energy recovery block",
            start_slot=midday_start,
            end_slot=min(midday_start + rng.randint(3, 5), 336),
        )
    )
    disrupted.tasks.append(
        Task(
            id=f"low-energy-admin-{seed}",
            name="Admin catch-up",
            course="disruption",
            duration_slots=rng.randint(2, 3),
            deadline_slot=min(evening_start + rng.randint(8, 16), 335),
            priority=4,
            difficulty=2,
            energy_cost=2,
        )
    )
    disrupted.commitments.append(
        Commitment(
            id=f"disruption-recovery-evening-{seed}",
            name="Early recovery window",
            start_slot=evening_start,
            end_slot=min(evening_start + rng.randint(4, 6), 336),
        )
    )
