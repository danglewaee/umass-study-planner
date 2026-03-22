from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.app.main as app_module
from backend.app.main import app
from backend.app.models import TaskInput
from backend.app.store import store


class ApiRepairSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.profile_id = f"test-api-{uuid4().hex}"
        self.headers = {"X-Profile-Id": self.profile_id}
        self.original_selector = app_module.trained_selector
        store.clear_profile(self.profile_id)
        store.add_task(
            TaskInput(
                title="Test task",
                description="Task for API test profile.",
                category="academics",
                deadline=date.today(),
                estimated_minutes=90,
                difficulty=4,
                priority=5,
            ),
            self.profile_id,
        )

    def tearDown(self) -> None:
        store.clear_profile(self.profile_id)
        app_module.trained_selector = self.original_selector

    def test_strategy_endpoint_lists_repair_profiles(self) -> None:
        response = self.client.get("/planner/strategies", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("strategies", payload)
        self.assertIn("stability_aware", payload["strategies"])
        self.assertIn("deadline_rescue", payload["strategies"])

    def test_train_selector_endpoint_returns_summary(self) -> None:
        response = self.client.post(
            "/ml/train-repair-selector",
            json={"episodes": 20, "seed": 13},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["episodes"], 20)
        self.assertGreaterEqual(payload["unique_states"], 1)
        self.assertTrue(payload["action_counts"])

    def test_replan_rl_endpoint_selects_strategy_and_returns_plan(self) -> None:
        self.client.post("/ml/train-repair-selector", json={"episodes": 20, "seed": 17}, headers=self.headers)
        self.client.post(
            "/checkins",
            json={
                "energy_level": 3,
                "stress_level": 4,
                "confidence_level": 3,
                "note": "Testing RL-driven replanning.",
            },
            headers=self.headers,
        )

        task_id = store.list_tasks(self.profile_id)[0].id
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        response = self.client.post(
            "/planner/replan-rl",
            json={
                "task_id": task_id,
                "week_start": week_start.isoformat(),
                "reason": "Missed the first deep-work block.",
            },
            headers=self.headers,
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

    def test_commitment_endpoints_round_trip(self) -> None:
        create_response = self.client.post(
            "/commitments",
            json={
                "title": "Operating systems lecture",
                "day_of_week": 1,
                "start": "10:00:00",
                "end": "11:15:00",
                "kind": "class",
                "location": "Hasbrouck",
                "notes": "Recurring lecture block.",
            },
            headers=self.headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()

        list_response = self.client.get("/commitments", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Operating systems lecture")

        delete_response = self.client.delete(f"/commitments/{created['id']}", headers=self.headers)
        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(self.client.get("/commitments", headers=self.headers).json(), [])

    def test_profile_header_isolates_commitments(self) -> None:
        other_profile_headers = {"X-Profile-Id": f"other-{uuid4().hex}"}
        self.client.post(
            "/commitments",
            json={
                "title": "Networks lecture",
                "day_of_week": 2,
                "start": "13:00:00",
                "end": "14:15:00",
                "kind": "class",
                "location": "Morrill",
                "notes": "",
            },
            headers=self.headers,
        )

        self.assertEqual(len(self.client.get("/commitments", headers=self.headers).json()), 1)
        self.assertEqual(self.client.get("/commitments", headers=other_profile_headers).json(), [])
        store.clear_profile(other_profile_headers["X-Profile-Id"])


if __name__ == "__main__":
    unittest.main()
