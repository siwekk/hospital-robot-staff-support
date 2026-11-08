"""Equal staff budget variant (496 staffed hours per day split between local workers and a smaller mobile roster).

Phases
  test       one short run per policy, checks that nothing breaks
  main       human_only (reduced roster), staff_rollout, no_support_forecast on seeds 103000-103011
  calibrate  pilot seeds 104900-104907; matched_random probability per condition, target = staff_rollout coverage
             of phase main
  random     matched_random on the main seeds
Every phase writes a frozen design file and refuses to mix runs.
"""
import argparse, hashlib, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from budget_simulation import BudgetSimulation

PILOT_SEEDS = list(range(104900, 104908))
SEEDS = list(range(103000, 103012))
NODES = json.loads((ROOT / "budget_nodes.json").read_text())
MAIN_POLICIES = ["human_only", "staff_rollout", "no_support_forecast"]


def cases():
    out = []
    for mode, k, b, lag in product(["local", "mixed"], [3, 6], [0.4, 0.8], [0, 10]):
        out.append(dict(name=f"{mode}_k{k}_b{int(100 * b)}_lag{lag}", mode=mode, k=k,
                        background_fraction=b, information_lag=lag))
    return out


def staffing(cnt):
    return [dict(name=n, start_hour=s, end_hour=e, count=c)
            for n, s, e, c in zip(["night", "day", "evening"], [22, 6, 14], [6, 14, 22], cnt)]


def job(args):
    case, policy, seed, warmup, days, output = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    d = NODES[f"k{case['k']}"]
    cfg = rw.config(case, policy, warmup, days)
    cfg["hospital"]["human_staffing"] = staffing(d["roster"])
    cfg["workflow"]["nodes"] = d["local_set"] if case["mode"] == "local" else d["mixed_set"]
    start = perf_counter()
    result = BudgetSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  roster=d["roster"], local_nodes=cfg["workflow"]["nodes"], elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    path = Path(output) / f'{case["name"]}__{policy}__{seed}.json'
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(result, indent=2)); tmp.replace(path)
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    return out


def freeze(name, design):
    path = ROOT / f"design_budget_{name}.json"
    design["code_hashes"] = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                             for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))}
    body = json.loads(json.dumps({k: v for k, v in design.items() if k != "code_hashes"}))
    if path.exists():
        old = {k: v for k, v in json.loads(path.read_text()).items() if k != "code_hashes"}
        if old != body:
            raise RuntimeError("Design changed: refusing to mix runs.")
    else:
        path.write_text(json.dumps(design, indent=2))


def mean_cov(results):
    t = {}
    for (case, *_), (cov, _) in results:
        t.setdefault(case["name"], []).append(cov)
    return {k: sum(v) / len(v) for k, v in t.items()}


def targets():
    import numpy as np
    tab = {}
    for f in sorted((ROOT / "results" / "budget_main").glob("*__staff_rollout__*.json")):
        r = json.loads(f.read_text()); tab.setdefault(r["case"], []).append(r["robot_coverage"])
    return {k: float(np.mean(v)) for k, v in tab.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["test", "main", "calibrate", "random"])
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    cs = cases()
    if a.phase == "test":
        out = ROOT / "results" / "budget_test"; out.mkdir(parents=True, exist_ok=True)
        jobs = [(dict(c, admit_probability=.5), pol, 103000, 1, 1, str(out))
                for c in cs if c["background_fraction"] == .4 and c["information_lag"] == 0 and c["k"] == 6
                for pol in MAIN_POLICIES + ["matched_random", "greedy_robot"]]
        for j, r in run_all(jobs, a.workers):
            print(j[0]["name"], j[1], r)
        return
    if a.phase == "main":
        out = ROOT / "results" / "budget_main"; out.mkdir(parents=True, exist_ok=True)
        freeze("main", dict(phase="main", seeds=SEEDS, warmup_days=7, measurement_days=7, policies=MAIN_POLICIES,
                            cases=cs, nodes=NODES))
        jobs = [(c, pol, s, 7, 7, str(out)) for s in SEEDS for c in cs for pol in MAIN_POLICIES
                if not (out / f'{c["name"]}__{pol}__{s}.json').exists()]
        print("budget main pending", len(jobs), flush=True)
        run_all(jobs, a.workers); print("COMPLETE", flush=True); return
    if a.phase == "calibrate":
        tg = targets(); assert len(tg) == len(cs), "run phase main first"
        out = ROOT / "results" / "budget_calibration"; out.mkdir(parents=True, exist_ok=True)
        log = dict(seeds=PILOT_SEEDS, warmup_days=2, measurement_days=4, targets=tg, rounds=[])
        jobs = [(dict(c, admit_probability=1.0), "greedy_robot", s, 2, 4, str(out)) for c in cs for s in PILOT_SEEDS]
        print("greedy", len(jobs), flush=True)
        cmax = mean_cov(run_all(jobs, a.workers))
        p = {n: min(1.0, tg[n] / cmax[n]) if cmax[n] > 0 else 1.0 for n in tg}
        log["rounds"].append(dict(policy="greedy_robot", coverage=cmax, next_p=dict(p)))
        for rnd in (1, 2):
            jobs = [(dict(c, admit_probability=p[c["name"]]), "matched_random", s, 2, 4, str(out)) for c in cs for s in PILOT_SEEDS]
            print("random round", rnd, len(jobs), flush=True)
            cov = mean_cov(run_all(jobs, a.workers)); used = dict(p)
            p = {n: min(1.0, p[n] * tg[n] / cov[n]) if cov[n] > 0 else min(1.0, p[n] * 2) for n in tg}
            log["rounds"].append(dict(policy="matched_random", round=rnd, p=used, coverage=cov, next_p=dict(p)))
        log["final_p"] = p
        (ROOT / "budget_calibration.json").write_text(json.dumps(log, indent=2)); print("calibration done", flush=True); return
    if a.phase == "random":
        p = json.loads((ROOT / "budget_calibration.json").read_text())["final_p"]
        out = ROOT / "results" / "budget_random"; out.mkdir(parents=True, exist_ok=True)
        rc = [dict(c, admit_probability=p[c["name"]]) for c in cs]
        freeze("random", dict(phase="random", seeds=SEEDS, warmup_days=7, measurement_days=7,
                              policies=["matched_random"], cases=rc, nodes=NODES))
        jobs = [(c, "matched_random", s, 7, 7, str(out)) for s in SEEDS for c in rc
                if not (out / f'{c["name"]}__matched_random__{s}.json').exists()]
        print("budget random pending", len(jobs), flush=True)
        run_all(jobs, a.workers); print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
