from __future__ import annotations

from collections import defaultdict
from statistics import mean

from baselines import solve_edf, solve_weighted
from scheduler import evaluate_schedule_stability, replan_scenario, solve_scenario
from simulation.disruptions import apply_disruption, disruption_type_for_index, list_disruption_types
from simulation.scenario_gen import generate_scenario


def run_simulation(count: int, seed: int) -> dict:
    planner_metrics = []
    edf_metrics = []
    weighted_metrics = []
    planner_replan_metrics = []
    edf_replan_metrics = []
    weighted_replan_metrics = []
    planner_replan_by_type = defaultdict(list)
    edf_replan_by_type = defaultdict(list)
    weighted_replan_by_type = defaultdict(list)

    for idx in range(count):
        scenario = generate_scenario(seed + idx)
        planner = solve_scenario(scenario)
        edf = solve_edf(scenario)
        weighted = solve_weighted(scenario)
        planner_metrics.append(_extract(planner))
        edf_metrics.append(_extract(edf))
        weighted_metrics.append(_extract(weighted))

        disruption_type = disruption_type_for_index(idx)
        disrupted, disruption_type = apply_disruption(
            scenario,
            seed + 10_000 + idx,
            disruption_type=disruption_type,
            return_type=True,
        )
        planner_replan = replan_scenario(disrupted, planner)
        edf_replan = solve_edf(disrupted)
        weighted_replan = solve_weighted(disrupted)
        planner_row = _extract_replan(planner_replan, planner)
        edf_row = _extract_replan(edf_replan, edf)
        weighted_row = _extract_replan(weighted_replan, weighted)
        planner_replan_metrics.append(planner_row)
        edf_replan_metrics.append(edf_row)
        weighted_replan_metrics.append(weighted_row)
        planner_replan_by_type[disruption_type].append(planner_row)
        edf_replan_by_type[disruption_type].append(edf_row)
        weighted_replan_by_type[disruption_type].append(weighted_row)

    return {
        "planner": _aggregate(planner_metrics),
        "baselines": {
            "edf": _aggregate(edf_metrics),
            "weighted": _aggregate(weighted_metrics),
        },
        "replan": {
            "planner": _aggregate(planner_replan_metrics),
            "baselines": {
                "edf": _aggregate(edf_replan_metrics),
                "weighted": _aggregate(weighted_replan_metrics),
            },
        },
        "replan_by_disruption": {
            disruption_type: {
                "planner": _aggregate(planner_replan_by_type[disruption_type]),
                "baselines": {
                    "edf": _aggregate(edf_replan_by_type[disruption_type]),
                    "weighted": _aggregate(weighted_replan_by_type[disruption_type]),
                },
            }
            for disruption_type in list_disruption_types()
        },
    }


def _extract(result) -> dict:
    return {
        "missed_deadlines": result.metrics.missed_deadlines,
        "overload_slots": result.metrics.overload_slots,
        "off_window_penalty": result.metrics.off_window_penalty,
        "solve_time_ms": result.metrics.solve_time_ms,
        "objective_value": result.metrics.objective_value,
    }


def _extract_replan(result, previous_plan) -> dict:
    preserved, churn, stability_pct = evaluate_schedule_stability(previous_plan, result.items)
    return {
        "missed_deadlines": result.metrics.missed_deadlines,
        "overload_slots": result.metrics.overload_slots,
        "schedule_churn": churn,
        "preserved_blocks": preserved,
        "schedule_stability_pct": stability_pct,
        "solve_time_ms": result.metrics.solve_time_ms,
        "objective_value": result.metrics.objective_value,
    }


def _aggregate(rows: list[dict]) -> dict:
    return {
        key: round(mean(row[key] for row in rows), 2)
        for key in rows[0].keys()
    }
