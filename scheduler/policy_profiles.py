from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerPolicy:
    name: str
    weights: dict[str, int]
    use_previous_layout: bool = True
    allow_split_override: bool | None = None
    description: str = ""


BASE_WEIGHTS = {
    "missed": 1000,
    "overload": 200,
    "cram": 80,
    "churn": 60,
    "off_window": 25,
    "fragmentation": 15,
}

PLANNING_POLICY = PlannerPolicy(
    name="planning_default",
    weights=BASE_WEIGHTS,
    use_previous_layout=False,
    allow_split_override=True,
    description="Balanced weekly planning profile.",
)

REPAIR_POLICIES: dict[str, PlannerPolicy] = {
    "stability_aware": PlannerPolicy(
        name="stability_aware",
        weights=BASE_WEIGHTS,
        use_previous_layout=True,
        allow_split_override=True,
        description="Default repair profile with moderate churn penalties.",
    ),
    "deadline_rescue": PlannerPolicy(
        name="deadline_rescue",
        weights={
            "missed": 1350,
            "overload": 150,
            "cram": 140,
            "churn": 18,
            "off_window": 10,
            "fragmentation": 6,
        },
        use_previous_layout=True,
        allow_split_override=True,
        description="Aggressively recovers tight deadlines, tolerating more movement.",
    ),
    "load_balance": PlannerPolicy(
        name="load_balance",
        weights={
            "missed": 950,
            "overload": 340,
            "cram": 90,
            "churn": 35,
            "off_window": 18,
            "fragmentation": 18,
        },
        use_previous_layout=True,
        allow_split_override=True,
        description="Spreads work to avoid overload spikes after disruptions.",
    ),
    "focus_windows": PlannerPolicy(
        name="focus_windows",
        weights={
            "missed": 975,
            "overload": 180,
            "cram": 90,
            "churn": 45,
            "off_window": 65,
            "fragmentation": 28,
        },
        use_previous_layout=True,
        allow_split_override=False,
        description="Preserves preferred windows and minimizes fragmented schedules.",
    ),
    "full_replan": PlannerPolicy(
        name="full_replan",
        weights={
            "missed": 1300,
            "overload": 180,
            "cram": 120,
            "churn": 0,
            "off_window": 15,
            "fragmentation": 8,
        },
        use_previous_layout=False,
        allow_split_override=True,
        description="Drops stability constraints and recomputes the week globally.",
    ),
}

DEFAULT_REPAIR_POLICY = "stability_aware"


def get_planning_policy() -> PlannerPolicy:
    return PLANNING_POLICY


def get_repair_policy(name: str | None) -> PlannerPolicy:
    if not name:
        return REPAIR_POLICIES[DEFAULT_REPAIR_POLICY]
    return REPAIR_POLICIES.get(name, REPAIR_POLICIES[DEFAULT_REPAIR_POLICY])


def list_repair_policies() -> list[str]:
    return list(REPAIR_POLICIES.keys())
