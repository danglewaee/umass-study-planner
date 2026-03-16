from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scheduler import evaluate_schedule_stability, replan_scenario, solve_scenario
from scheduler.utils import blocked_slots
from simulation.disruptions import apply_disruption, list_disruption_types
from simulation.runner import run_simulation
from simulation.scenario_gen import generate_scenario


class PlannerInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenario = generate_scenario(7)
        cls.plan = solve_scenario(cls.scenario)
        cls.task_by_id = {task.id: task for task in cls.scenario.tasks}

    def test_base_plan_avoids_blocked_slots(self) -> None:
        self._assert_plan_feasible(self.scenario, self.plan)

    def test_base_plan_has_no_overlapping_task_slots(self) -> None:
        occupied: set[int] = set()
        for item in self.plan.items:
            if not item.scheduled:
                continue
            for start, end in item.chunks:
                for slot in range(start, end):
                    self.assertNotIn(slot, occupied)
                    occupied.add(slot)

    def test_scheduled_chunks_match_task_durations_and_deadlines(self) -> None:
        for item in self.plan.items:
            task = self.task_by_id[item.task_id]
            if not item.scheduled:
                self.assertEqual(item.chunks, [])
                continue

            self.assertEqual(item.start_slot, item.chunks[0][0])
            self.assertEqual(item.end_slot, item.chunks[-1][1])
            self.assertEqual(sum(end - start for start, end in item.chunks), task.duration_slots)
            self.assertLessEqual(item.end_slot, task.deadline_slot + 1)

    def test_replans_remain_feasible_for_all_disruption_types(self) -> None:
        for offset, disruption_type in enumerate(list_disruption_types()):
            with self.subTest(disruption_type=disruption_type):
                disrupted, actual_type = apply_disruption(
                    self.scenario,
                    10_000 + offset,
                    disruption_type=disruption_type,
                    return_type=True,
                )
                self.assertEqual(actual_type, disruption_type)
                replanned = replan_scenario(disrupted, self.plan)
                self._assert_plan_feasible(disrupted, replanned)

    def test_replan_stability_metrics_are_bounded(self) -> None:
        for offset, disruption_type in enumerate(list_disruption_types()):
            with self.subTest(disruption_type=disruption_type):
                disrupted = apply_disruption(
                    self.scenario,
                    20_000 + offset,
                    disruption_type=disruption_type,
                )
                replanned = replan_scenario(disrupted, self.plan)
                preserved, churn, stability_pct = evaluate_schedule_stability(self.plan, replanned.items)
                scheduled_before = sum(1 for item in self.plan.items if item.scheduled)
                self.assertEqual(replanned.metrics.schedule_churn, churn)
                self.assertEqual(replanned.metrics.preserved_blocks, preserved)
                self.assertEqual(replanned.metrics.schedule_stability_pct, stability_pct)
                self.assertGreaterEqual(stability_pct, 0.0)
                self.assertLessEqual(stability_pct, 100.0)
                self.assertLessEqual(preserved + churn, scheduled_before)

    def test_simulation_reports_breakdown_for_each_disruption_type(self) -> None:
        results = run_simulation(count=8, seed=7)
        breakdown = results["replan_by_disruption"]
        self.assertEqual(set(breakdown.keys()), set(list_disruption_types()))
        for disruption_type in list_disruption_types():
            with self.subTest(disruption_type=disruption_type):
                planner_metrics = breakdown[disruption_type]["planner"]
                self.assertIn("missed_deadlines", planner_metrics)
                self.assertIn("schedule_stability_pct", planner_metrics)
                self.assertIn("solve_time_ms", planner_metrics)
                self.assertIn("edf", breakdown[disruption_type]["baselines"])
                self.assertIn("weighted", breakdown[disruption_type]["baselines"])

    def _assert_plan_feasible(self, scenario, plan) -> None:
        blocked = blocked_slots(scenario)
        task_by_id = {task.id: task for task in scenario.tasks}
        occupied: set[int] = set()

        for item in plan.items:
            task = task_by_id[item.task_id]
            if not item.scheduled:
                self.assertEqual(item.chunks, [])
                continue

            self.assertTrue(item.chunks)
            previous_end = None
            scheduled_slots = 0
            for start, end in item.chunks:
                self.assertLess(start, end)
                if previous_end is not None:
                    self.assertGreaterEqual(start, previous_end)
                self.assertLessEqual(end, task.deadline_slot + 1)
                for slot in range(start, end):
                    self.assertNotIn(slot, blocked)
                    self.assertNotIn(slot, occupied)
                    occupied.add(slot)
                scheduled_slots += end - start
                previous_end = end

            self.assertEqual(scheduled_slots, task.duration_slots)


if __name__ == "__main__":
    unittest.main()
