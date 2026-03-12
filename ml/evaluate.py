from __future__ import annotations

from .baselines import balanced_policy, consistency_first_policy, urgency_first_policy
from .simulator import PROFILE_PRESETS, SCENARIO_PRESETS, StudentPlannerEnv, rollout_episode


def compare_baselines(episodes: int = 25) -> dict[str, dict[str, dict[str, float]]]:
    policies = {
        "urgency_first": urgency_first_policy,
        "balanced": balanced_policy,
        "consistency_first": consistency_first_policy,
    }
    scenario_results: dict[str, dict[str, dict[str, float]]] = {}

    for scenario in SCENARIO_PRESETS:
        scenario_results[scenario] = {}
        for profile_name in PROFILE_PRESETS:
            policy_results: dict[str, dict[str, float]] = {}
            for name, policy in policies.items():
                totals = {
                    "total_reward": 0.0,
                    "completed_priority_points": 0.0,
                    "completed_tasks": 0.0,
                    "remaining_blocks": 0.0,
                    "missed_deadlines": 0.0,
                    "overload_events": 0.0,
                    "consistency_score": 0.0,
                    "stress_level": 0.0,
                    "sleep_debt_hours": 0.0,
                }
                for seed in range(episodes):
                    env = StudentPlannerEnv(seed=seed + 1, scenario=scenario, profile_name=profile_name)
                    episode = rollout_episode(env, policy)
                    for key, value in episode.items():
                        totals[key] += value
                policy_results[name] = {key: round(value / episodes, 3) for key, value in totals.items()}
            scenario_results[scenario][profile_name] = policy_results
    return scenario_results


def summarize_winners(results: dict[str, dict[str, dict[str, float]]]) -> dict[str, dict[str, str]]:
    winners: dict[str, dict[str, str]] = {}
    for scenario, profiles in results.items():
        winners[scenario] = {}
        for profile_name, policy_map in profiles.items():
            best_policy = max(policy_map.items(), key=lambda item: item[1]["total_reward"])[0]
            winners[scenario][profile_name] = best_policy
    return winners


if __name__ == "__main__":
    from pprint import pprint

    results = compare_baselines(episodes=20)
    pprint(results)
    print("\nWinners:")
    pprint(summarize_winners(results))
