"""Staff cost family and sensitivity experiments. Frozen source in ../src is imported unchanged.

Phases: test, cost_pilot, cost_main, sens.
Pilot seeds 104900+ are never used for inference. Main phases use seeds 103000+ and are paired with
results/main (human_only, staff_rollout, no_support_forecast, ...) on identical seeds.
"""
import argparse, hashlib, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from extra_simulation import ExtraSimulation

PILOT_SEEDS = list(range(104900, 104908))
SCENARIOS = {  # sensitivity overrides: (section, key, value)
    "fleet4": [("robots", "fleet_size", 4)],
    "fleet8": [("robots", "fleet_size", 8)],
    "speed72": [("hospital", "robot_speed_m_per_min", 72.0)],
    "support1p5": [("robots", "support_multiplier", 1.5)],
    "support0p5": [("robots", "support_multiplier", 0.5)],
}


def job(args):
    case, policy, seed, warmup, days, output, tag, overrides = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    for section, key, value in overrides:
        cfg[section][key] = value
    start = perf_counter()
    result = ExtraSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  scenario_tag=tag, overrides=overrides, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    name = f'{tag}__{case["name"]}__{policy}__{seed}.json'
    (Path(output) / name).write_text(json.dumps(result, indent=2))
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 25 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    return out


def freeze(name, design):
    path = ROOT / f"design_{name}.json"
    design["code_hashes"] = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
                             for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))
                             if f.name != "run_extra.py" or True}
    # hashes of runner files may legitimately change between phases; only the design body is compared
    body = json.loads(json.dumps({k: v for k, v in design.items() if k != "code_hashes"}))
    if path.exists():
        previous = {k: v for k, v in json.loads(path.read_text()).items() if k != "code_hashes"}
        if previous != body:
            raise RuntimeError("Design changed: refusing to mix runs.")
    else:
        path.write_text(json.dumps(design, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["test", "cost_pilot", "cost_main", "phi_pilot", "phi_main", "sens", "sens_opt", "sens_opt8"])
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    cases = rw.cases()
    if args.phase == "test":  # lambda = 0 must reproduce the frozen policies bit for bit
        base.initialize()
        out = ROOT / "results" / "test"; out.mkdir(parents=True, exist_ok=True)
        case = next(dict(c, staff_cost=0.0) for c in cases if c["name"] == "mobile_b40_lag0")
        for pol, ref in (("staff_cost", "staff_rollout"), ("omitted_cost", "no_support_forecast")):
            job((case, pol, 103000, 7, 7, str(out), "test", []))
            new = json.loads((out / f"test__mobile_b40_lag0__{pol}__103000.json").read_text())
            old = json.loads((ROOT / "ref" / f"mobile_b40_lag0__{ref}__103000.json").read_text()) \
                if (ROOT / "ref" / f"mobile_b40_lag0__{ref}__103000.json").exists() else None
            if old is None:
                print(pol, "no stored reference; J =", new["weighted_tardiness_per_request"]); continue
            diff = [k for k in old if k not in ("elapsed_seconds", "decision_mean_ms", "decision_p95_ms")
                    and k not in ("policy",) and new.get(k) != old[k]]
            print(pol, "differing keys vs", ref, ":", diff[:8])
        return
    if args.phase == "cost_pilot":
        out = ROOT / "results" / "cost_pilot"; out.mkdir(parents=True, exist_ok=True)
        grid = [0.002, 0.005, 0.01, 0.02, 0.05]
        jobs = [(dict(c, staff_cost=lam), "staff_cost", s, 2, 4, str(out), f"lam{lam}", [])
                for lam in grid for c in cases for s in PILOT_SEEDS]
        print("cost pilot", len(jobs), flush=True)
        res = run_all(jobs, args.workers)
        table = {}
        for (case, pol, seed, *_rest, tag, _), (cov, j) in res:
            table.setdefault(tag, []).append((cov, j))
        summary = {t: dict(coverage=sum(c for c, _ in v) / len(v), J=sum(j for _, j in v) / len(v)) for t, v in table.items()}
        (ROOT / "cost_pilot_summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=1), flush=True)
        return
    if args.phase == "phi_pilot":
        out = ROOT / "results" / "phi_pilot"; out.mkdir(parents=True, exist_ok=True)
        grid = [1.0, 3.0, 10.0, 30.0]
        jobs = [(dict(c, phi=phi), "staff_phi", s, 2, 4, str(out), f"phi{phi}", [])
                for phi in grid for c in cases for s in PILOT_SEEDS[:4]]
        print("phi pilot", len(jobs), flush=True)
        res = run_all(jobs, args.workers)
        table = {}
        for (case, pol, seed, *_rest, tag, _), (cov, j) in res:
            table.setdefault(tag, []).append((cov, j))
        summary = {t: dict(coverage=sum(c for c, _ in v) / len(v), J=sum(j for _, j in v) / len(v)) for t, v in table.items()}
        (ROOT / "phi_pilot_summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=1), flush=True)
        return
    if args.phase == "phi_main":
        phis = json.loads((ROOT / "phi_grid.json").read_text())
        out = ROOT / "results" / "phi_main"; out.mkdir(parents=True, exist_ok=True)
        seeds = list(range(103000, 103008))
        freeze("phi_main", dict(phase="phi_main", phis=phis, seeds=seeds, warmup_days=7, measurement_days=7,
                                policies=["staff_phi", "omitted_phi"], cases=cases))
        jobs = [(dict(c, phi=phi), pol, s, 7, 7, str(out), f"phi{phi}", [])
                for s in seeds for c in cases for phi in phis for pol in ("staff_phi", "omitted_phi")
                if not (out / f'phi{phi}__{c["name"]}__{pol}__{s}.json').exists()]
        print("phi main pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)
        return
    if args.phase == "cost_main":
        lams = json.loads((ROOT / "cost_grid.json").read_text())
        out = ROOT / "results" / "cost_main"; out.mkdir(parents=True, exist_ok=True)
        seeds = list(range(103000, 103008))
        freeze("cost_main", dict(phase="cost_main", lambdas=lams, seeds=seeds, warmup_days=7, measurement_days=7,
                                 policies=["staff_cost", "omitted_cost"], cases=cases))
        jobs = [(dict(c, staff_cost=lam), pol, s, 7, 7, str(out), f"lam{lam}", [])
                for s in seeds for c in cases for lam in lams for pol in ("staff_cost", "omitted_cost")
                if not (out / f'lam{lam}__{c["name"]}__{pol}__{s}.json').exists()]
        print("cost main pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)
        return
    if args.phase in ("sens_opt", "sens_opt8"):  # optimizer on a larger fleet, seed major order so partial results stay balanced
        out = ROOT / "results" / "sens_opt"; out.mkdir(parents=True, exist_ok=True)
        seeds = list(range(103000, 103006))
        chosen = [c for c in cases if c["mode"] in ("mobile", "local") and c["background_fraction"] in (.4, .8)]
        fleet = "fleet8" if args.phase == "sens_opt8" else "fleet4"
        scen = {fleet: SCENARIOS[fleet]}
        freeze(args.phase, dict(phase=args.phase, scenarios=scen, seeds=seeds, warmup_days=7, measurement_days=7,
                                policies=["optimizer"], cases=chosen))
        jobs = [(c, "optimizer", s, 7, 7, str(out), tag, ov) for s in seeds for c in chosen for tag, ov in scen.items()
                if not (out / f'{tag}__{c["name"]}__optimizer__{s}.json').exists()]
        print("sens_opt pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)
        return
    if args.phase == "sens":
        out = ROOT / "results" / "sens"; out.mkdir(parents=True, exist_ok=True)
        seeds = list(range(103000, 103006))
        chosen = [c for c in cases if c["mode"] in ("mobile", "local") and c["background_fraction"] in (.4, .8)]
        p = json.loads((ROOT / "calibration.json").read_text())["final_p"]
        policies = ["staff_rollout", "no_support_forecast", "idle_pair_rule"]
        freeze("sens", dict(phase="sens", scenarios=SCENARIOS, seeds=seeds, warmup_days=7, measurement_days=7,
                            policies=policies, cases=chosen))
        jobs = [(c, pol, s, 7, 7, str(out), tag, ov) for s in seeds for tag, ov in SCENARIOS.items()
                for c in chosen for pol in policies
                if not (out / f'{tag}__{c["name"]}__{pol}__{s}.json').exists()]
        print("sens pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
