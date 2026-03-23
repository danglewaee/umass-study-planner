from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin

import httpx

from .models import CanvasCourseSummary, TaskCategory, TaskInput


def normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip()
    if not normalized:
        raise ValueError("Canvas base URL is required.")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return normalized.rstrip("/")


def list_courses(base_url: str, access_token: str) -> list[CanvasCourseSummary]:
    items = _paginated_get(
        normalize_base_url(base_url),
        "/api/v1/courses",
        access_token,
        params={
            "per_page": "100",
            "enrollment_state": "active",
        },
    )
    return [
        CanvasCourseSummary(
            id=item["id"],
            name=item.get("name") or item.get("course_code") or f"Course {item['id']}",
            course_code=item.get("course_code"),
            workflow_state=item.get("workflow_state"),
        )
        for item in items
        if item.get("id") is not None
    ]


def list_assignments(base_url: str, access_token: str, course_id: int) -> list[dict[str, Any]]:
    return _paginated_get(
        normalize_base_url(base_url),
        f"/api/v1/courses/{course_id}/assignments",
        access_token,
        params={"per_page": "100"},
    )


def infer_assignment_tasks(
    assignments: list[dict[str, Any]],
    *,
    course_name: str,
    default_estimated_minutes: int,
    default_difficulty: int,
) -> tuple[list[tuple[str, TaskInput]], int]:
    task_candidates: list[tuple[str, TaskInput]] = []
    skipped_assignments = 0
    normalized_course_name = (course_name or "").strip() or "Canvas Course"

    for assignment in assignments:
        try:
            due_at_raw = assignment.get("due_at")
            assignment_id = assignment.get("id")
            assignment_name = (assignment.get("name") or "").strip()
            if not due_at_raw or assignment_id is None or not assignment_name:
                skipped_assignments += 1
                continue

            due_at = _parse_canvas_datetime(due_at_raw)
            deadline = due_at.date()
            task_title = _truncate(f"{normalized_course_name}: {assignment_name}", 120)
            task_description = _build_assignment_description(assignment, normalized_course_name)
            priority = _priority_for_deadline(deadline)

            task_candidates.append(
                (
                    str(assignment_id),
                    TaskInput(
                        title=task_title,
                        description=task_description,
                        category=TaskCategory.academics,
                        deadline=deadline,
                        estimated_minutes=default_estimated_minutes,
                        difficulty=default_difficulty,
                        priority=priority,
                    ),
                )
            )
        except Exception:
            skipped_assignments += 1
            continue

    return task_candidates, skipped_assignments


def _paginated_get(
    base_url: str,
    path: str,
    access_token: str,
    *,
    params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    url = urljoin(f"{base_url}/", path.lstrip("/"))
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    next_params: dict[str, str] | None = params

    while next_url:
        response = httpx.get(
            next_url,
            params=next_params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            items.extend(payload)
        else:
            raise RuntimeError("Canvas response was not a list payload.")

        next_url = response.links.get("next", {}).get("url")
        next_params = None

    return items


def _parse_canvas_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _build_assignment_description(assignment: dict[str, Any], course_name: str) -> str:
    fragments = [f"Imported from Canvas course {course_name}."]
    description_html = assignment.get("description") or ""
    if description_html:
        cleaned = _clean_html(description_html)
        if cleaned:
            fragments.append(cleaned)
    html_url = assignment.get("html_url")
    if html_url:
        fragments.append(f"Canvas link: {html_url}")
    return _truncate(" ".join(fragments), 600)


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = re.sub(r"\s+", " ", unescape(without_tags)).strip()
    return normalized


def _priority_for_deadline(deadline) -> int:
    days_out = (deadline - date.today()).days
    if days_out <= 2:
        return 5
    if days_out <= 5:
        return 4
    return 3


def _truncate(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 1)].rstrip() + "..."
