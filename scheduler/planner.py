from __future__ import annotations

import time
from collections import Counter
from collections import defaultdict

from ortools.sat.python import cp_model

from api.schemas import DAYS_PER_WEEK, PlanMetrics, PlanResult, PlannedTask, SLOTS_PER_DAY, TOTAL_SLOTS, Scenario, Task
from scheduler.policy_profiles import get_planning_policy, get_repair_policy
from scheduler.stability import evaluate_schedule_stability
from scheduler.utils import blocked_slots, preferred_window_slots

MIN_SPLIT_CHUNK_SLOTS = 2
MAX_SPLIT_GAP_SLOTS = 24
MAX_SPLIT_LAYOUTS = 24
MAX_SINGLE_LAYOUTS = 36
MAX_TOTAL_LAYOUTS = 48
MAX_LAYOUTS_PER_BUCKET = 3
LAYOUT_BUCKET_SLOTS = 8


def solve_scenario(scenario: Scenario) -> PlanResult:
    return _solve(scenario, previous_plan=None, strategy_name=get_planning_policy().name)


def replan_scenario(scenario: Scenario, previous_plan: PlanResult, strategy_name: str | None = None) -> PlanResult:
    return _solve(scenario, previous_plan=previous_plan, strategy_name=strategy_name)


def _solve(scenario: Scenario, previous_plan: PlanResult | None, strategy_name: str | None) -> PlanResult:
    started = time.perf_counter()
    model = cp_model.CpModel()
    blocked = blocked_slots(scenario)
    preferred = preferred_window_slots(scenario)
    policy = get_planning_policy() if previous_plan is None else get_repair_policy(strategy_name)
    weights = policy.weights
    effective_previous_plan = previous_plan if policy.use_previous_layout else None
    previous_signatures = {
        item.task_id: _task_signature(item)
        for item in (effective_previous_plan.items if effective_previous_plan else [])
        if item.scheduled
    }

    layout_vars: dict[tuple[str, int], cp_model.IntVar] = {}
    missed_vars: dict[str, cp_model.IntVar] = {}
    daily_overload: list[cp_model.IntVar] = []
    off_window_terms = []
    cram_terms = []
    churn_terms = []
    fragmentation_terms = []
    churn_base = 0
    slot_terms: dict[int, list[cp_model.IntVar]] = defaultdict(list)
    day_terms: dict[int, list] = defaultdict(list)

    layouts_by_task: dict[str, list[dict]] = {}
    for task in scenario.tasks:
        layouts = _generate_layouts(
            task,
            blocked,
            preferred,
            previous_signatures.get(task.id),
            allow_split_override=policy.allow_split_override,
        )
        layouts_by_task[task.id] = layouts
        missed = model.NewBoolVar(f"missed_{task.id}")
        missed_vars[task.id] = missed

        vars_for_task = []
        for idx, layout in enumerate(layouts):
            var = model.NewBoolVar(f"task_{task.id}_layout_{idx}")
            layout_vars[(task.id, idx)] = var
            vars_for_task.append(var)
            for slot in layout["covered_slots"]:
                slot_terms[slot].append(var)
            for day, overlap in layout["day_loads"].items():
                day_terms[day].append(overlap * var)
            if layout["off_window_penalty"]:
                off_window_terms.append(int(layout["off_window_penalty"]) * var)
            if layout["cram_penalty"]:
                cram_terms.append(int(layout["cram_penalty"]) * var)
            if layout["fragmentation_penalty"]:
                fragmentation_terms.append(int(layout["fragmentation_penalty"]) * var)

        if vars_for_task:
            model.Add(sum(vars_for_task) + missed == 1)
        else:
            model.Add(missed == 1)

        previous_signature = previous_signatures.get(task.id)
        if previous_signature is not None:
            matched_index = next(
                (idx for idx, layout in enumerate(layouts) if layout["signature"] == previous_signature),
                None,
            )
            if matched_index is not None:
                changed = model.NewBoolVar(f"changed_{task.id}")
                model.Add(changed + layout_vars[(task.id, matched_index)] == 1)
                churn_terms.append(changed)
            else:
                churn_base += 1

    for slot in range(DAYS_PER_WEEK * SLOTS_PER_DAY):
        overlapping = slot_terms.get(slot)
        if overlapping:
            model.Add(sum(overlapping) <= 1)

    for day in range(DAYS_PER_WEEK):
        overload = model.NewIntVar(0, 24, f"overload_day_{day}")
        daily_overload.append(overload)
        load_terms = day_terms.get(day, [])
        if load_terms:
            model.Add(sum(load_terms) - scenario.preferences.max_daily_study_slots <= overload)
        else:
            model.Add(overload == 0)

    objective = (
        weights["missed"] * sum(missed_vars.values())
        + weights["overload"] * sum(daily_overload)
        + weights["cram"] * sum(cram_terms)
        + weights["churn"] * (sum(churn_terms) + churn_base)
        + weights["off_window"] * sum(off_window_terms)
        + weights["fragmentation"] * sum(fragmentation_terms)
    )
    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    solve_time_ms = round((time.perf_counter() - started) * 1000.0, 2)
    items: list[PlannedTask] = []
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for task in scenario.tasks:
            items.append(PlannedTask(task_id=task.id, name=task.name, scheduled=False, reason="solver failed"))
        preserved, churn, stability_pct = evaluate_schedule_stability(previous_plan, items)
        return PlanResult(
            items=items,
            metrics=PlanMetrics(
                missed_deadlines=len(scenario.tasks),
                overload_slots=0,
                near_deadline_penalty=0,
                schedule_churn=churn,
                preserved_blocks=preserved,
                schedule_stability_pct=stability_pct,
                fragmentation_penalty=0,
                off_window_penalty=0,
                solve_time_ms=solve_time_ms,
                objective_value=float("inf"),
            ),
        )

    missed_total = 0
    cram_total = 0
    off_window_total = 0
    fragmentation_total = 0
    for task in scenario.tasks:
        if solver.Value(missed_vars[task.id]) == 1:
            missed_total += 1
            items.append(PlannedTask(task_id=task.id, name=task.name, scheduled=False, reason="not scheduled"))
            continue

        chosen_layout = None
        for idx, layout in enumerate(layouts_by_task[task.id]):
            if solver.Value(layout_vars[(task.id, idx)]) == 1:
                chosen_layout = layout
                break

        if chosen_layout is None:
            missed_total += 1
            items.append(PlannedTask(task_id=task.id, name=task.name, scheduled=False, reason="not scheduled"))
            continue

        cram_total += int(chosen_layout["cram_penalty"])
        off_window_total += int(chosen_layout["off_window_penalty"])
        fragmentation_total += int(chosen_layout["fragmentation_penalty"])
        chunks = [(start, start + duration) for start, duration in chosen_layout["chunks"]]
        items.append(
            PlannedTask(
                task_id=task.id,
                name=task.name,
                scheduled=True,
                start_slot=chunks[0][0],
                end_slot=chunks[-1][1],
                day=chunks[0][0] // SLOTS_PER_DAY,
                chunks=chunks,
            )
        )

    overload_total = sum(solver.Value(var) for var in daily_overload)
    items.sort(key=lambda item: (0 if item.start_slot is not None else 1, item.start_slot or 10_000, item.task_id))
    preserved, churn, stability_pct = evaluate_schedule_stability(previous_plan, items)
    return PlanResult(
        items=items,
        metrics=PlanMetrics(
            missed_deadlines=missed_total,
            overload_slots=overload_total,
            near_deadline_penalty=cram_total,
            schedule_churn=churn,
            preserved_blocks=preserved,
            schedule_stability_pct=stability_pct,
            fragmentation_penalty=fragmentation_total,
            off_window_penalty=off_window_total,
            solve_time_ms=solve_time_ms,
            objective_value=round(solver.ObjectiveValue(), 2),
        ),
    )


