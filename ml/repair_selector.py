from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from backend.app.models import PlanStrategy, Task, TaskCategory, TaskStatus, UserPreferences, WeeklyPlanResponse
from backend.app.planner import available_strategies
from backend.app.planner_engine import PlannerRequest, generate_plan as generate_plan_with_engine

ACTIONS = tuple(PlanStrategy(strategy) for strategy in available_strategies())


def _run_planner(
    tasks: list[Task],
    week_start: date,
    preferences: UserPreferences,
    strategy: PlanStrategy = PlanStrategy.stability_aware,
    previous_plan: WeeklyPlanResponse | None = None,
) -> WeeklyPlanResponse:
    return generate_plan_with_engine(
        PlannerRequest(
            tasks=tasks,
            week_start=week_start,
            preferences=preferences,
            strategy=strategy,
            previous_plan=previous_plan,
        )
    )


@dataclass
class TrainedRepairSelector:
    q_table: dict[str, dict[str, float]]
    action_counts: dict[str, int]
    average_reward: float
    episodes: int
    final_epsilon: float

    def choose_action(self, state: tuple[int, int, int, int]) -> PlanStrategy:
        key = _state_key(state)
        values = self.q_table.get(key, {})
        if not values:
            return PlanStrategy.stability_aware
        best_value = max(values.get(action.value, 0.0) for action in ACTIONS)
        best_actions = [action for action in ACTIONS if values.get(action.value, 0.0) == best_value]
        return sorted(best_actions, key=lambda item: ACTIONS.index(item))[0]

    def summary(self) -> dict:
        return {
            "episodes": self.episodes,
            "unique_states": len(self.q_table),
            "average_reward": round(self.average_reward, 2),
            "final_epsilon": round(self.final_epsilon, 4),
            "action_counts": dict(self.action_counts),
        }


def train_repair_selector(
    episodes: int = 60,
    seed: int = 11,
    alpha: float = 0.35,
    epsilon: float = 0.25,
    epsilon_decay: float = 0.97,
    min_epsilon: float = 0.05,
) -> TrainedRepairSelector:
    rng = random.Random(seed)
    q_table = defaultdict(_empty_action_values)
    action_counts: Counter = Counter()
    rewards = []

    for episode in range(episodes):
        tasks, week_start, preferences = _generate_training_case(seed + episode)
        previous_plan = _run_planner(tasks, week_start, preferences, strategy=PlanStrategy.stability_aware)
        shocked_tasks, delayed_task_id, _ = _apply_repair_shock(tasks, week_start, seed + 10_000 + episode)
        state = encode_state(shocked_tasks, week_start, preferences, previous_plan, delayed_task_id)
        state_key = _state_key(state)

        rollout_rewards = {}
        for action in ACTIONS:
            repaired = _run_planner(
                shocked_tasks,
                week_start,
                preferences,
                strategy=action,
                previous_plan=previous_plan,
            )
            reward = compute_reward(repaired)
            rollout_rewards[action] = reward
            q_table[state_key][action.value] += alpha * (reward - q_table[state_key][action.value])

        if rng.random() < epsilon:
            chosen_action = rng.choice(ACTIONS)
        else:
            chosen_action = _best_action(q_table[state_key])

        rewards.append(rollout_rewards[chosen_action])
        action_counts[chosen_action.value] += 1
        epsilon = max(min_epsilon, epsilon * epsilon_decay)

    return TrainedRepairSelector(
        q_table={state: dict(values) for state, values in q_table.items()},
        action_counts=dict(action_counts),
        average_reward=(sum(rewards) / len(rewards)) if rewards else 0.0,
        episodes=episodes,
        final_epsilon=epsilon,
    )


def replan_with_selector(
    tasks: list[Task],
    week_start: date,
    preferences: UserPreferences,
    previous_plan: WeeklyPlanResponse,
    delayed_task_id: str | None,
    agent: TrainedRepairSelector,
    stress_level: int | None = None,
) -> tuple[PlanStrategy, tuple[int, int, int, int], WeeklyPlanResponse]:
    state = encode_state(tasks, week_start, preferences, previous_plan, delayed_task_id, stress_level)
    action = agent.choose_action(state)
    result = _run_planner(tasks, week_start, preferences, strategy=action, previous_plan=previous_plan)
    return action, state, result


