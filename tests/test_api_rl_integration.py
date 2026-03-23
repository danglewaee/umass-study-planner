from __future__ import annotations

import sys
import unittest
from os import environ
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend.app.main as app_module
from backend.app.main import app
from backend.app.google_calendar import GoogleTokenBundle
from backend.app.models import TaskInput
from backend.app.planner_ortools import ortools_available
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
        self.assertIn("engines", payload)
        self.assertEqual(payload["default_engine"], "heuristic_v1")
        self.assertIn("stability_aware", payload["strategies"])
        self.assertIn("deadline_rescue", payload["strategies"])
        self.assertIn("heuristic_v1", payload["engines"])
        if ortools_available():
            self.assertIn("ortools_cp_sat", payload["engines"])

    def test_train_selector_endpoint_returns_summary(self) -> None:
        response = self.client.post(
            "/ml/train-repair-selector",
            json={"episodes": 20, "seed": 13},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["episodes"], 20)
        self.assertEqual(payload["planner_engine"], "heuristic_v1")
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
        self.assertEqual(payload["result"]["engine_used"], "heuristic_v1")
        self.assertIsNotNone(payload["result"]["metrics"])

    def test_generate_week_endpoint_exposes_engine_metadata(self) -> None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        response = self.client.post(
            "/planner/generate-week",
            json={
                "week_start": week_start.isoformat(),
                "strategy": "stability_aware",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["strategy_used"], "stability_aware")
        self.assertEqual(payload["engine_used"], "heuristic_v1")
        self.assertIsNotNone(payload["metrics"])

    def test_generate_week_uses_ortools_engine_when_requested(self) -> None:
        if not ortools_available():
            self.skipTest("OR-Tools is not installed in this environment.")

        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        response = self.client.post(
            "/planner/generate-week",
            json={
                "week_start": week_start.isoformat(),
                "strategy": "stability_aware",
                "engine_name": "ortools_cp_sat",
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["engine_used"], "ortools_cp_sat")
        self.assertIsNotNone(payload["metrics"])

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

    def test_google_oauth_callback_persists_connection(self) -> None:
        state = store.create_oauth_state("google", self.profile_id)

        with patch.dict(
            environ,
            {
                "GOOGLE_CLIENT_ID": "test-client",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "GOOGLE_REDIRECT_URI": "http://localhost:8000/oauth/google/callback",
            },
            clear=False,
        ):
            with patch(
                "backend.app.main.google_calendar.exchange_code_for_tokens",
                return_value=GoogleTokenBundle(
                    access_token="google-access-token",
                    refresh_token="google-refresh-token",
                    scope="openid email https://www.googleapis.com/auth/calendar.readonly",
                    expires_at=None,
                ),
            ), patch(
                "backend.app.main.google_calendar.fetch_connected_email",
                return_value="student@umass.edu",
            ):
                response = self.client.get(f"/oauth/google/callback?code=demo-code&state={state}")

        self.assertEqual(response.status_code, 200)
        connection = store.get_google_connection(self.profile_id)
        self.assertIsNotNone(connection)
        self.assertEqual(connection.email, "student@umass.edu")

    def test_google_import_commitments_upserts_without_duplicates(self) -> None:
        sample_events = [
            {
                "summary": "Algorithms lecture",
                "location": "LGRC",
                "start": {"dateTime": "2026-03-23T10:00:00-04:00"},
                "end": {"dateTime": "2026-03-23T11:15:00-04:00"},
                "recurringEventId": "algorithms-lecture",
            },
            {
                "summary": "Algorithms lecture",
                "location": "LGRC",
                "start": {"dateTime": "2026-03-30T10:00:00-04:00"},
                "end": {"dateTime": "2026-03-30T11:15:00-04:00"},
                "recurringEventId": "algorithms-lecture",
            },
            {
                "summary": "Career fair",
                "location": "Campus Center",
                "start": {"dateTime": "2026-03-25T15:00:00-04:00"},
                "end": {"dateTime": "2026-03-25T16:00:00-04:00"},
            },
        ]

        with patch.dict(
            environ,
            {
                "GOOGLE_CLIENT_ID": "test-client",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "GOOGLE_REDIRECT_URI": "http://localhost:8000/oauth/google/callback",
            },
            clear=False,
        ):
            store.upsert_google_connection(
                self.profile_id,
                email="student@umass.edu",
                access_token="google-access-token",
                refresh_token="google-refresh-token",
                scope="openid email https://www.googleapis.com/auth/calendar.readonly",
                token_expiry=None,
            )

            with patch("backend.app.main.google_calendar.list_events", return_value=sample_events):
                first = self.client.post(
                    "/integrations/google/import-commitments",
                    json={"calendar_id": "primary", "lookahead_days": 28},
                    headers=self.headers,
                )
                second = self.client.post(
                    "/integrations/google/import-commitments",
                    json={"calendar_id": "primary", "lookahead_days": 28},
                    headers=self.headers,
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["imported_commitments"], 1)
        self.assertEqual(second.json()["updated_commitments"], 1)
        commitments = self.client.get("/commitments", headers=self.headers).json()
        self.assertEqual(len(commitments), 1)
        self.assertEqual(commitments[0]["title"], "Algorithms lecture")

    def test_canvas_connection_status_and_courses(self) -> None:
        sample_courses = [
            {"id": 101, "name": "COMPSCI 320", "course_code": "COMPSCI-320", "workflow_state": "available"},
        ]

        with patch("backend.app.main.canvas.list_courses", return_value=sample_courses):
            connect_response = self.client.put(
                "/integrations/canvas/connection",
                json={
                    "base_url": "https://umass.instructure.com",
                    "access_token": "canvas-personal-token-for-tests",
                },
                headers=self.headers,
            )
            self.assertEqual(connect_response.status_code, 200)

            status_response = self.client.get("/integrations/canvas/status", headers=self.headers)
            self.assertEqual(status_response.status_code, 200)
            self.assertTrue(status_response.json()["connected"])

            courses_response = self.client.get("/integrations/canvas/courses", headers=self.headers)
            self.assertEqual(courses_response.status_code, 200)
            self.assertEqual(len(courses_response.json()), 1)
            self.assertEqual(courses_response.json()[0]["id"], 101)

    def test_canvas_import_assignments_upserts_without_duplicates(self) -> None:
        sample_assignments = [
            {
                "id": 9001,
                "name": "Distributed systems milestone",
                "description": "<p>Implement the worker queue.</p>",
                "due_at": "2026-03-28T23:59:00Z",
                "html_url": "https://umass.instructure.com/courses/101/assignments/9001",
            }
        ]

        store.upsert_canvas_connection(
            self.profile_id,
            base_url="https://umass.instructure.com",
            access_token="canvas-personal-token-for-tests",
        )

        with patch("backend.app.main.canvas.list_assignments", return_value=sample_assignments):
            first = self.client.post(
                "/integrations/canvas/import-assignments",
                json={
                    "course_id": 101,
                    "course_name": "COMPSCI 320",
                    "default_estimated_minutes": 120,
                    "default_difficulty": 4,
                },
                headers=self.headers,
            )
            second = self.client.post(
                "/integrations/canvas/import-assignments",
                json={
                    "course_id": 101,
                    "course_name": "COMPSCI 320",
                    "default_estimated_minutes": 120,
                    "default_difficulty": 4,
                },
                headers=self.headers,
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["imported_tasks"], 1)
        self.assertEqual(second.json()["updated_tasks"], 1)
        tasks = self.client.get("/tasks", headers=self.headers).json()
        imported = [task for task in tasks if task["title"] == "COMPSCI 320: Distributed systems milestone"]
        self.assertEqual(len(imported), 1)


if __name__ == "__main__":
    unittest.main()
