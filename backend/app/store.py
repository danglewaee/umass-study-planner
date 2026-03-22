from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .models import CheckIn, CheckInInput, FixedCommitment, FixedCommitmentInput, Task, TaskInput, UserPreferences

DEFAULT_PROFILE_ID = "demo-user"
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "study_partner.sqlite3"


class SQLiteStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._seed_demo_profile()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    profile_id TEXT PRIMARY KEY,
                    sleep_start TEXT NOT NULL,
                    sleep_end TEXT NOT NULL,
                    focus_start TEXT NOT NULL,
                    focus_end TEXT NOT NULL,
                    max_deep_blocks_per_day INTEGER NOT NULL,
                    break_minutes INTEGER NOT NULL,
                    preferred_block_minutes INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    deadline TEXT NOT NULL,
                    estimated_minutes INTEGER NOT NULL,
                    difficulty INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS check_ins (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    energy_level INTEGER NOT NULL,
                    stress_level INTEGER NOT NULL,
                    confidence_level INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commitments (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    day_of_week INTEGER NOT NULL,
                    start TEXT NOT NULL,
                    end TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    location TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_profile_deadline ON tasks (profile_id, deadline);
                CREATE INDEX IF NOT EXISTS idx_checkins_profile_created ON check_ins (profile_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_commitments_profile_day ON commitments (profile_id, day_of_week, start);
                """
            )

    def _ensure_profile(self, profile_id: str) -> None:
        normalized = self._normalize_profile_id(profile_id)
        defaults = UserPreferences().model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO preferences (
                    profile_id, sleep_start, sleep_end, focus_start, focus_end,
                    max_deep_blocks_per_day, break_minutes, preferred_block_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    defaults["sleep_start"],
                    defaults["sleep_end"],
                    defaults["focus_start"],
                    defaults["focus_end"],
                    defaults["max_deep_blocks_per_day"],
                    defaults["break_minutes"],
                    defaults["preferred_block_minutes"],
                ),
            )

    def _seed_demo_profile(self) -> None:
        self._ensure_profile(DEFAULT_PROFILE_ID)
        if self.list_tasks(DEFAULT_PROFILE_ID):
            return

        seeded = [
            TaskInput(
                title="Finish distributed systems milestone",
                description="Implement ingestion queue and alert ranking baseline.",
                category="academics",
                deadline=datetime.now().date(),
                estimated_minutes=180,
                difficulty=5,
                priority=5,
            ),
            TaskInput(
                title="Submit internship application follow-up",
                description="Send recruiter follow-up and update tracker.",
                category="recruiting",
                deadline=datetime.now().date(),
                estimated_minutes=45,
                difficulty=2,
                priority=4,
            ),
            TaskInput(
                title="Gym and recovery session",
                description="Protect physical reset block for the week.",
                category="health",
                deadline=datetime.now().date(),
                estimated_minutes=60,
                difficulty=1,
                priority=4,
            ),
        ]
        for task in seeded:
            self.add_task(task, DEFAULT_PROFILE_ID)

    def _normalize_profile_id(self, profile_id: str | None) -> str:
        return (profile_id or DEFAULT_PROFILE_ID).strip() or DEFAULT_PROFILE_ID

    def clear_profile(self, profile_id: str) -> None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM check_ins WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM commitments WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM preferences WHERE profile_id = ?", (normalized,))

    def add_task(self, payload: TaskInput, profile_id: str = DEFAULT_PROFILE_ID) -> Task:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        task = Task(
            id=str(uuid4()),
            created_at=datetime.utcnow(),
            **payload.model_dump(),
        )
        record = task.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, profile_id, title, description, category, deadline,
                    estimated_minutes, difficulty, priority, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    normalized,
                    record["title"],
                    record["description"],
                    record["category"],
                    record["deadline"],
                    record["estimated_minutes"],
                    record["difficulty"],
                    record["priority"],
                    record["status"],
                    record["created_at"],
                ),
            )
        return task

    def list_tasks(self, profile_id: str = DEFAULT_PROFILE_ID) -> list[Task]:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, description, category, deadline, estimated_minutes,
                       difficulty, priority, status, created_at
                FROM tasks
                WHERE profile_id = ?
                ORDER BY deadline ASC, priority DESC
                """,
                (normalized,),
            ).fetchall()
        return [Task.model_validate(dict(row)) for row in rows]

    def get_task(self, task_id: str, profile_id: str = DEFAULT_PROFILE_ID) -> Task | None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, description, category, deadline, estimated_minutes,
                       difficulty, priority, status, created_at
                FROM tasks
                WHERE id = ? AND profile_id = ?
                """,
                (task_id, normalized),
            ).fetchone()
        return Task.model_validate(dict(row)) if row else None

    def mark_delayed(self, task_id: str, profile_id: str = DEFAULT_PROFILE_ID) -> Task | None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = ? WHERE id = ? AND profile_id = ?",
                ("delayed", task_id, normalized),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_task(task_id, normalized)

    def add_check_in(self, payload: CheckInInput, profile_id: str = DEFAULT_PROFILE_ID) -> CheckIn:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        check_in = CheckIn(id=str(uuid4()), created_at=datetime.utcnow(), **payload.model_dump())
        record = check_in.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO check_ins (
                    id, profile_id, energy_level, stress_level, confidence_level, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    normalized,
                    record["energy_level"],
                    record["stress_level"],
                    record["confidence_level"],
                    record["note"],
                    record["created_at"],
                ),
            )
        return check_in

    def list_check_ins(self, profile_id: str = DEFAULT_PROFILE_ID) -> list[CheckIn]:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, energy_level, stress_level, confidence_level, note, created_at
                FROM check_ins
                WHERE profile_id = ?
                ORDER BY created_at ASC
                """,
                (normalized,),
            ).fetchall()
        return [CheckIn.model_validate(dict(row)) for row in rows]

    def add_commitment(self, payload: FixedCommitmentInput, profile_id: str = DEFAULT_PROFILE_ID) -> FixedCommitment:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        commitment = FixedCommitment(
            id=str(uuid4()),
            created_at=datetime.utcnow(),
            **payload.model_dump(),
        )
        record = commitment.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO commitments (
                    id, profile_id, title, day_of_week, start, end, kind, location, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    normalized,
                    record["title"],
                    record["day_of_week"],
                    record["start"],
                    record["end"],
                    record["kind"],
                    record["location"],
                    record["notes"],
                    record["created_at"],
                ),
            )
        return commitment

    def list_commitments(self, profile_id: str = DEFAULT_PROFILE_ID) -> list[FixedCommitment]:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, day_of_week, start, end, kind, location, notes, created_at
                FROM commitments
                WHERE profile_id = ?
                ORDER BY day_of_week ASC, start ASC, title ASC
                """,
                (normalized,),
            ).fetchall()
        return [FixedCommitment.model_validate(dict(row)) for row in rows]

    def delete_commitment(self, commitment_id: str, profile_id: str = DEFAULT_PROFILE_ID) -> bool:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM commitments WHERE id = ? AND profile_id = ?",
                (commitment_id, normalized),
            )
        return cursor.rowcount > 0

    def get_preferences(self, profile_id: str = DEFAULT_PROFILE_ID) -> UserPreferences:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sleep_start, sleep_end, focus_start, focus_end,
                       max_deep_blocks_per_day, break_minutes, preferred_block_minutes
                FROM preferences
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()
        return UserPreferences.model_validate(dict(row))

    def set_preferences(self, preferences: UserPreferences, profile_id: str = DEFAULT_PROFILE_ID) -> UserPreferences:
        normalized = self._normalize_profile_id(profile_id)
        payload = preferences.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences (
                    profile_id, sleep_start, sleep_end, focus_start, focus_end,
                    max_deep_blocks_per_day, break_minutes, preferred_block_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    sleep_start = excluded.sleep_start,
                    sleep_end = excluded.sleep_end,
                    focus_start = excluded.focus_start,
                    focus_end = excluded.focus_end,
                    max_deep_blocks_per_day = excluded.max_deep_blocks_per_day,
                    break_minutes = excluded.break_minutes,
                    preferred_block_minutes = excluded.preferred_block_minutes
                """,
                (
                    normalized,
                    payload["sleep_start"],
                    payload["sleep_end"],
                    payload["focus_start"],
                    payload["focus_end"],
                    payload["max_deep_blocks_per_day"],
                    payload["break_minutes"],
                    payload["preferred_block_minutes"],
                ),
            )
        return preferences


store = SQLiteStore()
