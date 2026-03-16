# BalanceOS ML Layer

This folder contains the RL-ready planning environment for BalanceOS.

## Files
- mdp.py: state, action, reward, and transition models
- simulator.py: student workload simulation environment with scenario and profile presets
- baselines.py: heuristic scheduling policies
- evaluate.py: benchmark baseline policies across scenarios and user profiles
- train_rl.py: placeholder RL training entrypoint with a smoke-test random policy
- repair_selector.py: simulation-trained strategy selector for backend replanning
- evaluate_repair_selector.py: quick benchmark for the repair selector

## Current scenarios
- balanced_semester
- exam_crunch
- recruiting_sprint
- overload_recovery

## Current user profiles
- default
- burnout_prone
- disciplined
- night_owl

## Design
The planner is framed as a sequential decision-making problem over a week.
At each step, an agent can:
- schedule a task block
- insert recovery
- leave buffer
- defer a task

The reward balances:
- progress toward deadlines
- consistency
- sleep and recovery preservation
- overload risk
- schedule fragility

The simulator now includes stochastic task success, profile-specific fatigue sensitivity, deadline pressure, and multiple workload regimes so heuristic and learned policies can be compared meaningfully.

## Why this exists
The product layer can ship with heuristics first. The ML layer lets us compare rule-based planning against learned policies in a simulator before using real user data.

The repair selector is the bridge between the ML layer and the product planner:
- the backend planner exposes multiple repair strategies
- the selector learns which strategy to use after a schedule disruption
- the API can then call RL-assisted replanning without replacing the deterministic planner

## Quick commands
- Syntax check: python -m compileall ml
- Baseline comparison: python -m ml.evaluate
- RL smoke test: python -m ml.train_rl
- Repair selector evaluation: python -m ml.evaluate_repair_selector
