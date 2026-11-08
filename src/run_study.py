"""Frozen paired experiments, resumable from one JSON file per completed run."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path
from time import perf_counter
import sys

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(HERE))
from hospital_sim.routing import HospitalRouter, RouteEstimate
from hospital_sim.simulation import HospitalSimulation
from staff_simulation import StaffSimulation

PARAMETERS = None
ROUTES = None
POLICIES = ["human_only", "adaptive_hybrid", "travel_aware_hybrid", "deadline_hybrid",
            "own_completion", "no_support_forecast", "staff_rollout"]

def cached_route(self, origin, destination):
    return ROUTES[(str(origin), str(destination))]

def initialize():
    global PARAMETERS, ROUTES
    PARAMETERS = json.loads((STUDY / "parameters.json").read_text())
    ROUTES = {(o, d): RouteEstimate(distance, rides, floors)
              for o, d, distance, rides, floors in json.loads((STUDY / "routes.json").read_text())}
    HospitalRouter.estimate = cached_route

def scenarios():
    result = []
    for staffing, mix, deadline in product(["moderate", "high"], ["balanced", "source"], [25, 45]):
        result.append(dict(name=f"{staffing}_{mix}_d{deadline}", group="core", staffing=staffing,
                           mix=mix, deadline=deadline, elevators=4, fleet=2, support=1.0,
                           demand=1.0, contention=True, queue_limit=32))
    center = next(x for x in result if x["name"] == "moderate_balanced_d25")
    for name, override in [
        ("elevators2", dict(elevators=2)), ("elevators8", dict(elevators=8)),
        ("no_elevator_queue", dict(contention=False)), ("fleet6", dict(fleet=6)),
        ("support_half", dict(support=0.5)), ("support_double", dict(support=2.0)),
        ("demand150", dict(demand=1.5)), ("low_staff", dict(staffing="low")),
        ("queue64", dict(queue_limit=64)), ("passengers", dict(passengers=12.0)),
    ]:
        result.append(dict(center, **dict(override, name=name, group="sensitivity")))
    return result

def configure(case, policy, warmup, days):
    config = json.loads((STUDY / "base_config.json").read_text())
    config["model"].update(warmup_days=warmup, simulation_days=days)
    roster = {"moderate": (8, 30, 24), "high": (15, 60, 50), "low": (4, 15, 12)}[case["staffing"]]
    config["hospital"]["human_staffing"] = [
        dict(name=name, start_hour=start, end_hour=end, count=count)
        for name, start, end, count in zip(["night", "day", "evening"], [22, 6, 14], [6, 14, 22], roster)]
    config["hospital"].update(elevator_bank_capacity=case["elevators"],
                               explicit_elevator_contention=case["contention"],
                               passenger_elevator_arrivals_per_hour=case.get("passengers", 0.0))
    config["robots"].update(fleet_size=0 if policy == "human_only" else case["fleet"],
                             reliability=0.98, support_multiplier=case["support"])
    config["tasks"]["specimen"]["deadline_minutes"] = case["deadline"]
    config["scenario"] = dict(policy=policy, demand_multiplier=case["demand"])
    config["forecast"] = dict(queue_limit=case["queue_limit"])
    return config

def run_job(job):
    case, policy, seed, warmup, days, output = job
    config = configure(case, policy, warmup, days)
    parameters = dict(PARAMETERS)
    if case["mix"] == "balanced":
        parameters["task_mix"] = dict(specimen=.4, medication=.3, supply=.2, instrument=.1)
    start = perf_counter()
    sim = StaffSimulation(config, parameters, seed=seed)
    result = sim.run()
    result.update(case=case["name"], group=case["group"], policy=policy,
                  elapsed_seconds=perf_counter() - start, warmup_days=warmup, measurement_days=days,
                  scenario=case)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["urgent_created"] == result["urgent_completed"] + result["urgent_incomplete"]
    assert result["battery_infeasible_missions"] == 0
    assert 0 <= result["human_utilization"] <= 1
    assert result["robot_completed"] + result["human_completed"] == result["completed"]
    path = Path(output) / f"{case['name']}__{policy}__{seed}.json"
    path.write_text(json.dumps(result, indent=2))
    return case["name"], policy, seed, result["elapsed_seconds"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["pilot", "main", "long"], default="pilot")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    phase = args.phase
    reps, warmup, days, seed_base = {"pilot": (2, 1, 2, 91000),
                                    "main": (20, 7, 7, 92000),
                                    "long": (20, 7, 30, 93000)}[phase]
    cases = scenarios()
    if phase == "pilot":
        cases = [c for c in cases if c["name"] in {"moderate_balanced_d25", "elevators2"}]
    elif phase == "long":
        cases = [c for c in cases if c["name"] in {"moderate_balanced_d25", "moderate_source_d25"}]
    output = STUDY / "results" / phase
    output.mkdir(parents=True, exist_ok=True)
    design = dict(phase=phase, replications=reps, warmup_days=warmup, days=days,
                  seeds=list(range(seed_base, seed_base+reps)), cases=cases, policies=POLICIES,
                  frozen_at=datetime.now(timezone.utc).isoformat())
    design_path = STUDY / f"design_{phase}.json"
    if not design_path.exists():
        design_path.write_text(json.dumps(design, indent=2))
    jobs = [(case, policy, seed_base+r, warmup, days, str(output))
            for r in range(reps) for case in cases for policy in POLICIES
            if not (output / f"{case['name']}__{policy}__{seed_base+r}.json").exists()]
    if args.limit:
        jobs = jobs[:args.limit]
    print(f"{phase}: {len(jobs)} pending runs, {args.workers} processes", flush=True)
    start = perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(run_job, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            case, policy, seed, duration = future.result()
            if i <= 14 or i % 20 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} {case} {policy} {seed}, run {duration:.2f}s, elapsed {perf_counter()-start:.1f}s", flush=True)
    hashes = {str(p.relative_to(STUDY)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in HERE.rglob("*.py")}
    (STUDY / f"code_hashes_{phase}.json").write_text(json.dumps(hashes, indent=2))

if __name__ == "__main__":
    main()
