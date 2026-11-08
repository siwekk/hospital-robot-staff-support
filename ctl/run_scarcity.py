"""Staff scarcity and unattended receiving. Frozen source in ../src is imported unchanged.

Scenarios (two robots; mobile and local support; b in {0.4, 0.8}; both lags; seeds 103000-103011)
  roster85    mobile roster 7/26/20 (53 transporters, 424 staffed hours per day, 85% of 496)
  roster70    mobile roster 6/21/17 (44 transporters, 352 staffed hours per day, 71% of 496)
  unattended  full roster; robots deposit loads in a receptacle, receiving needs no worker
Policies: human_only, staff_rollout, no_support_forecast, and matched_random calibrated per condition
to the coverage of staff_rollout in the same scenario (pilot seeds 104900-104907, 2 + 4 days, greedy
run and two multiplicative corrections, as in the original controls).

Phases
  smoke       short runs; checks that unattended=False reproduces ExtraSimulation exactly
  main        freezes design_scarcity.json and runs the three forecast and human policies
  calibrate   targets from the stored staff_rollout runs, then pilot calibration
  random      freezes design_scarcity_random.json and runs matched_random
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
from scarcity_simulation import ScarcitySimulation

PILOT_SEEDS = list(range(104900, 104908))
SEEDS = list(range(103000, 103012))
OUT = ROOT / "results" / "scarcity"


def staffing(night, day, evening):
    return [dict(name=n, start_hour=s, end_hour=e, count=c)
            for n, s, e, c in zip(["night", "day", "evening"], [22, 6, 14], [6, 14, 22], [night, day, evening])]


SCENARIOS = {
    "roster85": [("hospital", "human_staffing", staffing(7, 26, 20))],
    "roster70": [("hospital", "human_staffing", staffing(6, 21, 17))],
    "unattended": [("robots", "unattended_receiving", True)],
}
MAIN_POLICIES = ["human_only", "staff_rollout", "no_support_forecast"]
PLAN = (
    "For each scenario, seed averages over the eight equally weighted conditions, 95% t intervals, 12 seeds. "
    "Reported: J of every policy; staff_rollout - human_only; B = J(no_support_forecast) - J(staff_rollout); "
    "V = J(no_support_forecast) - J(matched_random); S = J(matched_random) - J(staff_rollout); robot coverage, "
    "released staff minutes per day and mobile transport utilization. The baseline uses the main runs and "
    "results/controls on the same seeds and conditions. Contrasts by arrangement and by b are exploratory, "
    "and all contrasts are descriptive (designed after the main results)."
)


def conditions():
    return [c for c in rw.cases() if c["mode"] in ("mobile", "local") and c["background_fraction"] in (.4, .8)]


def job(args):
    case, policy, seed, warmup, days, output, tag, overrides, klass = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    for section, key, value in overrides:
        cfg[section][key] = value
    start = perf_counter()
    sim = (ExtraSimulation if klass == "extra" else ScarcitySimulation)(cfg, parameters, seed=seed)
    result = sim.run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  scenario_tag=tag, overrides=overrides, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    path = Path(output) / f'{tag}__{case["name"]}__{policy}__{seed}.json'
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(result, indent=2)); tmp.replace(path)
    return result["robot_coverage"], result["weighted_tardiness_per_request"], result


def run_all(jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 25 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    return out


def hashes():
    return {str(f.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
            for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))}


def freeze(name, design):
    path = ROOT / f"design_{name}.json"
    design = json.loads(json.dumps(design))
    if path.exists():
        old = json.loads(path.read_text())
        if {k: v for k, v in old.items() if k != "code_hashes"} != design:
            raise RuntimeError(f"{path.name} differs: refusing to mix runs.")
        changed = [k for k, v in old["code_hashes"].items() if k.startswith("src/") and hashlib.sha256((ROOT / k).read_bytes()).hexdigest() != v]
        if changed:
            raise RuntimeError(f"Frozen source changed: {changed}")
    else:
        path.write_text(json.dumps(dict(design, code_hashes=hashes()), indent=2))


def mean_coverage(results):
    table = {}
    for (case, _p, _s, _w, _d, _o, tag, *_), (coverage, *_r) in results:
        table.setdefault((tag, case["name"]), []).append(coverage)
    return {k: sum(v) / len(v) for k, v in table.items()}


def smoke(workers):
    out = ROOT / "results" / "scarcity_smoke"; out.mkdir(parents=True, exist_ok=True)
    case = next(c for c in conditions() if c["name"] == "local_b80_lag0")
    jobs = [(case, "staff_rollout", 103000, 1, 1, str(out), "same_extra", [], "extra"),
            (case, "staff_rollout", 103000, 1, 1, str(out), "same_scarcity", [], "scarcity")]
    jobs += [(case, pol, 103000, 1, 1, str(out), tag, SCENARIOS[tag], "scarcity")
             for tag in SCENARIOS for pol in MAIN_POLICIES]
    jobs.append((dict(case, admit_probability=.05), "matched_random", 103000, 1, 1, str(out), "unattended", SCENARIOS["unattended"], "scarcity"))
    res = {(j[6], j[1]): r for j, r in run_all(jobs, workers)}
    a, b = res[("same_extra", "staff_rollout")][2], res[("same_scarcity", "staff_rollout")][2]
    skip = {"elapsed_seconds", "decision_mean_ms", "decision_p95_ms", "scenario_tag", "unattended_receiving"}
    diff = [k for k in a if k not in skip and a[k] != b.get(k)]
    print("unattended=False vs ExtraSimulation, differing keys:", diff)
    if diff:
        raise RuntimeError("ScarcitySimulation without the flag does not reproduce ExtraSimulation")
    for (tag, pol), (cov, J, r) in sorted(res.items()):
        print(f"{tag:14s} {pol:20s} cov {cov:.4f} J {J:.3f} util {r['human_utilization']:.3f} "
              f"recv_service {r['local_receive_service'] + r['mobile_receive_service']:.1f} unattended {r.get('unattended_receive_count', '-')}")
    u = res[("unattended", "staff_rollout")][2]
    assert u["local_receive_service"] == 0 and u["mobile_receive_service"] == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["smoke", "main", "calibrate", "random"])
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.phase == "smoke":
        return smoke(args.workers)
    OUT.mkdir(parents=True, exist_ok=True)
    cases = conditions()
    if args.phase == "main":
        freeze("scarcity", dict(phase="scarcity", scenarios=SCENARIOS, seeds=SEEDS, warmup_days=7, measurement_days=7,
                                policies=MAIN_POLICIES, cases=cases, fleet_size=2, analysis_plan=PLAN))
        jobs = [(c, pol, s, 7, 7, str(OUT), tag, ov, "scarcity") for s in SEEDS for tag, ov in SCENARIOS.items()
                for c in cases for pol in MAIN_POLICIES if not (OUT / f'{tag}__{c["name"]}__{pol}__{s}.json').exists()]
        print("scarcity main pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)
        return
    if args.phase == "calibrate":
        targets = {}
        for tag in SCENARIOS:
            for c in cases:
                vals = [json.loads((OUT / f'{tag}__{c["name"]}__staff_rollout__{s}.json').read_text())["robot_coverage"] for s in SEEDS]
                targets.setdefault(tag, {})[c["name"]] = sum(vals) / len(vals)
        cal_out = ROOT / "results" / "scarcity_calibration"; cal_out.mkdir(parents=True, exist_ok=True)
        jobs = [(dict(c, admit_probability=1.0), "greedy_robot", s, 2, 4, str(cal_out), tag, ov, "scarcity")
                for tag, ov in SCENARIOS.items() for c in cases for s in PILOT_SEEDS]
        print("greedy", len(jobs), flush=True)
        cmax = mean_coverage(run_all(jobs, args.workers))
        p = {tag: {n: min(1.0, targets[tag][n] / cmax[(tag, n)]) if cmax[(tag, n)] > 0 else 1.0 for n in targets[tag]} for tag in SCENARIOS}
        log = dict(seeds=PILOT_SEEDS, warmup_days=2, measurement_days=4, targets=targets,
                   rounds=[dict(policy="greedy_robot", coverage={f"{t}|{n}": v for (t, n), v in cmax.items()}, next_p=p)])
        for rnd in (1, 2):
            jobs = [(dict(c, admit_probability=p[tag][c["name"]]), "matched_random", s, 2, 4, str(cal_out), tag, ov, "scarcity")
                    for tag, ov in SCENARIOS.items() for c in cases for s in PILOT_SEEDS]
            print("matched_random round", rnd, len(jobs), flush=True)
            cov = mean_coverage(run_all(jobs, args.workers))
            used = json.loads(json.dumps(p))
            p = {tag: {n: min(1.0, p[tag][n] * targets[tag][n] / cov[(tag, n)]) if cov[(tag, n)] > 0 else min(1.0, p[tag][n] * 2)
                       for n in targets[tag]} for tag in SCENARIOS}
            log["rounds"].append(dict(policy="matched_random", round=rnd, p=used, coverage={f"{t}|{n}": v for (t, n), v in cov.items()}, next_p=p))
        log["final_p"] = p
        (ROOT / "scarcity_calibration.json").write_text(json.dumps(log, indent=2))
        print("calibration done", flush=True)
        return
    if args.phase == "random":
        p = json.loads((ROOT / "scarcity_calibration.json").read_text())["final_p"]
        arms = {tag: [dict(c, admit_probability=p[tag][c["name"]]) for c in cases] for tag in SCENARIOS}
        freeze("scarcity_random", dict(phase="scarcity_random", scenarios=SCENARIOS, seeds=SEEDS, warmup_days=7,
                                       measurement_days=7, policies=["matched_random"], arms=arms, fleet_size=2, analysis_plan=PLAN))
        jobs = [(c, "matched_random", s, 7, 7, str(OUT), tag, SCENARIOS[tag], "scarcity") for s in SEEDS for tag in SCENARIOS
                for c in arms[tag] if not (OUT / f'{tag}__{c["name"]}__matched_random__{s}.json').exists()]
        print("scarcity random pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
