from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.models import PlanStrategy, Task, TaskCategory, TaskStatus, UserPreferences
from backend.app.planner import generate_weekly_plan
from ml.repair_selector import evaluate_repair_selector, train_repair_selector


def build_task(task_id: str, title: str, days_out: int, minutes: int, priority: int, difficulty: int, status: TaskStatus = TaskStatus.pending) -> Task:
    week_start = date.today() - timedelta(days=date.today().weekday())
    return Task(
        id=task_id,
        title=title,
        description="test task",
        category=TaskCategory.academics,
        deadline=week_start + timedelta(days=days_out),
        estimated_minutes=minutes,
        difficulty=difficulty,
        priority=priority,
        status=status,
        created_at=datetime.utcnow(),
    )


class IntegrationPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.week_start = date.today() - timedelta(days=date.today().weekday())
        self.preferences = UserPreferences(
            sleep_start=time(hour=23, minute=0),
            sleep_end=time(hour=7, minute=0),
            focus_start=time(hour=9, minute=0),
            focus_end=time(hour=18, minute=0),
            max_deep_blocks_per_day=3,
            break_minutes=15,
            preferred_block_minutes=90,
        )
        self.tasks = [
            build_task("t1", "Algorithms set", 1, 120, 5, 5),
            build_task("t2", "Systems milestone", 3, 90, 5, 4),
            build_task("t3", "Recruiter follow-up", 2, 45, 4, 2),
            build_task("t4", "Gym reset", 4, 60, 3, 1),
        ]

    def test_generate_plan_exposes_metrics_and_strategy(self) -> None:
        plan = generate_weekly_plan(self.tasks, self.week_start, self.preferences, strategy=PlanStrategy.stability_aware)
        self.assertEqual(plan.strategy_used, PlanStrategy.stability_aware)
        self.assertIsNotNone(plan.metrics)
        self.assertGreaterEqual(plan.metrics.scheduled_tasks, 1)
        self.assertGreaterEqual(plan.metrics.focus_alignment_pct, 0.0)
        self.assertLessEqual(plan.metrics.focus_alignment_pct, 100.0)

    def test_replan_preserves_blocks_under_stability_strategy(self) -> None:
        previous = generate_weekly_plan(self.tasks, self.week_start, self.preferences, strategy=PlanStrategy.stability_aware)
        disrupted = [task.model_copy(deep=True) for task in self.tasks]
        disrupted[0].status = TaskStatus.delayed
        repaired = generate_weekly_plan(
            disrupted,
            self.week_start,
            self.preferences,
            strategy=PlanStrategy.stability_aware,
            previous_plan=previous,
        )
        self.assertGreaterEqual(repaired.metrics.preserved_blocks, 1)
        self.assertGreaterEqual(repaired.metrics.schedule_stability_pct, 0.0)
        self.assertLessEqual(repaired.metrics.schedule_stability_pct, 100.0)

    def test_repair_selector_training_and_evaluation(self) -> None:
        agent = train_repair_selector(episodes=20, seed=11)
        summary = agent.summary()
        self.assertGreaterEqual(summary["unique_states"], 1)
        self.assertTrue(summary["action_counts"])

        results = evaluate_repair_selector(agent, count=10, seed=101)
        self.assertIn("learned_policy", results)
        self.assertIn("fixed_policies", results)
        self.assertIn("deadline_rescue", results["fixed_policies"])
        self.assertIn("reward", results["learned_policy"])


if __name__ == "__main__":
    unittest.main()
