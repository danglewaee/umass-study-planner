from __future__ import annotations

from copy import deepcopy
from random import Random

from .mdp import Action, PlannerState, RewardBreakdown, SimTask, TaskKind, TransitionResult, UserProfile

BLOCKS_PER_DAY = 4
LAST_DAY_INDEX = 6


PROFILE_PRESETS: dict[str, UserProfile] = {
    "default": UserProfile("morning", 1.0, 0.3, 0.8, 1.0),
    "burnout_prone": UserProfile("morning", 1.5, 0.45, 0.9, 1.35),
    "disciplined": UserProfile("morning", 0.8, 0.15, 1.0, 0.85),
    "night_owl": UserProfile("evening", 1.1, 0.3, 0.75, 1.0),
}


def _task(
    task_id: str,
    title: str,
    kind: TaskKind,
    priority: int,
    difficulty: int,
    blocks: int,
    deadline_day: int,
    energy_match: str,
) -> SimTask:
    return SimTask(task_id, title, kind, priority, difficulty, blocks, blocks, deadline_day, energy_match)


SCENARIO_PRESETS: dict[str, list[SimTask]] = {
    "balanced_semester": [
        _task("t1", "Algorithms problem set", TaskKind.academics, 5, 5, 2, 2, "morning"),
        _task("t2", "Backend project milestone", TaskKind.academics, 5, 4, 3, 4, "morning"),
        _task("t3", "Recruiter follow-up", TaskKind.recruiting, 4, 2, 1, 1, "midday"),
        _task("t4", "Gym and recovery", TaskKind.health, 4, 1, 1, 3, "evening"),
        _task("t5", "Draft systems write-up", TaskKind.academics, 3, 3, 2, 5, "midday"),
    ],
    "exam_crunch": [
        _task("t1", "Operating systems exam prep", TaskKind.academics, 5, 5, 3, 1, "morning"),
        _task("t2", "Machine learning exam prep", TaskKind.academics, 5, 5, 3, 2, "morning"),
        _task("t3", "Algorithms practice set", TaskKind.academics, 4, 4, 2, 2, "midday"),
        _task("t4", "Take-home quiz", TaskKind.academics, 4, 3, 1, 0, "evening"),
        _task("t5", "Sleep reset walk", TaskKind.health, 3, 1, 1, 3, "evening"),
    ],
    "recruiting_sprint": [
        _task("t1", "OA preparation", TaskKind.recruiting, 5, 4, 2, 1, "morning"),
        _task("t2", "Behavioral story practice", TaskKind.recruiting, 4, 2, 2, 3, "midday"),
        _task("t3", "Resume tailoring", TaskKind.recruiting, 4, 2, 1, 0, "midday"),
        _task("t4", "Distributed systems assignment", TaskKind.academics, 5, 4, 2, 2, "morning"),
        _task("t5", "Workout", TaskKind.health, 3, 1, 1, 4, "evening"),
        _task("t6", "Networking follow-ups", TaskKind.recruiting, 3, 2, 1, 2, "midday"),
    ],
    "overload_recovery": [
        _task("t1", "Late lab report", TaskKind.academics, 5, 4, 2, 0, "morning"),
        _task("t2", "Missed homework catch-up", TaskKind.academics, 4, 4, 2, 1, "midday"),
        _task("t3", "Sleep recovery", TaskKind.health, 5, 1, 1, 1, "evening"),
        _task("t4", "Therapy journaling", TaskKind.personal, 3, 1, 1, 2, "evening"),
        _task("t5", "Project checkpoint", TaskKind.academics, 4, 3, 2, 4, "morning"),
    ],
}