def _generate_layouts(
    task: Task,
    blocked: set[int],
    preferred: set[int],
    previous_signature: tuple[tuple[int, int], ...] | None = None,
    allow_split_override: bool | None = None,
) -> list[dict]:
    single_candidates = []
    split_candidates = []
    seen_signatures: set[tuple[tuple[int, int], ...]] = set()

    single_latest_start = max(0, task.deadline_slot - task.duration_slots + 1)
    for start in range(0, single_latest_start + 1):
        if _chunk_feasible(start, task.duration_slots, blocked, task.deadline_slot):
            layout = _make_layout([(start, task.duration_slots)], preferred, task.deadline_slot)
            signature = layout["signature"]
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                single_candidates.append(layout)

    if previous_signature:
        previous_layout = _layout_from_signature(previous_signature, blocked, preferred, task.deadline_slot)
        if previous_layout is not None and previous_layout["signature"] not in seen_signatures:
            seen_signatures.add(previous_layout["signature"])
            if len(previous_layout["chunks"]) == 1:
                single_candidates.append(previous_layout)
            else:
                split_candidates.append(previous_layout)

    layouts = _prune_layouts(single_candidates, previous_signature, MAX_SINGLE_LAYOUTS)

    allow_split = task.allow_split if allow_split_override is None else allow_split_override
    if not allow_split or task.duration_slots < (MIN_SPLIT_CHUNK_SLOTS * 2):
        return layouts

    first_duration = task.duration_slots // 2
    second_duration = task.duration_slots - first_duration
    split_signatures: set[tuple[tuple[int, int], ...]] = set()

    latest_first_start = max(0, task.deadline_slot - first_duration + 1)
    for first_start in range(0, latest_first_start + 1):
        if not _chunk_feasible(first_start, first_duration, blocked, task.deadline_slot):
            continue

        first_end = first_start + first_duration
        latest_second_start = min(task.deadline_slot - second_duration + 1, first_end + MAX_SPLIT_GAP_SLOTS)
        if latest_second_start < first_end:
            continue

        feasible_seconds = []
        for second_start in range(first_end, latest_second_start + 1):
            if _chunk_feasible(second_start, second_duration, blocked, task.deadline_slot):
                layout = _make_layout(
                    [(first_start, first_duration), (second_start, second_duration)],
                    preferred,
                    task.deadline_slot,
                )
                feasible_seconds.append(layout)

        if not feasible_seconds:
            continue

        feasible_seconds.sort(key=lambda layout: (layout["score"], layout["last_end"], layout["first_start"]))
        selected = [feasible_seconds[0]]
        if len(feasible_seconds) > 1:
            selected.append(feasible_seconds[-1])

        for layout in selected:
            signature = layout["signature"]
            if signature in seen_signatures or signature in split_signatures:
                continue
            split_signatures.add(signature)
            split_candidates.append(layout)

    pruned_split = _prune_layouts(split_candidates, previous_signature, MAX_SPLIT_LAYOUTS)
    layouts.extend(pruned_split)
    return _prune_layouts(layouts, previous_signature, MAX_TOTAL_LAYOUTS)


