from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.google_calendar import infer_weekly_commitments


class GoogleCalendarImportTests(unittest.TestCase):
    def test_infer_weekly_commitments_keeps_repeating_timed_events(self) -> None:
        events = [
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
            {
                "summary": "Spring break",
                "start": {"date": "2026-03-29"},
                "end": {"date": "2026-03-30"},
            },
        ]

        candidates, skipped = infer_weekly_commitments(events)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].commitment.title, "Algorithms lecture")
        self.assertEqual(candidates[0].commitment.day_of_week, 0)
        self.assertEqual(candidates[0].commitment.start.isoformat(), "10:00:00")
        self.assertEqual(candidates[0].commitment.end.isoformat(), "11:15:00")
        self.assertEqual(skipped, 2)

    def test_infer_weekly_commitments_can_infer_repeat_pattern_without_rrule(self) -> None:
        events = [
            {
                "summary": "Campus job shift",
                "location": "Library",
                "start": {"dateTime": "2026-03-24T14:00:00-04:00"},
                "end": {"dateTime": "2026-03-24T17:00:00-04:00"},
            },
            {
                "summary": "Campus job shift",
                "location": "Library",
                "start": {"dateTime": "2026-03-31T14:00:00-04:00"},
                "end": {"dateTime": "2026-03-31T17:00:00-04:00"},
            },
        ]

        candidates, skipped = infer_weekly_commitments(events)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].commitment.kind.value, "work")
        self.assertEqual(candidates[0].commitment.day_of_week, 1)
        self.assertEqual(skipped, 0)

    def test_infer_weekly_commitments_skips_malformed_or_overnight_events(self) -> None:
        events = [
            {
                "summary": "Late night study",
                "start": {"dateTime": "2026-03-24T23:00:00-04:00"},
                "end": {"dateTime": "2026-03-25T01:00:00-04:00"},
                "recurringEventId": "late-night-study",
            },
            {
                "summary": "Broken event",
                "start": {"dateTime": "not-a-real-datetime"},
                "end": {"dateTime": "still-not-a-real-datetime"},
            },
        ]

        candidates, skipped = infer_weekly_commitments(events)

        self.assertEqual(candidates, [])
        self.assertEqual(skipped, 2)


if __name__ == "__main__":
    unittest.main()
