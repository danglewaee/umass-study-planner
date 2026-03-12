from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import uuid4

from .models import ScheduleBlock, Task, UserInsights, UserPreferences, WeeklyPlanResponse


def _add_minutes(start: time, minutes: int) -> time:
    anchor = datetime.combine(date.today(), start)
    shifted = anchor + timedelta(minutes=minutes)
    return shifted.time().replace(second=0, microsecond=0)


def _weekday_offsets(week_start: date) -> list[date]:
    return [week_start + timedelta(days=offset) for offset in range(7)]


def _create_sleep_blocks(days: list[date], preferences: UserPreferences) -> list[ScheduleBlock]:
    blocks: list[ScheduleBlock] = []
    for current_day in days:
        blocks.append(
            ScheduleBlock(
                id=str(uuid4()),
                title="Sleep",
                day=current_day,
                start=preferences.sleep_start,
                end=time(hour=23, minute=59) if preferences.sleep_start > preferences.sleep_end else preferences.sleep_end,
                kind="sleep",
                reasoning="Protected recovery block based on sleep target.",
            )
        )
    return blocks


def generate_weekly_plan(tasks: list[Task], week_start: date, preferences: UserPreferences) -> WeeklyPlanResponse:
    blocks: list[ScheduleBlock] = []
    alerts: list[str] = []
    days = _weekday_offsets(week_start)
    blocks.extend(_create_sleep_blocks(days, preferences))

    daily_loads = {day: 0 for day in days}
    current_day_index = 0
    current_start = preferences.focus_start

    ranked_tasks = sorted(tasks, key=lambda item: (item.deadline, -item.priority, -item.difficulty))

    for task in ranked_tasks:
        duration = min(task.estimated_minutes, preferences.preferred_block_minutes)
        if current_day_index >= len(days):
            alerts.append("This week is over capacity. Reduce scope or move lower-priority work.")
            break

        assigned_day = days[current_day_index]
        day_limit = preferences.max_deep_blocks_per_day * preferences.preferred_block_minutes

        if daily_loads[assigned_day] + duration > day_limit:
            current_day_index += 1
            current_start = preferences.focus_start
            if current_day_index >= len(days):
                alerts.append("Not all tasks fit without harming balance constraints.")
                break
            assigned_day = days[current_day_index]

        end = _add_minutes(current_start, duration)
        blocks.append(
            ScheduleBlock(
                id=str(uuid4()),
                title=task.title,
                task_id=task.id,
                day=assigned_day,
                start=current_start,
                end=end,
                kind="deep_work",
                reasoning=(
                    f"Scheduled in a focus window using urgency={task.priority} and difficulty={task.difficulty}."
                ),
            )
        )
        blocks.append(
            ScheduleBlock(
                id=str(uuid4()),
                title="Break",
                day=assigned_day,
                start=end,
                end=_add_minutes(end, preferences.break_minutes),
                kind="break",
                reasoning="Inserted recovery buffer to preserve sustainable pacing.",
            )
        )
        daily_loads[assigned_day] += duration
        current_start = _add_minutes(end, preferences.break_minutes)

        if daily_loads[assigned_day] >= day_limit:
            current_day_index += 1
            current_start = preferences.focus_start

    overloaded_days = sum(1 for minutes in daily_loads.values() if minutes >= preferences.max_deep_blocks_per_day * preferences.preferred_block_minutes)
    if overloaded_days >= 3:
        alerts.append("Three or more days are near your focus cap. Consider reducing expected workload.")

    score_summary = {
        "goal_progress": round(min(len(ranked_tasks), len([block for block in blocks if block.kind == 'deep_work'])) / max(len(ranked_tasks), 1), 2),
        "consistency": round(max(0.25, 1 - overloaded_days / 7), 2),
        "balance": round(max(0.2, 1 - overloaded_days / 5), 2),
    }

    if not alerts:
        alerts.append("Plan looks balanced. Protect sleep and keep momentum with small daily wins.")

    return WeeklyPlanResponse(week_start=week_start, blocks=sorted(blocks, key=lambda block: (block.day, block.start)), alerts=alerts, score_summary=score_summary)


def derive_user_insights(tasks: list[Task], stress_level: int | None) -> UserInsights:
    hard_tasks = sum(1 for task in tasks if task.difficulty >= 4)
    recruiting_tasks = sum(1 for task in tasks if str(task.category) == "TaskCategory.recruiting" or str(task.category) == "recruiting")

    strongest_window = "Morning deep work" if hard_tasks >= 2 else "Midday focused blocks"
    consistency_risk = "medium" if len(tasks) >= 6 else "low"
    overload_risk = "high" if (stress_level or 0) >= 4 and hard_tasks >= 2 else "medium" if hard_tasks >= 3 else "low"

    guidance = [
        "Keep one protected recovery block every day to sustain consistency.",
        "Break high-ambiguity tasks into 60 to 90 minute blocks before scheduling.",
    ]
    if recruiting_tasks:
        guidance.append("Batch recruiting admin work into one lighter block to reduce context switching.")
    if overload_risk == "high":
        guidance.append("Your current pattern suggests overload risk. Drop or defer one non-critical task this week.")

    return UserInsights(
        strongest_window=strongest_window,
        consistency_risk=consistency_risk,
        overload_risk=overload_risk,
        guidance=guidance,
    )


def parse_brain_dump(text: str) -> list[dict[str, object]]:
    lines = [line.strip("- *\t ") for line in text.splitlines() if line.strip()]
    today = datetime.utcnow().date()
    parsed: list[dict[str, object]] = []
    for index, line in enumerate(lines[:8]):
        lowered = line.lower()
        category = "academics"
        if any(keyword in lowered for keyword in ["intern", "resume", "apply", "recruiter", "career"]):
            category = "recruiting"
        elif any(keyword in lowered for keyword in ["gym", "sleep", "walk", "health", "meal"]):
            category = "health"
        elif any(keyword in lowered for keyword in ["family", "laundry", "call", "groceries"]):
            category = "personal"

        parsed.append(
            {
                "title": line[:120],
                "description": "Generated from brain dump input.",
                "category": category,
                "deadline": today + timedelta(days=min(index + 1, 7)),
                "estimated_minutes": 60 if category != "health" else 45,
                "difficulty": 4 if category == "academics" else 2,
                "priority": 4 if index < 3 else 3,
            }
        )
    return parsed
