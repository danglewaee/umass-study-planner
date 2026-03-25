from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .models import (
    AuthUser,
    CanvasConnection,
    CheckIn,
    CheckInInput,
    FixedCommitment,
    FixedCommitmentInput,
    GoogleConnection,
    SavedPlanResponse,
    Task,
    TaskInput,
    TaskUpdateInput,
    UsageAnalyticsSummary,
    UsageDailyPoint,
    UsageEventRecord,
    UserPreferences,
    WeeklyPlanResponse,
)

DEFAULT_PROFILE_ID = "demo-user"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "study_partner.sqlite3"
CONFIGURED_DB_PATH = os.getenv("STUDY_PARTNER_DB_PATH") or (
    str(Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "study_partner.sqlite3")
    if os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    else None
)
DB_PATH = Path(CONFIGURED_DB_PATH) if CONFIGURED_DB_PATH else DEFAULT_DB_PATH


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

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
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

                CREATE TABLE IF NOT EXISTS task_sources (
                    task_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    external_ref TEXT NOT NULL,
                    last_synced_at TEXT NOT NULL,
                    UNIQUE(profile_id, provider, scope_id, external_ref)
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

                CREATE TABLE IF NOT EXISTS commitment_sources (
                    commitment_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    calendar_id TEXT NOT NULL,
                    external_ref TEXT NOT NULL,
                    last_synced_at TEXT NOT NULL,
                    UNIQUE(profile_id, provider, calendar_id, external_ref)
                );

                CREATE TABLE IF NOT EXISTS google_connections (
                    profile_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    token_expiry TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_synced_at TEXT
                );

                CREATE TABLE IF NOT EXISTS canvas_connections (
                    profile_id TEXT PRIMARY KEY,
                    base_url TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_synced_at TEXT
                );

                CREATE TABLE IF NOT EXISTS oauth_states (
                    provider TEXT NOT NULL,
                    state TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS saved_plans (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    week_start TEXT NOT NULL,
                    source_action TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(profile_id, week_start)
                );

                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, expires_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_profile_deadline ON tasks (profile_id, deadline);
                CREATE INDEX IF NOT EXISTS idx_task_sources_profile ON task_sources (profile_id, provider, scope_id);
                CREATE INDEX IF NOT EXISTS idx_checkins_profile_created ON check_ins (profile_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_commitments_profile_day ON commitments (profile_id, day_of_week, start);
                CREATE INDEX IF NOT EXISTS idx_commitment_sources_profile ON commitment_sources (profile_id, provider, calendar_id);
                CREATE INDEX IF NOT EXISTS idx_oauth_states_provider ON oauth_states (provider, created_at);
                CREATE INDEX IF NOT EXISTS idx_saved_plans_profile_updated ON saved_plans (profile_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_profile_created ON usage_events (profile_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_profile_type ON usage_events (profile_id, event_type, created_at DESC);
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

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _hash_password(self, password: str, salt: bytes | None = None) -> str:
        effective_salt = salt or secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), effective_salt, 120_000)
        return f"{effective_salt.hex()}:{derived.hex()}"

    def _verify_password(self, password: str, encoded: str) -> bool:
        salt_hex, digest_hex = encoded.split(":", 1)
        candidate = self._hash_password(password, bytes.fromhex(salt_hex))
        return hmac.compare_digest(candidate, f"{salt_hex}:{digest_hex}")

    def _hash_session_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _user_from_row(self, row: sqlite3.Row | None) -> AuthUser | None:
        return AuthUser.model_validate(dict(row)) if row else None

    def clear_profile(self, profile_id: str) -> None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM task_sources WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM commitment_sources WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM google_connections WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM canvas_connections WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM oauth_states WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM saved_plans WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM usage_events WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM tasks WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM check_ins WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM commitments WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM preferences WHERE profile_id = ?", (normalized,))

    def log_usage_event(
        self,
        profile_id: str,
        event_type: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> UsageEventRecord:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        record = UsageEventRecord(
            event_type=event_type,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_events (id, profile_id, event_type, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    normalized,
                    record.event_type,
                    json.dumps(record.metadata),
                    record.created_at.isoformat(),
                ),
            )
        return record

    def get_usage_summary(self, profile_id: str, *, window_days: int = 14) -> UsageAnalyticsSummary:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        bounded_window = max(1, min(window_days, 90))
        window_start = (datetime.utcnow() - timedelta(days=bounded_window - 1)).date().isoformat()

        with self._connect() as connection:
            aggregate = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_events,
                    SUM(CASE WHEN event_type = 'app_session_started' THEN 1 ELSE 0 END) AS session_starts,
                    SUM(CASE WHEN event_type = 'plan_generated' THEN 1 ELSE 0 END) AS plan_generations,
                    SUM(CASE WHEN event_type IN ('bounded_replan', 'rl_replan') THEN 1 ELSE 0 END) AS replan_runs,
                    SUM(CASE WHEN event_type IN ('task_created', 'task_updated', 'task_deleted') THEN 1 ELSE 0 END) AS task_events,
                    SUM(CASE WHEN event_type IN ('google_commitments_imported', 'canvas_assignments_imported') THEN 1 ELSE 0 END) AS import_runs,
                    COUNT(DISTINCT substr(created_at, 1, 10)) AS active_days,
                    MAX(created_at) AS last_active_at
                FROM usage_events
                WHERE profile_id = ? AND substr(created_at, 1, 10) >= ?
                """,
                (normalized, window_start),
            ).fetchone()

            recent_rows = connection.execute(
                """
                SELECT event_type, metadata_json, created_at
                FROM usage_events
                WHERE profile_id = ? AND substr(created_at, 1, 10) >= ?
                ORDER BY created_at DESC
                LIMIT 8
                """,
                (normalized, window_start),
            ).fetchall()

            daily_rows = connection.execute(
                """
                SELECT
                    substr(created_at, 1, 10) AS day,
                    COUNT(*) AS total_events,
                    SUM(CASE WHEN event_type = 'plan_generated' THEN 1 ELSE 0 END) AS plan_generations,
                    SUM(CASE WHEN event_type IN ('bounded_replan', 'rl_replan') THEN 1 ELSE 0 END) AS replan_runs
                FROM usage_events
                WHERE profile_id = ? AND substr(created_at, 1, 10) >= ?
                GROUP BY substr(created_at, 1, 10)
                ORDER BY day DESC
                LIMIT 14
                """,
                (normalized, window_start),
            ).fetchall()

        recent_events = [
            UsageEventRecord(
                event_type=row["event_type"],
                created_at=datetime.fromisoformat(row["created_at"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in recent_rows
        ]
        daily_activity = [
            UsageDailyPoint(
                day=row["day"],
                total_events=row["total_events"] or 0,
                plan_generations=row["plan_generations"] or 0,
                replan_runs=row["replan_runs"] or 0,
            )
            for row in daily_rows
        ]
        return UsageAnalyticsSummary(
            profile_id=normalized,
            window_days=bounded_window,
            total_events=aggregate["total_events"] or 0,
            session_starts=aggregate["session_starts"] or 0,
            plan_generations=aggregate["plan_generations"] or 0,
            replan_runs=aggregate["replan_runs"] or 0,
            task_events=aggregate["task_events"] or 0,
            import_runs=aggregate["import_runs"] or 0,
            active_days=aggregate["active_days"] or 0,
            last_active_at=datetime.fromisoformat(aggregate["last_active_at"]) if aggregate["last_active_at"] else None,
            recent_events=recent_events,
            daily_activity=daily_activity,
        )

    def create_user(self, email: str, password: str, full_name: str) -> AuthUser:
        normalized_email = self._normalize_email(email)
        now = datetime.utcnow().isoformat()
        user = AuthUser(
            id=str(uuid4()),
            email=normalized_email,
            full_name=full_name.strip(),
            created_at=datetime.utcnow(),
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users (id, email, password_hash, full_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.id,
                        normalized_email,
                        self._hash_password(password),
                        user.full_name,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("An account with this email already exists.") from exc
        self._ensure_profile(user.id)
        return user

    def get_user(self, user_id: str) -> AuthUser | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, full_name, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._user_from_row(row)

    def get_user_by_email(self, email: str) -> AuthUser | None:
        normalized_email = self._normalize_email(email)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, full_name, created_at FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
        return self._user_from_row(row)

    def authenticate_user(self, email: str, password: str) -> AuthUser | None:
        normalized_email = self._normalize_email(email)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, password_hash, full_name, created_at FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
        if not row or not self._verify_password(password, row["password_hash"]):
            return None
        return AuthUser.model_validate(
            {
                "id": row["id"],
                "email": row["email"],
                "full_name": row["full_name"],
                "created_at": row["created_at"],
            }
        )

    def create_session(self, user_id: str, *, duration_days: int = 14) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(days=duration_days)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self._hash_session_token(token),
                    user_id,
                    datetime.utcnow().isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return token, expires_at

    def get_user_by_session_token(self, token: str) -> AuthUser | None:
        token_hash = self._hash_session_token(token)
        now = datetime.utcnow().isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            row = connection.execute(
                """
                SELECT u.id, u.email, u.full_name, u.created_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        return self._user_from_row(row)

    def delete_session(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (self._hash_session_token(token),),
            )

    def clear_user_account(self, user_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.clear_profile(user_id)

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

    def update_task(
        self,
        task_id: str,
        payload: TaskUpdateInput,
        profile_id: str = DEFAULT_PROFILE_ID,
    ) -> Task | None:
        normalized = self._normalize_profile_id(profile_id)
        record = payload.model_dump(mode="json")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, category = ?, deadline = ?, estimated_minutes = ?,
                    difficulty = ?, priority = ?, status = ?
                WHERE id = ? AND profile_id = ?
                """,
                (
                    record["title"],
                    record["description"],
                    record["category"],
                    record["deadline"],
                    record["estimated_minutes"],
                    record["difficulty"],
                    record["priority"],
                    record["status"],
                    task_id,
                    normalized,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_task(task_id, normalized)

    def delete_task(self, task_id: str, profile_id: str = DEFAULT_PROFILE_ID) -> bool:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_sources WHERE task_id = ? AND profile_id = ?",
                (task_id, normalized),
            )
            cursor = connection.execute(
                "DELETE FROM tasks WHERE id = ? AND profile_id = ?",
                (task_id, normalized),
            )
        return cursor.rowcount > 0

    def upsert_canvas_task(
        self,
        payload: TaskInput,
        profile_id: str,
        *,
        course_id: int,
        assignment_id: str,
    ) -> tuple[Task, bool]:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        now = datetime.utcnow()
        payload_dump = payload.model_dump(mode="json")
        scope_id = str(course_id)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT t.id, t.status, t.created_at
                FROM task_sources ts
                JOIN tasks t ON t.id = ts.task_id
                WHERE ts.profile_id = ? AND ts.provider = ? AND ts.scope_id = ? AND ts.external_ref = ?
                """,
                (normalized, "canvas_assignment", scope_id, assignment_id),
            ).fetchone()

            if row:
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = ?, description = ?, category = ?, deadline = ?, estimated_minutes = ?, difficulty = ?, priority = ?
                    WHERE id = ? AND profile_id = ?
                    """,
                    (
                        payload_dump["title"],
                        payload_dump["description"],
                        payload_dump["category"],
                        payload_dump["deadline"],
                        payload_dump["estimated_minutes"],
                        payload_dump["difficulty"],
                        payload_dump["priority"],
                        row["id"],
                        normalized,
                    ),
                )
                connection.execute(
                    """
                    UPDATE task_sources
                    SET last_synced_at = ?
                    WHERE task_id = ? AND profile_id = ?
                    """,
                    (now.isoformat(), row["id"], normalized),
                )
                updated = connection.execute(
                    """
                    SELECT id, title, description, category, deadline, estimated_minutes,
                           difficulty, priority, status, created_at
                    FROM tasks
                    WHERE id = ? AND profile_id = ?
                    """,
                    (row["id"], normalized),
                ).fetchone()
                return Task.model_validate(dict(updated)), False

            task_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO tasks (
                    id, profile_id, title, description, category, deadline,
                    estimated_minutes, difficulty, priority, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    normalized,
                    payload_dump["title"],
                    payload_dump["description"],
                    payload_dump["category"],
                    payload_dump["deadline"],
                    payload_dump["estimated_minutes"],
                    payload_dump["difficulty"],
                    payload_dump["priority"],
                    "pending",
                    now.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO task_sources (
                    task_id, profile_id, provider, scope_id, external_ref, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    normalized,
                    "canvas_assignment",
                    scope_id,
                    assignment_id,
                    now.isoformat(),
                ),
            )

        return Task(id=task_id, status="pending", created_at=now, **payload.model_dump()), True

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
            connection.execute(
                "DELETE FROM commitment_sources WHERE commitment_id = ? AND profile_id = ?",
                (commitment_id, normalized),
            )
            cursor = connection.execute(
                "DELETE FROM commitments WHERE id = ? AND profile_id = ?",
                (commitment_id, normalized),
            )
        return cursor.rowcount > 0

    def upsert_google_commitment(
        self,
        payload: FixedCommitmentInput,
        profile_id: str,
        external_ref: str,
        calendar_id: str,
    ) -> tuple[FixedCommitment, bool]:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        now = datetime.utcnow()
        payload_dump = payload.model_dump(mode="json")

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.id, c.created_at
                FROM commitment_sources cs
                JOIN commitments c ON c.id = cs.commitment_id
                WHERE cs.profile_id = ? AND cs.provider = ? AND cs.calendar_id = ? AND cs.external_ref = ?
                """,
                (normalized, "google_calendar", calendar_id, external_ref),
            ).fetchone()

            if row:
                connection.execute(
                    """
                    UPDATE commitments
                    SET title = ?, day_of_week = ?, start = ?, end = ?, kind = ?, location = ?, notes = ?
                    WHERE id = ? AND profile_id = ?
                    """,
                    (
                        payload_dump["title"],
                        payload_dump["day_of_week"],
                        payload_dump["start"],
                        payload_dump["end"],
                        payload_dump["kind"],
                        payload_dump["location"],
                        payload_dump["notes"],
                        row["id"],
                        normalized,
                    ),
                )
                connection.execute(
                    """
                    UPDATE commitment_sources
                    SET last_synced_at = ?
                    WHERE commitment_id = ? AND profile_id = ?
                    """,
                    (now.isoformat(), row["id"], normalized),
                )
                commitment = connection.execute(
                    """
                    SELECT id, title, day_of_week, start, end, kind, location, notes, created_at
                    FROM commitments
                    WHERE id = ? AND profile_id = ?
                    """,
                    (row["id"], normalized),
                ).fetchone()
                return FixedCommitment.model_validate(dict(commitment)), False

            commitment_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO commitments (
                    id, profile_id, title, day_of_week, start, end, kind, location, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commitment_id,
                    normalized,
                    payload_dump["title"],
                    payload_dump["day_of_week"],
                    payload_dump["start"],
                    payload_dump["end"],
                    payload_dump["kind"],
                    payload_dump["location"],
                    payload_dump["notes"],
                    now.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO commitment_sources (
                    commitment_id, profile_id, provider, calendar_id, external_ref, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    commitment_id,
                    normalized,
                    "google_calendar",
                    calendar_id,
                    external_ref,
                    now.isoformat(),
                ),
            )

        return FixedCommitment(
            id=commitment_id,
            created_at=now,
            **payload.model_dump(),
        ), True

    def create_oauth_state(self, provider: str, profile_id: str) -> str:
        normalized = self._normalize_profile_id(profile_id)
        state = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (provider, state, profile_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (provider, state, normalized, datetime.utcnow().isoformat()),
            )
        return state

    def consume_oauth_state(self, provider: str, state: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT profile_id FROM oauth_states WHERE provider = ? AND state = ?",
                (provider, state),
            ).fetchone()
            connection.execute(
                "DELETE FROM oauth_states WHERE provider = ? AND state = ?",
                (provider, state),
            )
        return row["profile_id"] if row else None

    def upsert_google_connection(
        self,
        profile_id: str,
        *,
        email: str,
        access_token: str,
        refresh_token: str,
        scope: str,
        token_expiry: datetime | None,
    ) -> GoogleConnection:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        now = datetime.utcnow()
        expiry_value = token_expiry.isoformat() if token_expiry else None

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO google_connections (
                    profile_id, email, access_token, refresh_token, scope, token_expiry, created_at, updated_at, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                    (SELECT last_synced_at FROM google_connections WHERE profile_id = ?),
                    NULL
                ))
                ON CONFLICT(profile_id) DO UPDATE SET
                    email = excluded.email,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    scope = excluded.scope,
                    token_expiry = excluded.token_expiry,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized,
                    email,
                    access_token,
                    refresh_token,
                    scope,
                    expiry_value,
                    now.isoformat(),
                    now.isoformat(),
                    normalized,
                ),
            )
            row = connection.execute(
                """
                SELECT profile_id, email, access_token, refresh_token, scope, token_expiry, created_at, updated_at, last_synced_at
                FROM google_connections
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()

        return GoogleConnection.model_validate(dict(row))

    def get_google_connection(self, profile_id: str) -> GoogleConnection | None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT profile_id, email, access_token, refresh_token, scope, token_expiry, created_at, updated_at, last_synced_at
                FROM google_connections
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()
        return GoogleConnection.model_validate(dict(row)) if row else None

    def clear_google_connection(self, profile_id: str) -> None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM google_connections WHERE profile_id = ?", (normalized,))
            connection.execute("DELETE FROM oauth_states WHERE provider = ? AND profile_id = ?", ("google", normalized))

    def touch_google_sync(self, profile_id: str) -> GoogleConnection | None:
        normalized = self._normalize_profile_id(profile_id)
        now = datetime.utcnow().isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE google_connections SET last_synced_at = ?, updated_at = ? WHERE profile_id = ?",
                (now, now, normalized),
            )
            row = connection.execute(
                """
                SELECT profile_id, email, access_token, refresh_token, scope, token_expiry, created_at, updated_at, last_synced_at
                FROM google_connections
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()
        return GoogleConnection.model_validate(dict(row)) if row else None

    def upsert_canvas_connection(
        self,
        profile_id: str,
        *,
        base_url: str,
        access_token: str,
    ) -> CanvasConnection:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        now = datetime.utcnow()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO canvas_connections (
                    profile_id, base_url, access_token, created_at, updated_at, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, COALESCE(
                    (SELECT last_synced_at FROM canvas_connections WHERE profile_id = ?),
                    NULL
                ))
                ON CONFLICT(profile_id) DO UPDATE SET
                    base_url = excluded.base_url,
                    access_token = excluded.access_token,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized,
                    base_url,
                    access_token,
                    now.isoformat(),
                    now.isoformat(),
                    normalized,
                ),
            )
            row = connection.execute(
                """
                SELECT profile_id, base_url, access_token, created_at, updated_at, last_synced_at
                FROM canvas_connections
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()

        return CanvasConnection.model_validate(dict(row))

    def get_canvas_connection(self, profile_id: str) -> CanvasConnection | None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT profile_id, base_url, access_token, created_at, updated_at, last_synced_at
                FROM canvas_connections
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()
        return CanvasConnection.model_validate(dict(row)) if row else None

    def clear_canvas_connection(self, profile_id: str) -> None:
        normalized = self._normalize_profile_id(profile_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM canvas_connections WHERE profile_id = ?", (normalized,))

    def touch_canvas_sync(self, profile_id: str) -> CanvasConnection | None:
        normalized = self._normalize_profile_id(profile_id)
        now = datetime.utcnow().isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE canvas_connections SET last_synced_at = ?, updated_at = ? WHERE profile_id = ?",
                (now, now, normalized),
            )
            row = connection.execute(
                """
                SELECT profile_id, base_url, access_token, created_at, updated_at, last_synced_at
                FROM canvas_connections
                WHERE profile_id = ?
                """,
                (normalized,),
            ).fetchone()
        return CanvasConnection.model_validate(dict(row)) if row else None

    def save_weekly_plan(
        self,
        plan: WeeklyPlanResponse,
        profile_id: str = DEFAULT_PROFILE_ID,
        *,
        source_action: str,
    ) -> SavedPlanResponse:
        normalized = self._normalize_profile_id(profile_id)
        self._ensure_profile(normalized)
        now = datetime.utcnow().isoformat()
        payload = plan.model_dump(mode="json")
        plan_id = str(uuid4())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, created_at FROM saved_plans WHERE profile_id = ? AND week_start = ?",
                (normalized, payload["week_start"]),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO saved_plans (id, profile_id, week_start, source_action, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, week_start) DO UPDATE SET
                    source_action = excluded.source_action,
                    plan_json = excluded.plan_json,
                    updated_at = excluded.updated_at
                """,
                (
                    existing["id"] if existing else plan_id,
                    normalized,
                    payload["week_start"],
                    source_action,
                    json.dumps(payload),
                    existing["created_at"] if existing else now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT id, source_action, plan_json, updated_at
                FROM saved_plans
                WHERE profile_id = ? AND week_start = ?
                """,
                (normalized, payload["week_start"]),
            ).fetchone()
        return SavedPlanResponse(
            id=row["id"],
            source_action=row["source_action"],
            saved_at=datetime.fromisoformat(row["updated_at"]),
            plan=WeeklyPlanResponse.model_validate(json.loads(row["plan_json"])),
        )

    def get_latest_saved_plan(
        self,
        profile_id: str = DEFAULT_PROFILE_ID,
        *,
        week_start: str | None = None,
    ) -> SavedPlanResponse | None:
        normalized = self._normalize_profile_id(profile_id)
        query = """
            SELECT id, source_action, plan_json, updated_at
            FROM saved_plans
            WHERE profile_id = ?
        """
        params: list[str] = [normalized]
        if week_start:
            query += " AND week_start = ?"
            params.append(week_start)
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, tuple(params)).fetchone()
        if not row:
            return None
        return SavedPlanResponse(
            id=row["id"],
            source_action=row["source_action"],
            saved_at=datetime.fromisoformat(row["updated_at"]),
            plan=WeeklyPlanResponse.model_validate(json.loads(row["plan_json"])),
        )

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
