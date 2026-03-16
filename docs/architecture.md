# Architecture

## Core flow
Scenario -> candidate generation -> bounded layout enumeration -> CP-SAT solve -> weekly plan -> disruption injection -> stability-aware replan -> metrics

## Components
- `api/main.py`: FastAPI endpoints for planning, replanning, and simulation
- `api/schemas.py`: shared scenario and result schemas
- `scheduler/planner.py`: CP-SAT planner, bounded split-task layouts, and replan logic
- `scheduler/stability.py`: preserved-block and churn metrics
- `scheduler/utils.py`: blocked-slot and preference helpers
- `baselines/`: greedy baselines for comparison
- `simulation/scenario_gen.py`: synthetic week generation
- `simulation/disruptions.py`: disruption injection for replanning
- `simulation/runner.py`: aggregate evaluation
- `benchmarks/compare.py`: command-line benchmark runner

## Current scope
- tasks may use either one block or a bounded two-chunk layout
- 30-minute slots
- stability-aware replanning via layout preservation
- weighted objective over deadlines, overload, cram, churn, fragmentation, and off-window penalties

## Detailed pipeline
See `docs/pipeline.md` for the full end-to-end planning, disruption, RL, evaluation, and API pipeline.
