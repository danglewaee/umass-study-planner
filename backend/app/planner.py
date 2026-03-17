from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from .models import (
    PlanMetrics,
    PlanStrategy,
    ScheduleBlock,
    Task,
    TaskStatus,
    UserInsights,
    UserPreferences,
    WeeklyPlanResponse,
)


@dataclass(frozen=True)
class StrategyProfile:
    name: PlanStrategy
    capacity_multiplier: float
    break_delta_minutes: int = 0
    preserve_existing_blocks: bool = True
    focus_end_extension_minutes: int = 0
    soft_capacity_overflow_minutes: int = 0


STRATEGY_PROFILES: dict[PlanStrategy, StrategyProfile] = {
    PlanStrategy.stability_aware: StrategyProfile(
        name=PlanStrategy.stability_aware,
        capacity_multiplier=1.0,
        break_delta_minutes=0,
        preserve_existing_blocks=True,
        focus_end_extension_minutes=0,
        soft_capacity_overflow_minutes=0,
    ),
    PlanStrategy.deadline_rescue: StrategyProfile(
        name=PlanStrategy.deadline_rescue,
        capacity_multiplier=1.15,
        break_delta_minutes=-5,
        preserve_existing_blocks=False,
        focus_end_extension_minutes=60,
        soft_capacity_overflow_minutes=90,
    ),
    PlanStrategy.load_balance: StrategyProfile(
        name=PlanStrategy.load_balance,
        capacity_multiplier=0.95,
        break_delta_minutes=5,
        preserve_existing_blocks=True,
        focus_end_extension_minutes=0,
        soft_capacity_overflow_minutes=0,
    ),
    PlanStrategy.focus_windows: StrategyProfile(
        name=PlanStrategy.focus_windows,
        capacity_multiplier=0.9,
        break_delta_minutes=10,
        preserve_existing_blocks=True,
        focus_end_extension_minutes=0,
        soft_capacity_overflow_minutes=0,
    ),
}


def available_strategies() -> list[str]:
    return [strategy.value for strategy in PlanStrategy]


def get_strategy_profile(strategy: PlanStrategy | str | None) -> StrategyProfile:
    if isinstance(strategy, PlanStrategy):
        return STRATEGY_PROFILES[strategy]
    if isinstance(strategy, str):
        try:
            return STRATEGY_PROFILES[PlanStrategy(strategy)]
        except ValueError:
            return STRATEGY_PROFILES[PlanStrategy.stability_aware]
    return STRATEGY_PROFILES[PlanStrategy.stability_aware]


def _add_minutes(start: time, minutes: int) -> time:
    anchor = datetime.combine(date.today(), start)
    shifted = anchor + timedelta(minutes=minutes)
    return shifted.time().replace(second=0, microsecond=0)


def _weekday_offsets(week_start: date) -> list[date]:
    return [week_start + timedelta(days=offset) for offset in range(7)]


