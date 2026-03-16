# Benchmarking

## Setup
- Planner: CP-SAT weekly scheduler with bounded task splitting and stability-aware replanning
- RL layer: tabular policy selector over repair strategies (`stability_aware`, `deadline_rescue`, `load_balance`, `full_replan`)
- Baselines:
  - earliest-deadline-first heuristic
  - weighted heuristic
  - fixed repair strategies for replanning
- Commands:
  - `python benchmarks/compare.py`
  - `python benchmarks/compare_rl.py`
- Benchmark scope: local synthetic simulation, not production user traffic

## Planning benchmark
Across 50 simulated scenarios:
- planner: `0.52` missed deadlines, `1.16` overload slots, `7.22` off-window penalty, `455.66ms` average solve time
- EDF baseline: `1.40` missed deadlines, `38.16` off-window penalty
- weighted heuristic: `0.02` missed deadlines, but `12.44` overload slots and `38.36` off-window penalty

Takeaway:
- the planner is materially better than EDF on deadline completion
- it preserves schedule quality much better than the weighted heuristic by avoiding overload and off-window drift

## Replanning benchmark
Across 50 disrupted scenarios:
- planner: `0.56` missed deadlines, `91.97%` schedule stability, `277.12ms` average replan time
- EDF baseline: `1.50` missed deadlines, `81.70%` stability
- weighted heuristic: `0.02` missed deadlines, but `12.82` overload slots

Takeaway:
- the replanner preserves most of the existing week while keeping deadline misses much lower than EDF
- the main tradeoff remains between deadline rescue and overload control

## Disruption coverage
The benchmark now rotates through four disruption types:
- `urgent_commitment`: sudden commitment plus a new urgent task
- `missed_session`: a preferred study block becomes unavailable
- `deadline_pull_in`: an existing task deadline is moved earlier
- `low_energy_day`: recovery blocks remove capacity and add a lightweight admin task

## Failure-mode snapshot
Selected planner results by disruption type:
- `deadline_pull_in`: `0.42` missed deadlines, `97.06%` stability, `248.93ms` replan time
- `missed_session`: `0.54` missed deadlines, `94.00%` stability, `236.31ms` replan time
- `urgent_commitment`: `0.62` missed deadlines, `90.49%` stability, `323.72ms` replan time
- `low_energy_day`: `0.67` missed deadlines, `86.26%` stability, `299.04ms` replan time

Takeaway:
- `low_energy_day` is currently the hardest disruption class
- `deadline_pull_in` is the cleanest case for preserving the existing plan while repairing tight deadlines

## RL-assisted replanning
Across 50 disrupted scenarios:
- learned policy: reward `95.63`, `0.04` missed deadlines, `4.72` overload slots, `86.84%` stability, `197.74ms` average solve time
- fixed `deadline_rescue`: reward `95.48`, `0.00` missed deadlines, `4.96` overload slots, `85.70%` stability, `196.18ms`
- fixed `stability_aware`: reward `81.47`, `0.52` missed deadlines, `93.70%` stability, `199.44ms`

Takeaway:
- the learned policy improves the deadline/stability tradeoff over any single fixed strategy
- the agent mostly switches between `deadline_rescue` and `stability_aware`, with occasional `load_balance` use under heavier congestion

## Remaining weakness
- `deadline_pull_in` remains the hardest case for the RL selector; it often needs aggressive rescue behavior and can still accumulate overload
