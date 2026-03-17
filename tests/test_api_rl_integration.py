from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.app.main as app_module
from backend.app.main import app
from backend.app.store import store


class ApiRepairSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.original_tasks = [task.model_copy(deep=True) for task in store.state.tasks]
        self.original_check_ins = [check_in.model_copy(deep=True) for check_in in store.state.check_ins]
        self.original_preferences = store.state.preferences.model_copy(deep=True)
        self.original_selector = app_module.trained_selector

    def tearDown(self) -> None:
        store.state.tasks = [task.model_copy(deep=True) for task in self.original_tasks]
        store.state.check_ins = [check_in.model_copy(deep=True) for check_in in self.original_check_ins]
        store.state.preferences = self.original_preferences.model_copy(deep=True)
        app_module.trained_selector = self.original_selector

    def test_strategy_endpoint_lists_repair_profiles(self) -> None:
        response = self.client.get("/planner/strategies")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("strategies", payload)
        self.assertIn("stability_aware", payload["strategies"])
        self.assertIn("deadline_rescue", payload["strategies"])

    def test_train_selector_endpoint_returns_summary(self) -> None:
        response = self.client.post(
            "/ml/train-repair-selector",
            json={"episodes": 20, "seed": 13},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["episodes"], 20)
        self.assertGreaterEqual(payload["unique_states"], 1)
        self.assertTrue(payload["action_counts"])

    def test_replan_rl_endpoint_selects_strategy_and_returns_plan(self) -> None:
        self.client.post("/ml/train-repair-selector", json={"episodes": 20, "seed": 17})
        self.client.post(
            "/checkins",
            json={
                "energy_level": 3,
                "stress_level": 4,
                "confidence_level": 3,
                "note": "Testing RL-driven replanning.",
            },
        )

        task_id = store.list_tasks()[0].id
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        response = self.client.post(
            "/planner/replan-rl",
            json={
                "task_id": task_id,
                "week_start": week_start.isoformat(),
                "reason": "Missed the first deep-work block.",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(
            payload["chosen_strategy"],
            {"stability_aware", "deadline_rescue", "load_balance", "focus_windows"},
        )
        self.assertEqual(len(payload["encoded_state"]), 4)
        self.assertIn("result", payload)
        self.assertIn("strategy_used", payload["result"])
        self.assertIsNotNone(payload["result"]["metrics"])


if __name__ == "__main__":
    unittest.main()
