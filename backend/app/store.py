from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .models import CheckIn, CheckInInput, FixedCommitment, FixedCommitmentInput, Task, TaskInput, UserPreferences


@dataclass
class AppState:
    tasks: list[Task]
    check_ins: list[CheckIn]
    commitments: list[FixedCommitment]
    preferences: UserPreferences


class InMemoryStore:
    def __init__(self) -> None:
        self.state = AppState(tasks=[], check_ins=[], commitments=[], preferences=UserPreferences())
        self._seed_data()

    def _seed_data(self) -> None:
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
            self.add_task(task)

    def add_task(self, payload: TaskInput) -> Task:
        task = Task(
            id=str(uuid4()),
            created_at=datetime.utcnow(),
            **payload.model_dump(),
        )
        self.state.tasks.append(task)
        return task

    def list_tasks(self) -> list[Task]:
        return sorted(self.state.tasks, key=lambda item: (item.deadline, -item.priority))

    def get_task(self, task_id: str) -> Task | None:
        for task in self.state.tasks:
            if task.id == task_id:
                return task
        return None

    def mark_delayed(self, task_id: str) -> Task | None:
        task = self.get_task(task_id)
        if task:
            task.status = "delayed"
        return task

    def add_check_in(self, payload: CheckInInput) -> CheckIn:
        check_in = CheckIn(id=str(uuid4()), created_at=datetime.utcnow(), **payload.model_dump())
        self.state.check_ins.append(check_in)
        return check_in

    def list_check_ins(self) -> list[CheckIn]:
        return list(self.state.check_ins)

    def add_commitment(self, payload: FixedCommitmentInput) -> FixedCommitment:
        commitment = FixedCommitment(
            id=str(uuid4()),
            created_at=datetime.utcnow(),
            **payload.model_dump(),
        )
        self.state.commitments.append(commitment)
        return commitment

    def list_commitments(self) -> list[FixedCommitment]:
        return sorted(self.state.commitments, key=lambda item: (item.day_of_week, item.start, item.title))

    def delete_commitment(self, commitment_id: str) -> bool:
        for index, commitment in enumerate(self.state.commitments):
            if commitment.id == commitment_id:
                del self.state.commitments[index]
                return True
        return False

    def get_preferences(self) -> UserPreferences:
        return self.state.preferences

    def set_preferences(self, preferences: UserPreferences) -> UserPreferences:
        self.state.preferences = preferences
        return preferences

    def category_counts(self) -> dict[str, int]:
        counts: defaultdict[str, int] = defaultdict(int)
        for task in self.state.tasks:
            counts[str(task.category)] += 1
        return dict(counts)


store = InMemoryStore()
