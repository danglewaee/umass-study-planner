from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from api.schemas import PlanResult, Scenario
from baselines import solve_edf, solve_weighted
from scheduler import evaluate_schedule_stability, replan_scenario, solve_scenario
from scheduler.policy_profiles import DEFAULT_REPAIR_POLICY, list_repair_policies
from simulation.disruptions import apply_disruption, disruption_type_for_index, list_disruption_types
from simulation.scenario_gen import generate_scenario

ACTIONS = tuple(list_repair_policies())
FIXED_POLICY_BASELINES = ("stability_aware", "deadline_rescue", "load_balance", "full_replan")


@dataclass
class TrainedRepairAgent:
    q_table: dict[str, dict[str, float]]
    action_counts: dict[str, int]
    average_reward: float
    episodes: int
    final_epsilon: float

    def choose_action(self, state: tuple[int, int, int, int]) -> str:
        key = _state_key(state)
        values = self.q_table.get(key, {})
        if not values:
            return DEFAULT_REPAIR_POLICY
        best_value = max(values.get(action, 0.0) for action in ACTIONS)
        best_actions = [action for action in ACTIONS if values.get(action, 0.0) == best_value]
        return sorted(best_actions, key=ACTIONS.index)[0]

    def summary(self) -> dict:
        return {
            "episodes": self.episodes,
            "unique_states": len(self.q_table),
            "average_reward": round(self.average_reward, 2),
            "final_epsilon": round(self.final_epsilon, 4),
            "action_counts": dict(self.action_counts),
        }


def train_repair_agent(
    episodes: int = 60,
    seed: int = 11,
    alpha: float = 0.35,
    epsilon: float = 0.25,
    epsilon_decay: float = 0.97,
    min_epsilon: float = 0.05,
) -> TrainedRepairAgent:
    rng = random.Random(seed)
    q_table = defaultdict(_empty_action_values)
    action_counts: Counter = Counter()
    rewards = []

    for idx in range(episodes):
        scenario = generate_scenario(seed + idx)
        previous_plan = solve_scenario(scenario)
        disruption_type = disruption_type_for_index(idx)
        disrupted, _ = apply_disruption(
            scenario,
            seed + 10_000 + idx,
            disruption_type=disruption_type,
            return_type=True,
        )
        state = encode_state(disrupted, previous_plan)
        state_key = _state_key(state)

        rollout_rewards = {}
        for action in ACTIONS:
            result = replan_scenario(disrupted, previous_plan, strategy_name=action)
            reward = compute_reward(result)
            rollout_rewards[action] = reward
            q_table[state_key][action] += alpha * (reward - q_table[state_key][action])

        if rng.random() < epsilon:
            chosen_action = rng.choice(ACTIONS)
        else:
            chosen_action = _best_action(q_table[state_key])

        rewards.append(rollout_rewards[chosen_action])
        action_counts[chosen_action] += 1
        epsilon = max(min_epsilon, epsilon * epsilon_decay)

    return TrainedRepairAgent(
        q_table={key: dict(values) for key, values in q_table.items()},
        action_counts=dict(action_counts),
        average_reward=(sum(rewards) / len(rewards)) if rewards else 0.0,
        episodes=episodes,
        final_epsilon=epsilon,
    )


def replan_with_agent(
    scenario: Scenario,
    previous_plan: PlanResult,
    agent: TrainedRepairAgent,
) -> tuple[str, tuple[int, int, int, int], PlanResult]:
    state = encode_state(scenario, previous_plan)
    action = agent.choose_action(state)
    result = replan_scenario(scenario, previous_plan, strategy_name=action)
    return action, state, result


def evaluate_repair_agent(
    agent: TrainedRepairAgent,
    count: int = 50,
    seed: int = 101,
) -> dict:
    learned_rows = []
    action_distribution: Counter = Counter()
    fixed_rows: dict[str, list[dict]] = {policy: [] for policy in FIXED_POLICY_BASELINES}
    heuristic_rows: dict[str, list[dict]] = {"edf": [], "weighted": []}
    learned_by_type = defaultdict(list)
    action_distribution_by_type: dict[str, Counter] = defaultdict(Counter)
    fixed_rows_by_type: dict[str, dict[str, list[dict]]] = {
        disruption_type: {policy: [] for policy in FIXED_POLICY_BASELINES}
        for disruption_type in list_disruption_types()
    }
    heuristic_rows_by_type: dict[str, dict[str, list[dict]]] = {
        disruption_type: {"edf": [], "weighted": []}
        for disruption_type in list_disruption_types()
    }

    for idx in range(count):
        scenario = generate_scenario(seed + idx)
        previous_plan = solve_scenario(scenario)
        disruption_type = disruption_type_for_index(idx)
        disrupted, disruption_type = apply_disruption(
            scenario,
            seed + 20_000 + idx,
            disruption_type=disruption_type,
            return_type=True,
        )

        action, _, learned = replan_with_agent(disrupted, previous_plan, agent)
        learned_row = _extract_metrics(learned, previous_plan, action)
        learned_rows.append(learned_row)
        learned_by_type[disruption_type].append(learned_row)
        action_distribution[action] += 1
        action_distribution_by_type[disruption_type][action] += 1

        for policy in FIXED_POLICY_BASELINES:
            fixed = replan_scenario(disrupted, previous_plan, strategy_name=policy)
            fixed_row = _extract_metrics(fixed, previous_plan, policy)
            fixed_rows[policy].append(fixed_row)
            fixed_rows_by_type[disruption_type][policy].append(fixed_row)

        edf_row = _extract_metrics(solve_edf(disrupted), previous_plan, "edf")
        weighted_row = _extract_metrics(solve_weighted(disrupted), previous_plan, "weighted")
        heuristic_rows["edf"].append(edf_row)
        heuristic_rows["weighted"].append(weighted_row)
        heuristic_rows_by_type[disruption_type]["edf"].append(edf_row)
        heuristic_rows_by_type[disruption_type]["weighted"].append(weighted_row)

    return {
        "trained_agent": agent.summary(),
        "learned_policy": _aggregate(learned_rows),
        "action_distribution": dict(action_distribution),
        "fixed_policies": {policy: _aggregate(rows) for policy, rows in fixed_rows.items()},
        "heuristics": {name: _aggregate(rows) for name, rows in heuristic_rows.items()},
        "by_disruption": {
            disruption_type: {
                "learned_policy": _aggregate(learned_by_type[disruption_type]),
                "action_distribution": dict(action_distribution_by_type[disruption_type]),
                "fixed_policies": {
                    policy: _aggregate(fixed_rows_by_type[disruption_type][policy])
                    for policy in FIXED_POLICY_BASELINES
                },
                "heuristics": {
                    name: _aggregate(heuristic_rows_by_type[disruption_type][name])
                    for name in ("edf", "weighted")
                },
            }
            for disruption_type in list_disruption_types()
        },
    }


