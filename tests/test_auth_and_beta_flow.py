from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app
from backend.app.store import store


class AuthAndBetaFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.email = f"student-{uuid4().hex[:8]}@umass.edu"
        self.password = "strongpass123"
        self.user_id: str | None = None
        self.token: str | None = None

    def tearDown(self) -> None:
        if self.user_id:
            store.clear_user_account(self.user_id)

    def _register(self) -> dict:
        response = self.client.post(
            "/auth/register",
            json={
                "email": self.email,
                "password": self.password,
                "full_name": "Jamie Beta",
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.user_id = payload["user"]["id"]
        self.token = payload["token"]
        return payload

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            self._register()
        return {"Authorization": f"Bearer {self.token}"}

    def test_auth_session_round_trip(self) -> None:
        payload = self._register()
        self.assertEqual(payload["user"]["email"], self.email)

        me_response = self.client.get("/auth/me", headers=self._auth_headers())
        self.assertEqual(me_response.status_code, 200)
        self.assertTrue(me_response.json()["authenticated"])

        logout_response = self.client.post("/auth/logout", headers=self._auth_headers())
        self.assertEqual(logout_response.status_code, 204)

        expired_response = self.client.get("/auth/me", headers=self._auth_headers())
        self.assertEqual(expired_response.status_code, 401)
        self.token = None

    def test_authenticated_task_crud_round_trip(self) -> None:
        headers = self._auth_headers()
        create_response = self.client.post(
            "/tasks",
            json={
                "title": "Finish beta landing page",
                "description": "Polish the deployable beta before pilot.",
                "category": "academics",
                "deadline": date.today().isoformat(),
                "estimated_minutes": 120,
                "difficulty": 4,
                "priority": 5,
            },
            headers=headers,
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()

        update_response = self.client.put(
            f"/tasks/{created['id']}",
            json={
                "title": "Finish beta landing page",
                "description": "Polish the deployable beta before pilot.",
                "category": "academics",
                "deadline": date.today().isoformat(),
                "estimated_minutes": 150,
                "difficulty": 4,
                "priority": 5,
                "status": "completed",
            },
            headers=headers,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["status"], "completed")
        self.assertEqual(update_response.json()["estimated_minutes"], 150)

        list_response = self.client.get("/tasks", headers=headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        delete_response = self.client.delete(f"/tasks/{created['id']}", headers=headers)
        self.assertEqual(delete_response.status_code, 204)
        self.assertEqual(self.client.get("/tasks", headers=headers).json(), [])

    def test_generate_week_persists_latest_saved_plan(self) -> None:
        headers = self._auth_headers()
        week_start = date.today() - timedelta(days=date.today().weekday())
        self.client.post(
            "/tasks",
            json={
                "title": "Prepare distributed systems checkpoint",
                "description": "Need a plan that survives interruptions.",
                "category": "academics",
                "deadline": (week_start + timedelta(days=2)).isoformat(),
                "estimated_minutes": 90,
                "difficulty": 4,
                "priority": 5,
            },
            headers=headers,
        )

        plan_response = self.client.post(
            "/planner/generate-week",
            json={
                "week_start": week_start.isoformat(),
                "strategy": "stability_aware",
            },
            headers=headers,
        )
        self.assertEqual(plan_response.status_code, 200)

        saved_response = self.client.get(
            f"/plans/latest?week_start={week_start.isoformat()}",
            headers=headers,
        )
        self.assertEqual(saved_response.status_code, 200)
        payload = saved_response.json()
        self.assertEqual(payload["source_action"], "generate_week")
        self.assertEqual(payload["plan"]["week_start"], week_start.isoformat())

    def test_root_serves_frontend_shell(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("UMass Study Partner", response.text)


if __name__ == "__main__":
    unittest.main()