def evaluate_repair_selector(
    agent: TrainedRepairSelector,
    count: int = 40,
    seed: int = 101,
) -> dict:
    learned_rows = []
    fixed_rows: dict[str, list[dict]] = {action.value: [] for action in ACTIONS}
    action_distribution: Counter = Counter()

    for idx in range(count):
        tasks, week_start, preferences = _generate_training_case(seed + idx)
        previous_plan = _run_planner(tasks, week_start, preferences, strategy=PlanStrategy.stability_aware)
        shocked_tasks, delayed_task_id, shock_type = _apply_repair_shock(tasks, week_start, seed + 20_000 + idx)

        chosen, state, learned = replan_with_selector(
            shocked_tasks,
            week_start,
            preferences,
            previous_plan,
            delayed_task_id,
            agent,
        )
        learned_rows.append(_extract_metrics(learned, compute_reward(learned), chosen.value, shock_type, state))
        action_distribution[chosen.value] += 1

        for action in ACTIONS:
            result = _run_planner(
                shocked_tasks,
                week_start,
                preferences,
                strategy=action,
                previous_plan=previous_plan,
            )
            fixed_rows[action.value].append(
                _extract_metrics(result, compute_reward(result), action.value, shock_type, state)
            )

    return {
        "trained_agent": agent.summary(),
        "learned_policy": _aggregate(learned_rows),
        "action_distribution": dict(action_distribution),
        "fixed_policies": {name: _aggregate(rows) for name, rows in fixed_rows.items()},
    }


def encode_state(
    tasks: list[Task],
    week_start: date,
    preferences: UserPreferences,
    previous_plan: WeeklyPlanResponse,
    delayed_task_id: str | None,
    stress_level: int | None = None,
) -> tuple[int, int, int, int]:
    active_tasks = [task for task in tasks if task.status != TaskStatus.completed]
    urgent_tasks = sum(1 for task in active_tasks if (task.deadline - week_start).days <= 2 and task.priority >= 4)
    hard_tasks = sum(1 for task in active_tasks if task.difficulty >= 4)
    delayed_priority = next((task.priority for task in active_tasks if task.id == delayed_task_id), 0)
    total_minutes = sum(task.estimated_minutes for task in active_tasks)
    capacity_minutes = max(1, 7 * preferences.max_deep_blocks_per_day * preferences.preferred_block_minutes)
    workload_ratio = total_minutes / capacity_minutes
    if stress_level is not None:
        delayed_priority = max(delayed_priority, stress_level)

    return (
        _bin_value(urgent_tasks, (1, 3)),
        _bin_value(hard_tasks, (1, 3)),
        _bin_value(delayed_priority, (2, 4)),
        _bin_ratio(workload_ratio, (0.65, 0.9)),
    )


def compute_reward(plan: WeeklyPlanResponse) -> float:
    metrics = plan.metrics
    if metrics is None:
        return -1000.0
    return round(
        180.0
        + (12.0 * metrics.scheduled_tasks)
        - (120.0 * metrics.unscheduled_tasks)
        - (22.0 * metrics.overload_days)
        - (4.0 * metrics.off_window_blocks)
        + (0.55 * metrics.schedule_stability_pct)
        + (0.02 * metrics.focus_alignment_pct),
        2,
    )


def _generate_training_case(seed: int) -> tuple[list[Task], date, UserPreferences]:
    rng = random.Random(seed)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    preferences = UserPreferences(
        focus_start=time(hour=9, minute=0),
        focus_end=time(hour=18, minute=0),
        sleep_start=time(hour=23, minute=0),
        sleep_end=time(hour=7, minute=0),
        max_deep_blocks_per_day=rng.randint(2, 4),
        break_minutes=rng.choice([10, 15, 20]),
        preferred_block_minutes=rng.choice([60, 75, 90]),
    )

    categories = [
        TaskCategory.academics,
        TaskCategory.academics,
        TaskCategory.recruiting,
        TaskCategory.personal,
        TaskCategory.health,
    ]
    tasks: list[Task] = []
    for idx in range(rng.randint(6, 10)):
        category = rng.choice(categories)
        deadline = week_start + timedelta(days=rng.randint(0, 6))
        tasks.append(
            Task(
                id=f"sim-task-{seed}-{idx}",
                title=f"Task {idx}",
                description="Synthetic repair-selector training task.",
                category=category,
                deadline=deadline,
                estimated_minutes=rng.choice([45, 60, 75, 90, 120, 150]),
                difficulty=rng.randint(1, 5),
                priority=rng.randint(1, 5),
                status=TaskStatus.pending,
                created_at=datetime.utcnow(),
            )
        )
    return tasks, week_start, preferences


