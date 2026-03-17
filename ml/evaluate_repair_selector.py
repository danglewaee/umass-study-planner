from __future__ import annotations

from pprint import pprint

from .repair_selector import evaluate_repair_selector, train_repair_selector


if __name__ == "__main__":
    agent = train_repair_selector(episodes=40, seed=11)
    pprint(evaluate_repair_selector(agent, count=20, seed=101))
