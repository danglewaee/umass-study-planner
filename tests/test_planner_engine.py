from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.models import PlanStrategy, Task, TaskCategory, TaskStatus, UserPreferences
from backend.app.planner import generate_weekly_plan
from backend.app.planner_engine import PlannerRequest, available_planner_engines, generate_plan


def build_task(task_id: str, title: str, days_out: int) -> Task:
    week_start = date.today() - timedelta(days=date.today().weekday())
    return Task(
        id=task_id,
        title=title,
        description="planner engine test task",
        category=TaskCategory.academics,
        deadline=week_start + timedelta(days=days_out),
        estimated_minutes=90,
        difficulty=4,
        priority=5,
        status=TaskStatus.pending,
        created_at=datetime.utcnow(),
    )


class PlannerEngineTests(unittest.TestCase):
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
            build_task("t1", "Algorithms set", 1),
            build_task("t2", "Systems milestone", 3),
        ]

    def test_default_engine_is_heuristic(self) -> None:
        plan = generate_plan(
            PlannerRequest(
                tasks=self.tasks,
                week_start=self.week_start,
                preferences=self.preferences,
                strategy=PlanStrategy.stability_aware,
            )
        )
        self.assertEqual(plan.engine_used, "heuristic_v1")
        self.assertEqual(available_planner_engines(), ["heuristic_v1"])

    def test_engine_wrapper_preserves_heuristic_outputs(self) -> None:
        direct = generate_weekly_plan(
            self.tasks,
            self.week_start,
            self.preferences,
            strategy=PlanStrategy.deadline_rescue,
        )
        wrapped = generate_plan(
            PlannerRequest(
                tasks=self.tasks,
                week_start=self.week_start,
                preferences=self.preferences,
                strategy=PlanStrategy.deadline_rescue,
            )
        )

        self.assertEqual(wrapped.strategy_used, direct.strategy_used)
        self.assertEqual(wrapped.metrics, direct.metrics)
        self.assertEqual(
            [(block.day, block.start, block.title) for block in wrapped.blocks],
            [(block.day, block.start, block.title) for block in direct.blocks],
        )
        self.assertEqual(wrapped.engine_used, "heuristic_v1")


if __name__ == "__main__":
    unittest.main()