def _apply_repair_shock(
    tasks: list[Task],
    week_start: date,
    seed: int,
) -> tuple[list[Task], str | None, str]:
    rng = random.Random(seed)
    shocked = [task.model_copy(deep=True) for task in tasks]
    shock_type = rng.choice(("task_slip", "urgent_addition", "deadline_pull_in"))

    if shock_type == "task_slip":
        delayed = rng.choice(shocked)
        delayed.status = TaskStatus.delayed
        return shocked, delayed.id, shock_type

    if shock_type == "urgent_addition":
        urgent = Task(
            id=f"urgent-{seed}",
            title="Urgent follow-up",
            description="Synthetic urgent task injected for RL selector training.",
            category=TaskCategory.recruiting,
            deadline=week_start + timedelta(days=rng.randint(0, 1)),
            estimated_minutes=rng.choice([45, 60, 75]),
            difficulty=rng.randint(2, 4),
            priority=5,
            status=TaskStatus.pending,
            created_at=datetime.utcnow(),
        )
        shocked.append(urgent)
        delayed = rng.choice(shocked[:-1])
        delayed.status = TaskStatus.delayed
        return shocked, delayed.id, shock_type

    candidate = rng.choice(shocked)
    candidate.deadline = max(week_start, candidate.deadline - timedelta(days=rng.randint(1, 2)))
    candidate.status = TaskStatus.delayed
    candidate.priority = max(candidate.priority, 4)
    return shocked, candidate.id, shock_type


def _extract_metrics(
    plan: WeeklyPlanResponse,
    reward: float,
    action: str,
    shock_type: str,
    state: tuple[int, int, int, int],
) -> dict:
    metrics = plan.metrics
    return {
        "action": action,
        "shock_type": shock_type,
        "state": state,
        "reward": reward,
        "scheduled_tasks": metrics.scheduled_tasks if metrics else 0,
        "unscheduled_tasks": metrics.unscheduled_tasks if metrics else 0,
        "overload_days": metrics.overload_days if metrics else 0,
        "schedule_stability_pct": metrics.schedule_stability_pct if metrics else 0.0,
        "off_window_blocks": metrics.off_window_blocks if metrics else 0,
        "focus_alignment_pct": metrics.focus_alignment_pct if metrics else 0.0,
    }


def _aggregate(rows: list[dict]) -> dict:
    numeric_keys = [key for key in rows[0].keys() if key not in {"action", "shock_type", "state"}]
    return {key: round(sum(row[key] for row in rows) / len(rows), 2) for key in numeric_keys}


def _best_action(values: dict[str, float]) -> PlanStrategy:
    best_value = max(values.get(action.value, 0.0) for action in ACTIONS)
    best_actions = [action for action in ACTIONS if values.get(action.value, 0.0) == best_value]
    return sorted(best_actions, key=lambda item: ACTIONS.index(item))[0]


def _empty_action_values() -> dict[str, float]:
    return {action.value: 0.0 for action in ACTIONS}


def _state_key(state: tuple[int, int, int, int]) -> str:
    return ":".join(str(part) for part in state)


def _bin_value(value: int, thresholds: tuple[int, int]) -> int:
    if value <= thresholds[0]:
        return 0
    if value <= thresholds[1]:
        return 1
    return 2


def _bin_ratio(value: float, thresholds: tuple[float, float]) -> int:
    if value <= thresholds[0]:
        return 0
    if value <= thresholds[1]:
        return 1
    return 2
