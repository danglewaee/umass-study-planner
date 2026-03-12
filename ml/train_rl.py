from __future__ import annotations

from dataclasses import dataclass
from random import Random

from .baselines import balanced_policy
from .mdp import Action
from .simulator import StudentPlannerEnv, rollout_episode


@dataclass
class RandomPolicyAgent:
    seed: int = 11

    def __post_init__(self) -> None:
        self.random = Random(self.seed)

    def select_action(self, env: StudentPlannerEnv, state) -> Action:
        legal = env.legal_actions()
        return self.random.choice(legal)


def random_policy(env: StudentPlannerEnv, state) -> Action:
    if not hasattr(random_policy, "agent"):
        random_policy.agent = RandomPolicyAgent()
    return random_policy.agent.select_action(env, state)


def smoke_train(episodes: int = 10) -> dict[str, float]:
    rewards = []
    env = StudentPlannerEnv(seed=21)
    for _ in range(episodes):
        env.reset()
        outcome = rollout_episode(env, random_policy)
        rewards.append(outcome["total_reward"])
    baseline = rollout_episode(StudentPlannerEnv(seed=22), balanced_policy)["total_reward"]
    return {
        "random_reward_mean": round(sum(rewards) / max(len(rewards), 1), 3),
        "balanced_policy_reference": round(baseline, 3),
    }


if __name__ == "__main__":
    print(smoke_train())