def _minutes_between(start: time, end: time) -> int:
    anchor = datetime.combine(date.today(), start)
    finish = datetime.combine(date.today(), end)
    return int((finish - anchor).total_seconds() // 60)


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


def generate_weekly_plan(
    tasks: list[Task],
    week_start: date,
    preferences: UserPreferences,
    strategy: PlanStrategy = PlanStrategy.stability_aware,
    previous_plan: WeeklyPlanResponse | None = None,
) -> WeeklyPlanResponse:
    profile = get_strategy_profile(strategy)
    days = _weekday_offsets(week_start)
    week_end = days[-1]
    break_minutes = max(5, preferences.break_minutes + profile.break_delta_minutes)
    daily_limit_minutes = int(preferences.max_deep_blocks_per_day * preferences.preferred_block_minutes * profile.capacity_multiplier)
    latest_focus_end = _add_minutes(preferences.focus_end, profile.focus_end_extension_minutes)

    blocks: list[ScheduleBlock] = []
    alerts: list[str] = []
    blocks.extend(_create_sleep_blocks(days, preferences))

    daily_loads = {day: 0 for day in days}
    day_next_start = {day: preferences.focus_start for day in days}
    task_lookup = {task.id: task for task in tasks}
    previous_task_blocks = {
        block.task_id: block
        for block in (previous_plan.blocks if previous_plan else [])
        if block.kind == "deep_work" and block.task_id
    }

    scheduled_task_ids: set[str] = set()
    preserved_blocks = 0
    off_window_blocks = 0

    if previous_plan and profile.preserve_existing_blocks:
        for task_id, block in sorted(previous_task_blocks.items(), key=lambda item: (item[1].day, item[1].start)):
            task = task_lookup.get(task_id)
            if not task or task.status == TaskStatus.completed or task.status == TaskStatus.delayed:
                continue
            if block.day < week_start or block.day > week_end:
                continue
            duration_minutes = _minutes_between(block.start, block.end)
            if duration_minutes <= 0:
                continue
            if block.start < preferences.focus_start or block.end > latest_focus_end:
                continue
            if daily_loads[block.day] + duration_minutes > daily_limit_minutes + profile.soft_capacity_overflow_minutes:
                continue

            _append_task_block(blocks, task, block.day, block.start, duration_minutes, break_minutes, preserved=True)
            scheduled_task_ids.add(task.id)
            preserved_blocks += 1
            daily_loads[block.day] += duration_minutes
            day_next_start[block.day] = max_time(day_next_start[block.day], _add_minutes(block.end, break_minutes))
            if block.end > preferences.focus_end:
                off_window_blocks += 1

    ranked_tasks = _rank_tasks(tasks, week_start, strategy)
    unscheduled_tasks = 0

    for task in ranked_tasks:
        if task.id in scheduled_task_ids or task.status == TaskStatus.completed:
            continue

        duration_minutes = _task_block_minutes(task, preferences, strategy)
        candidate_day_order = _candidate_days(task, days, daily_loads, week_start, strategy)
        assigned = False

        for assigned_day in candidate_day_order:
            if assigned_day > min(task.deadline, week_end):
                continue
            proposed_start = day_next_start[assigned_day]
            proposed_end = _add_minutes(proposed_start, duration_minutes)
            overflow_limit = daily_limit_minutes + profile.soft_capacity_overflow_minutes
            if proposed_start < preferences.focus_start:
                proposed_start = preferences.focus_start
                proposed_end = _add_minutes(proposed_start, duration_minutes)
            if proposed_end > latest_focus_end:
                continue
            if daily_loads[assigned_day] + duration_minutes > overflow_limit:
                continue

            _append_task_block(blocks, task, assigned_day, proposed_start, duration_minutes, break_minutes, preserved=False)
            scheduled_task_ids.add(task.id)
            daily_loads[assigned_day] += duration_minutes
            day_next_start[assigned_day] = _add_minutes(proposed_end, break_minutes)
            if proposed_end > preferences.focus_end:
                off_window_blocks += 1
            assigned = True
            break

        if not assigned:
            unscheduled_tasks += 1
            alerts.append(f"Could not fit '{task.title}' without breaking current balance constraints.")

    overload_days = sum(1 for minutes in daily_loads.values() if minutes > preferences.max_deep_blocks_per_day * preferences.preferred_block_minutes)
    scheduled_tasks = len(scheduled_task_ids)
    total_tasks = len([task for task in tasks if task.status != TaskStatus.completed])
    previous_deep_blocks = len(previous_task_blocks)
    stability_pct = round((preserved_blocks / previous_deep_blocks) * 100.0, 2) if previous_deep_blocks else 100.0
    focus_alignment_pct = round(
        ((scheduled_tasks - off_window_blocks) / max(scheduled_tasks, 1)) * 100.0,
        2,
    )

    if overload_days >= 3:
        alerts.append("Three or more days exceed your preferred deep-work load. Consider dropping or deferring work.")
    if strategy == PlanStrategy.deadline_rescue:
        alerts.append("Deadline rescue mode is prioritizing urgent work and allowing more schedule churn.")
    elif strategy == PlanStrategy.load_balance:
        alerts.append("Load-balance mode is spreading work more evenly across the week.")
    elif strategy == PlanStrategy.focus_windows:
        alerts.append("Focus-window mode is protecting your preferred study windows more aggressively.")
    if not alerts:
        alerts.append("Plan looks balanced. Protect sleep and keep momentum with small daily wins.")

    score_summary = {
        "goal_progress": round(scheduled_tasks / max(total_tasks, 1), 2),
        "consistency": round(max(0.2, stability_pct / 100 if previous_plan else 1 - overload_days / 7), 2),
        "balance": round(max(0.2, 1 - overload_days / 5), 2),
    }

    metrics = PlanMetrics(
        scheduled_tasks=scheduled_tasks,
        unscheduled_tasks=unscheduled_tasks,
        preserved_blocks=preserved_blocks,
        schedule_stability_pct=stability_pct,
        overload_days=overload_days,
        off_window_blocks=off_window_blocks,
        total_deep_work_minutes=sum(daily_loads.values()),
        focus_alignment_pct=focus_alignment_pct,
    )

    ordered_blocks = sorted(blocks, key=lambda block: (block.day, block.start, block.kind))
    return WeeklyPlanResponse(
        week_start=week_start,
        blocks=ordered_blocks,
        alerts=alerts,
        score_summary=score_summary,
        strategy_used=strategy,
        metrics=metrics,
    )


def _append_task_block(
    blocks: list[ScheduleBlock],
    task: Task,
    assigned_day: date,
    start: time,
    duration_minutes: int,
    break_minutes: int,
    preserved: bool,
) -> None:
    end = _add_minutes(start, duration_minutes)
    reasoning_prefix = "Preserved from previous plan" if preserved else "Scheduled using strategy-aware prioritization"
    blocks.append(
        ScheduleBlock(
            id=str(uuid4()),
            title=task.title,
            task_id=task.id,
            day=assigned_day,
            start=start,
            end=end,
            kind="deep_work",
            reasoning=(
                f"{reasoning_prefix}; urgency={task.priority}, difficulty={task.difficulty}, status={task.status}."
            ),
        )
    )
    break_end = _add_minutes(end, break_minutes)
    blocks.append(
        ScheduleBlock(
            id=str(uuid4()),
            title="Break",
            day=assigned_day,
            start=end,
            end=break_end,
            kind="break",
            reasoning="Inserted recovery buffer to preserve sustainable pacing.",
        )
    )


def _task_block_minutes(task: Task, preferences: UserPreferences, strategy: PlanStrategy) -> int:
    base = min(task.estimated_minutes, preferences.preferred_block_minutes)
    if strategy == PlanStrategy.deadline_rescue:
        return min(task.estimated_minutes, preferences.preferred_block_minutes + 30)
    if strategy == PlanStrategy.focus_windows:
        return min(base, 75)
    return base


def _rank_tasks(tasks: list[Task], week_start: date, strategy: PlanStrategy) -> list[Task]:
    def urgency_days(task: Task) -> int:
        return max((task.deadline - week_start).days, 0)

    if strategy == PlanStrategy.deadline_rescue:
        return sorted(
            tasks,
            key=lambda task: (
                urgency_days(task),
                0 if task.status == TaskStatus.delayed else 1,
                -task.priority,
                -task.difficulty,
            ),
        )
    if strategy == PlanStrategy.load_balance:
        return sorted(
            tasks,
            key=lambda task: (
                0 if task.category == "health" else 1,
                urgency_days(task),
                -task.priority,
                -task.difficulty,
            ),
        )
    if strategy == PlanStrategy.focus_windows:
        return sorted(
            tasks,
            key=lambda task: (
                urgency_days(task),
                -task.difficulty,
                -task.priority,
                0 if task.category == "academics" else 1,
            ),
        )
    return sorted(
        tasks,
        key=lambda task: (
            0 if task.status == TaskStatus.delayed else 1,
            urgency_days(task),
            -task.priority,
            -task.difficulty,
        ),
    )


def _candidate_days(
    task: Task,
    days: list[date],
    daily_loads: dict[date, int],
    week_start: date,
    strategy: PlanStrategy,
) -> list[date]:
    latest_date = min(task.deadline, days[-1])
    candidates = [day for day in days if week_start <= day <= latest_date]
    if strategy == PlanStrategy.load_balance:
        return sorted(candidates, key=lambda day: (daily_loads[day], day))
    if strategy == PlanStrategy.focus_windows:
        return sorted(candidates, key=lambda day: (abs((task.deadline - day).days), day))
    return candidates


def max_time(left: time, right: time) -> time:
    return left if left >= right else right


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