def _prune_layouts(
    layouts: list[dict],
    previous_signature: tuple[tuple[int, int], ...] | None,
    max_total: int,
) -> list[dict]:
    if len(layouts) <= max_total:
        return sorted(layouts, key=lambda layout: _layout_sort_key(layout, previous_signature))

    ordered = sorted(layouts, key=lambda layout: _layout_sort_key(layout, previous_signature))
    selected: list[dict] = []
    selected_signatures: set[tuple[tuple[int, int], ...]] = set()
    bucket_counts: Counter = Counter()

    must_keep = []
    must_keep.append(min(ordered, key=lambda layout: layout["first_start"]))
    must_keep.append(max(ordered, key=lambda layout: layout["last_end"]))
    if previous_signature is not None:
        matched = next((layout for layout in ordered if layout["signature"] == previous_signature), None)
        if matched is not None:
            must_keep.append(matched)

    for layout in must_keep:
        signature = layout["signature"]
        if signature in selected_signatures:
            continue
        selected.append(layout)
        selected_signatures.add(signature)
        bucket_counts[_layout_bucket(layout)] += 1

    for layout in ordered:
        if len(selected) >= max_total:
            break
        signature = layout["signature"]
        if signature in selected_signatures:
            continue
        bucket = _layout_bucket(layout)
        if bucket_counts[bucket] >= MAX_LAYOUTS_PER_BUCKET:
            continue
        selected.append(layout)
        selected_signatures.add(signature)
        bucket_counts[bucket] += 1

    if len(selected) < max_total:
        for layout in ordered:
            if len(selected) >= max_total:
                break
            signature = layout["signature"]
            if signature in selected_signatures:
                continue
            selected.append(layout)
            selected_signatures.add(signature)

    return sorted(selected, key=lambda layout: _layout_sort_key(layout, previous_signature))


