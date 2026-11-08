"""Resumable runner for control arms. Frozen source in ../src is imported unchanged.

Phases
  smoke      one short run per control policy
  calibrate  pilot seeds 104900+ (never used for inference); tunes the admission probability
             of matched_random to the mean robot coverage of staff_rollout in the main study
  main       control arms on the main study seeds 103000-103019, paired with the existing 1800 runs
"""
import argparse, hashlib, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from control_simulation import ControlSimulation

PILOT_SEEDS = list(range(104900, 104908))


def job(args):
    case, policy, seed, warmup, days, output = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    start = perf_counter()
    result = ControlSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup,
                  measurement_days=days, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    path = Path(output) / f'{case["name"]}__{policy}__{seed}.json'
    path.write_text(json.dumps(result, indent=2))
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            j = futures[f]
            out.append((j, f.result()))
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    return out


def mean_coverage(results):
    table = {}
    for (case, policy, seed, *_), (coverage, _) in results:
        table.setdefault(case["name"], []).append(coverage)
    return {k: sum(v) / len(v) for k, v in table.items()}


def calibrate(workers):
    targets = json.loads((ROOT / "coverage_targets.json").read_text())
    out = ROOT / "results" / "calibration"
    out.mkdir(parents=True, exist_ok=True)
    cases = rw.cases()
    log = {"seeds": PILOT_SEEDS, "warmup_days": 2, "measurement_days": 4, "rounds": []}
    jobs = [(dict(c, admit_probability=1.0), "greedy_robot", s, 2, 4, str(out)) for c in cases for s in PILOT_SEEDS]
    print("greedy robot", len(jobs), flush=True)
    cmax = mean_coverage(run_all(jobs, workers))
    p = {name: min(1.0, targets[name] / cmax[name]) if cmax[name] > 0 else 1.0 for name in targets}
    log["rounds"].append({"policy": "greedy_robot", "coverage": cmax, "next_p": dict(p)})
    for rnd in (1, 2):
        jobs = [(dict(c, admit_probability=p[c["name"]]), "matched_random", s, 2, 4, str(out))
                for c in cases for s in PILOT_SEEDS]
        print("matched_random round", rnd, len(jobs), flush=True)
        cov = mean_coverage(run_all(jobs, workers))
        used = dict(p)
        p = {n: min(1.0, p[n] * targets[n] / cov[n]) if cov[n] > 0 else min(1.0, p[n] * 2) for n in targets}
        log["rounds"].append({"policy": "matched_random", "round": rnd, "p": used, "coverage": cov, "next_p": dict(p)})
    log["targets"] = targets
    log["final_p"] = p
    (ROOT / "calibration.json").write_text(json.dumps(log, indent=2))
    print("calibration done", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["smoke", "calibrate", "main", "main2"], required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.phase == "calibrate":
        return calibrate(args.workers)
    cases = rw.cases()
    if args.phase == "smoke":
        out = ROOT / "results" / "smoke"
        out.mkdir(parents=True, exist_ok=True)
        jobs = [(dict(c, admit_probability=.5), pol, 103000, 1, 1, str(out))
                for c in cases if c["background_fraction"] == .4 and c["information_lag"] == 0
                for pol in ("matched_random", "idle_pair_rule", "greedy_robot")]
        for j, r in run_all(jobs, args.workers):
            print(j[0]["name"], j[1], r)
        return
    p = json.loads((ROOT / "calibration.json").read_text())["final_p"]
    policies = ["matched_random", "idle_pair_rule"]
    tag = "controls"
    if args.phase == "main2":
        policies, tag = ["idle_surplus_rule"], "controls2"
    seeds = list(range(103000, 103020))
    out = ROOT / "results" / tag
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
              for d in ("src", "ctl") for f in (ROOT / d).rglob("*.py")}
    design = dict(phase=tag, seeds=seeds, warmup_days=7, measurement_days=7, policies=policies,
                  cases=[dict(c, admit_probability=p[c["name"]]) for c in cases], code_hashes=hashes,
                  note="Arms added to the frozen main design; paired with results/main on identical seeds.")
    path = ROOT / f"design_{tag}.json"
    if path.exists():
        old = json.loads(path.read_text())
        if {k: v for k, v in old.items() if k != "code_hashes"} != {k: v for k, v in design.items() if k != "code_hashes"}:
            raise RuntimeError("Design or code changed: refusing to mix runs.")
    else:
        path.write_text(json.dumps(design, indent=2))
    jobs = [(c, pol, s, 7, 7, str(out)) for s in seeds for c in design["cases"] for pol in policies
            if not (out / f'{c["name"]}__{pol}__{s}.json').exists()]
    print("main controls pending", len(jobs), flush=True)
    run_all(jobs, args.workers)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
