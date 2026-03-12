from __future__ import annotations

from .mdp import Action, PlannerState


def urgency_first_policy(env, state: PlannerState) -> Action:
    candidates = [task for task in state.tasks if task.blocks_remaining > 0]
    if not candidates:
        return Action(type="buffer")
    task = sorted(candidates, key=lambda item: (item.deadline_day, -item.priority, -item.difficulty))[0]
    return Action(type="schedule_task", task_id=task.id)


def balanced_policy(env, state: PlannerState) -> Action:
    if state.stress_level >= 2.8 or state.sleep_debt_hours >= 2.0:
        return Action(type="recovery")

    candidates = [task for task in state.tasks if task.blocks_remaining > 0]
    if not candidates:
        return Action(type="buffer")

    current_window = env.current_window()
    scored = sorted(
        candidates,
        key=lambda task: (
            -(1 if task.energy_match == current_window else 0),
            -task.priority,
            task.deadline_day,
            -task.difficulty,
        ),
    )
    return Action(type="schedule_task", task_id=scored[0].id)


def consistency_first_policy(env, state: PlannerState) -> Action:
    if state.block_index == 3 or state.sleep_debt_hours >= 1.8:
        return Action(type="buffer")
    if state.stress_level >= 2.5:
        return Action(type="recovery")

    candidates = [task for task in state.tasks if task.blocks_remaining > 0]
    if not candidates:
        return Action(type="buffer")
    current_window = env.current_window()
    task = sorted(
        candidates,
        key=lambda item: (
            item.deadline_day,
            -(1 if item.energy_match == current_window else 0),
            -item.priority,
        ),
    )[0]
    return Action(type="schedule_task", task_id=task.id)