class StudentPlannerEnv:
    def __init__(self, seed: int = 7, scenario: str = "balanced_semester", profile_name: str = "default") -> None:
        self.random = Random(seed)
        self.scenario = scenario
        self.profile_name = profile_name
        self.profile = deepcopy(PROFILE_PRESETS[profile_name])
        self.initial_tasks = deepcopy(SCENARIO_PRESETS[scenario])
        self.completed_task_ids: set[str] = set()
        self.deadline_penalized: set[tuple[str, int]] = set()
        self.state = self.reset()

    def reset(self, profile: UserProfile | None = None, scenario: str | None = None) -> PlannerState:
        if profile is not None:
            self.profile = deepcopy(profile)
        elif self.profile_name in PROFILE_PRESETS:
            self.profile = deepcopy(PROFILE_PRESETS[self.profile_name])
        if scenario is not None:
            self.scenario = scenario
            self.initial_tasks = deepcopy(SCENARIO_PRESETS[scenario])
        self.completed_task_ids = set()
        self.deadline_penalized = set()
        self.state = PlannerState(tasks=deepcopy(self.initial_tasks))
        return deepcopy(self.state)

    def legal_actions(self) -> list[Action]:
        actions = [Action(type="recovery"), Action(type="buffer")]
        pending_tasks = [task for task in self.state.tasks if task.blocks_remaining > 0]
        for task in pending_tasks[:5]:
            actions.append(Action(type="schedule_task", task_id=task.id, duration_blocks=1))
            if task.blocks_remaining > 1:
                actions.append(Action(type="defer_task", task_id=task.id, duration_blocks=1))
        return actions

    def current_window(self) -> str:
        if self.state.block_index == 0:
            return "morning"
        if self.state.block_index in (1, 2):
            return "midday"
        return "evening"

    def step(self, action: Action) -> TransitionResult:
        state = deepcopy(self.state)
        reward = RewardBreakdown()
        info: dict[str, float | int | str] = {"action": action.type, "scenario": self.scenario, "profile": self.profile_name}
        hard_work_this_step = False
        scheduled_success = False

        if action.type == "schedule_task" and action.task_id:
            task = next((item for item in state.tasks if item.id == action.task_id), None)
            if task and task.blocks_remaining > 0:
                success_probability = self._success_probability(task, state)
                info["success_probability"] = round(success_probability, 3)
                if self.random.random() <= success_probability:
                    task.blocks_remaining -= 1
                    scheduled_success = True
                    reward.goal_progress += self._completion_bonus(task, state)
                    reward.consistency_gain += 0.45 * self.profile.consistency_preference
                    if self.current_window() != task.energy_match:
                        reward.fragility_penalty += 0.25
                    if task.difficulty >= 4:
                        hard_work_this_step = True
                    if task.blocks_remaining == 0 and task.id not in self.completed_task_ids:
                        self.completed_task_ids.add(task.id)
                        state.completed_priority_points += task.priority
                        reward.goal_progress += 1.25
                else:
                    state.stress_level += 0.45 * self.profile.overload_sensitivity
                    reward.fragility_penalty += 0.55
                    reward.consistency_gain -= 0.08
            else:
                reward.fragility_penalty += 1.0

        elif action.type == "recovery":
            state.stress_level = max(0.0, state.stress_level - 1.35 * self.profile.recovery_need)
            state.sleep_debt_hours = max(0.0, state.sleep_debt_hours - 0.45)
            reward.consistency_gain += 0.3

        elif action.type == "buffer":
            reward.consistency_gain += 0.18

        elif action.type == "defer_task" and action.task_id:
            reward.fragility_penalty += 0.45
            state.consistency_score = max(0.0, state.consistency_score - 0.05)
            state.stress_level += 0.15

        self._apply_step_effects(state, reward, hard_work_this_step, scheduled_success)
        self._advance_time(state)
        self._apply_deadline_penalties(state, reward)

        done = state.day_index > LAST_DAY_INDEX or all(task.blocks_remaining == 0 for task in state.tasks)
        state.consistency_score = max(0.0, min(1.0, state.consistency_score))
        self.state = state
        return TransitionResult(next_state=deepcopy(state), reward=round(reward.total, 3), done=done, info=info)

    def _success_probability(self, task: SimTask, state: PlannerState) -> float:
        probability = 0.9
        probability -= 0.06 * (task.difficulty - 1)
        probability -= 0.04 * self.profile.procrastination_tendency * max(0, task.deadline_day - state.day_index)
        probability -= 0.05 * state.stress_level
        probability -= 0.04 * state.sleep_debt_hours
        if self.current_window() == task.energy_match:
            probability += 0.08
        if self.current_window() == self.profile.strongest_window:
            probability += 0.06
        if task.kind == TaskKind.health:
            probability += 0.04
        return max(0.15, min(0.97, probability))

    def _completion_bonus(self, task: SimTask, state: PlannerState) -> float:
        urgency = max(0, 4 - (task.deadline_day - state.day_index))
        energy_bonus = 0.55 if self.current_window() == self.profile.strongest_window else 0.1
        difficulty_bonus = task.difficulty * 0.18
        return 1.0 + urgency * 0.45 + energy_bonus + difficulty_bonus

    def _apply_step_effects(
        self,
        state: PlannerState,
        reward: RewardBreakdown,
        hard_work_this_step: bool,
        scheduled_success: bool,
    ) -> None:
        if hard_work_this_step and self.current_window() == "evening":
            state.sleep_debt_hours += 0.55
            reward.sleep_penalty += 0.45
        if hard_work_this_step and state.block_index >= 2:
            state.stress_level += 0.7 * self.profile.overload_sensitivity
        if scheduled_success and self.current_window() == self.profile.strongest_window:
            state.consistency_score += 0.03
        if state.stress_level >= 3.0:
            state.overload_events += 1
            reward.overload_penalty += 0.85 * self.profile.overload_sensitivity
            state.consistency_score -= 0.07
        if state.sleep_debt_hours >= 2.5:
            reward.sleep_penalty += 0.5
            state.consistency_score -= 0.05
        if reward.consistency_gain > 0:
            state.consistency_score += 0.02

    def _advance_time(self, state: PlannerState) -> None:
        state.block_index += 1
        if state.block_index >= BLOCKS_PER_DAY:
            state.block_index = 0
            state.day_index += 1
            state.stress_level = max(0.0, state.stress_level - 0.35)
            state.sleep_debt_hours = max(0.0, state.sleep_debt_hours - 0.1)

    def _apply_deadline_penalties(self, state: PlannerState, reward: RewardBreakdown) -> None:
        for task in state.tasks:
            penalty_key = (task.id, state.day_index)
            if task.blocks_remaining > 0 and state.day_index > task.deadline_day and penalty_key not in self.deadline_penalized:
                self.deadline_penalized.add(penalty_key)
                state.missed_deadlines += 1
                reward.deadline_penalty += 1.7 + task.priority * 0.3
                state.consistency_score -= 0.05


def rollout_episode(env: StudentPlannerEnv, policy) -> dict[str, float]:
    state = env.reset()
    total_reward = 0.0
    steps = 0
    while True:
        action = policy(env, state)
        transition = env.step(action)
        total_reward += transition.reward
        state = transition.next_state
        steps += 1
        if transition.done or steps > 128:
            break
    completed_tasks = sum(1 for task in state.tasks if task.blocks_remaining == 0)
    remaining_blocks = sum(task.blocks_remaining for task in state.tasks)
    return {
        "total_reward": round(total_reward, 3),
        "completed_priority_points": state.completed_priority_points,
        "completed_tasks": completed_tasks,
        "remaining_blocks": remaining_blocks,
        "missed_deadlines": state.missed_deadlines,
        "overload_events": state.overload_events,
        "consistency_score": round(state.consistency_score, 3),
        "stress_level": round(state.stress_level, 3),
        "sleep_debt_hours": round(state.sleep_debt_hours, 3),
    }
