from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.canvas import infer_assignment_tasks, normalize_base_url


class CanvasImportTests(unittest.TestCase):
    def test_normalize_base_url_adds_https_and_strips_trailing_slash(self) -> None:
        self.assertEqual(normalize_base_url("umass.instructure.com/"), "https://umass.instructure.com")

    def test_infer_assignment_tasks_keeps_due_assignments(self) -> None:
        assignments = [
            {
                "id": 42,
                "name": "Problem Set 5",
                "description": "<p>Finish the graph search writeup.</p>",
                "due_at": "2026-03-28T23:59:00Z",
                "html_url": "https://umass.instructure.com/courses/1/assignments/42",
            },
            {
                "id": 43,
                "name": "Ungraded reading",
                "description": "<p>Read chapter 9.</p>",
                "due_at": None,
            },
        ]

        tasks, skipped = infer_assignment_tasks(
            assignments,
            course_name="COMPSCI 320",
            default_estimated_minutes=90,
            default_difficulty=3,
        )

        self.assertEqual(len(tasks), 1)
        assignment_id, task_input = tasks[0]
        self.assertEqual(assignment_id, "42")
        self.assertEqual(task_input.title, "COMPSCI 320: Problem Set 5")
        self.assertIn("Canvas course COMPSCI 320", task_input.description)
        self.assertEqual(task_input.estimated_minutes, 90)
        self.assertEqual(task_input.difficulty, 3)
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