def encode_state(scenario: Scenario, previous_plan: PlanResult) -> tuple[int, int, int, int]:
    previous_signatures = {
        item.task_id: item.chunks or ([(item.start_slot, item.end_slot)] if item.start_slot is not None and item.end_slot is not None else [])
        for item in previous_plan.items
        if item.scheduled
    }
    previous_end = {
        item.task_id: item.chunks[-1][1] if item.chunks else item.end_slot
        for item in previous_plan.items
        if item.scheduled and (item.chunks or item.end_slot is not None)
    }
    disruption_commitment = next((commitment for commitment in scenario.commitments if commitment.id.startswith("disruption-")), None)
    disruption_day = disruption_commitment.start_slot // 48 if disruption_commitment else None
    day_congestion = 0
    for chunks in previous_signatures.values():
        for start, _end in chunks:
            if disruption_day is not None and start // 48 == disruption_day:
                day_congestion += 1
                break

    min_urgent_slack = 10_000
    urgent_count = 0
    for task in scenario.tasks:
        scheduled_end = previous_end.get(task.id, max(0, task.deadline_slot - task.duration_slots))
        slack = task.deadline_slot - scheduled_end
        if task.priority >= 4 and slack <= 24:
            urgent_count += 1
        if task.priority >= 4:
            min_urgent_slack = min(min_urgent_slack, slack)

    weekly_capacity = scenario.preferences.max_daily_study_slots * 7
    demand_ratio = sum(task.duration_slots for task in scenario.tasks) / max(1, weekly_capacity)

    return (
        _inverse_bin(min_urgent_slack, (16, 36)),
        _bin_value(urgent_count, (0, 2)),
        _bin_value(day_congestion, (1, 3)),
        _bin_ratio(demand_ratio, (0.75, 0.92)),
    )


def compute_reward(
    result: PlanResult,
    schedule_churn: int | None = None,
    schedule_stability_pct: float | None = None,
) -> float:
    metrics = result.metrics
    churn = metrics.schedule_churn if schedule_churn is None else schedule_churn
    stability_pct = metrics.schedule_stability_pct if schedule_stability_pct is None else schedule_stability_pct
    return round(
        250.0
        - (260.0 * metrics.missed_deadlines)
        - (28.0 * metrics.overload_slots)
        - (18.0 * churn)
        - (1.5 * metrics.off_window_penalty)
        - (0.08 * metrics.solve_time_ms)
        + (0.65 * stability_pct),
        2,
    )


def _extract_metrics(result: PlanResult, previous_plan: PlanResult, action: str) -> dict:
    preserved, churn, stability_pct = evaluate_schedule_stability(previous_plan, result.items)
    return {
        "action": action,
        "reward": compute_reward(result, schedule_churn=churn, schedule_stability_pct=stability_pct),
        "missed_deadlines": result.metrics.missed_deadlines,
        "overload_slots": result.metrics.overload_slots,
        "schedule_churn": churn,
        "preserved_blocks": preserved,
        "schedule_stability_pct": stability_pct,
        "off_window_penalty": result.metrics.off_window_penalty,
        "solve_time_ms": result.metrics.solve_time_ms,
    }


def _aggregate(rows: list[dict]) -> dict:
    aggregated = {}
    numeric_keys = [key for key in rows[0] if key != "action"]
    for key in numeric_keys:
        aggregated[key] = round(sum(row[key] for row in rows) / len(rows), 2)
    return aggregated


def _best_action(values: dict[str, float]) -> str:
    best_value = max(values.get(action, 0.0) for action in ACTIONS)
    best_actions = [action for action in ACTIONS if values.get(action, 0.0) == best_value]
    return sorted(best_actions, key=ACTIONS.index)[0]


def _state_key(state: tuple[int, int, int, int]) -> str:
    return ":".join(str(part) for part in state)


def _empty_action_values() -> dict[str, float]:
    return {action: 0.0 for action in ACTIONS}


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


def _inverse_bin(value: int, thresholds: tuple[int, int]) -> int:
    if value <= thresholds[0]:
        return 2
    if value <= thresholds[1]:
        return 1
    return 0
