from __future__ import annotations

from fastapi import FastAPI

from api.schemas import (
    PlanResult,
    RLEvaluationRequest,
    RLReplanResponse,
    RLTrainRequest,
    RLTrainResponse,
    ReplanRequest,
    Scenario,
    SimulationRequest,
)
from rl import TrainedRepairAgent, evaluate_repair_agent, replan_with_agent, train_repair_agent
from scheduler import replan_scenario, solve_scenario
from simulation.runner import run_simulation
from simulation.scenario_gen import generate_scenario

app = FastAPI(title="Adaptive Study Planning Engine", version="0.1.0")
trained_agent: TrainedRepairAgent | None = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "adaptive-study-planning"}


@app.get("/sample-scenario", response_model=Scenario)
def sample_scenario():
    return generate_scenario(7)


@app.post("/plan", response_model=PlanResult)
def plan(scenario: Scenario):
    return solve_scenario(scenario)


@app.post("/replan", response_model=PlanResult)
def replan(request: ReplanRequest):
    return replan_scenario(request.scenario, request.previous_plan)


@app.post("/train-rl", response_model=RLTrainResponse)
def train_rl(request: RLTrainRequest):
    global trained_agent
    trained_agent = train_repair_agent(
        episodes=request.episodes,
        seed=request.seed,
        alpha=request.alpha,
        epsilon=request.epsilon,
    )
    return RLTrainResponse(**trained_agent.summary())


@app.post("/replan-rl", response_model=RLReplanResponse)
def replan_rl(request: ReplanRequest):
    global trained_agent
    if trained_agent is None:
        trained_agent = train_repair_agent()
    action, state, result = replan_with_agent(request.scenario, request.previous_plan, trained_agent)
    return RLReplanResponse(chosen_action=action, encoded_state=state, result=result)


@app.post("/simulate-rl")
def simulate_rl(request: RLEvaluationRequest):
    agent = train_repair_agent(episodes=request.training_episodes, seed=request.seed)
    return evaluate_repair_agent(agent, count=request.evaluation_scenarios, seed=request.seed + 1000)


@app.post("/simulate")
def simulate(request: SimulationRequest):
    return run_simulation(count=request.scenarios, seed=request.seed)