def _layout_bucket(layout: dict) -> tuple[int, int]:
    return (layout["first_start"] // LAYOUT_BUCKET_SLOTS, len(layout["chunks"]))


def _layout_sort_key(layout: dict, previous_signature: tuple[tuple[int, int], ...] | None) -> tuple:
    previous_distance = 0
    if previous_signature:
        previous_distance = _signature_distance(layout["signature"], previous_signature)
    return (
        0 if previous_signature and layout["signature"] == previous_signature else 1,
        layout["score"],
        previous_distance,
        layout["last_end"],
        layout["first_start"],
    )


def _layout_from_signature(
    signature: tuple[tuple[int, int], ...],
    blocked: set[int],
    preferred: set[int],
    deadline_slot: int,
) -> dict | None:
    chunks = []
    for start, end in signature:
        duration = end - start
        if duration <= 0 or not _chunk_feasible(start, duration, blocked, deadline_slot):
            return None
        chunks.append((start, duration))
    return _make_layout(chunks, preferred, deadline_slot)


def _signature_distance(
    first: tuple[tuple[int, int], ...],
    second: tuple[tuple[int, int], ...],
) -> int:
    if not first and not second:
        return 0
    if len(first) != len(second):
        return 10_000 + abs(len(first) - len(second)) * 100
    return sum(abs(start_a - start_b) + abs(end_a - end_b) for (start_a, end_a), (start_b, end_b) in zip(first, second))


def _make_layout(chunks: list[tuple[int, int]], preferred: set[int], deadline_slot: int) -> dict:
    covered_slots = []
    day_loads: Counter = Counter()
    off_window_penalty = 0
    for start, duration in chunks:
        for slot in range(start, start + duration):
            covered_slots.append(slot)
            day_loads[slot // SLOTS_PER_DAY] += 1
            if slot not in preferred:
                off_window_penalty += 1

    first_start = chunks[0][0]
    last_end = chunks[-1][0] + chunks[-1][1]
    cram_penalty = 1 if deadline_slot - last_end <= 12 else 0
    fragmentation_penalty = max(0, len(chunks) - 1)
    gap_penalty = 0
    if len(chunks) > 1:
        for idx in range(len(chunks) - 1):
            current_end = chunks[idx][0] + chunks[idx][1]
            next_start = chunks[idx + 1][0]
            gap_penalty += max(0, next_start - current_end)

    score = (off_window_penalty * 5) + (cram_penalty * 20) + (fragmentation_penalty * 15) + gap_penalty
    return {
        "chunks": chunks,
        "covered_slots": tuple(covered_slots),
        "day_loads": dict(day_loads),
        "off_window_penalty": off_window_penalty,
        "cram_penalty": cram_penalty,
        "fragmentation_penalty": fragmentation_penalty,
        "signature": tuple((start, start + duration) for start, duration in chunks),
        "first_start": first_start,
        "last_end": last_end,
        "score": score,
    }


def _task_signature(item: PlannedTask) -> tuple[tuple[int, int], ...]:
    if item.chunks:
        return tuple((int(start), int(end)) for start, end in item.chunks)
    if item.start_slot is not None and item.end_slot is not None:
        return ((item.start_slot, item.end_slot),)
    return tuple()


def _chunk_feasible(start: int, duration: int, blocked: set[int], deadline_slot: int) -> bool:
    end = start + duration
    if end > TOTAL_SLOTS or end > (deadline_slot + 1):
        return False
    return not any(slot in blocked for slot in range(start, end))
