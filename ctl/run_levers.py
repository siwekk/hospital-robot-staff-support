"""Higher demand, night-only robots and multi-load tours. Frozen source in ../src is imported unchanged.

Scenarios (two robots; mobile and local support; b in {0.4, 0.8}; both lags; seeds 103000-103011)
  demand110      demand x1.1, full roster 8/30/24 (x1.25 and above saturate human transport)
  demand120      demand x1.2
  night          robots offered only to requests created 22:00-06:00, full roster
  night4         as night, night shift cut from 8 to 4 transporters
  night4_allday  night shift cut to 4, robots offered at all hours
  cap3           robot tours carry up to three requests from the same origin, no waiting
  cap3_hold10    as cap3, robot waits up to 10 min after loading for further requests
  favorable      demand x1.2, unattended receiving and cap3_hold10 combined
Policies: human_only, staff_rollout, no_support_forecast, and matched_random calibrated per condition
to the coverage of staff_rollout in the same scenario (pilot seeds 104900-104907, 2 + 4 days, greedy run
and two multiplicative corrections, as in the earlier controls).

Phases: smoke, main, calibrate, random (as in run_scarcity.py)
"""
import argparse, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from scarcity_simulation import ScarcitySimulation
from levers_simulation import LeversSimulation
from run_scarcity import staffing, conditions, freeze, mean_coverage, PILOT_SEEDS, SEEDS

OUT = ROOT / "results" / "levers"
NIGHT = [("robots", "active_hours", [22, 6])]
NIGHT4 = [("hospital", "human_staffing", staffing(4, 30, 24))]


def cap(hold):
    return [("robots", "tour_capacity", 3), ("robots", "tour_hold_minutes", hold)]


SCENARIOS = {
    "demand110": [("scenario", "demand_multiplier", 1.1)],
    "demand120": [("scenario", "demand_multiplier", 1.2)],
    "night": NIGHT,
    "night4": NIGHT + NIGHT4,
    "night4_allday": NIGHT4,
    "cap3": cap(0.0),
    "cap3_hold10": cap(10.0),
    "favorable": [("scenario", "demand_multiplier", 1.2), ("robots", "unattended_receiving", True)] + cap(10.0),
}
MAIN_POLICIES = ["human_only", "staff_rollout", "no_support_forecast"]
PLAN = (
    "For each scenario, seed averages over the eight equally weighted conditions, 95% t intervals, 12 seeds. "
    "Reported: J of every policy; staff_rollout - human_only within the scenario; B, V and S as in the scarcity "
    "phase; robot coverage, released staff minutes per day, mobile utilization, joined requests and tour size. "
    "Scenarios with demand x1 and the full roster are also compared with the baseline of the main runs. "
    "All contrasts are descriptive (designed after the main results)."
)


def job(args):
    case, policy, seed, warmup, days, output, tag, overrides, klass = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    for section, key, value in overrides:
        cfg[section][key] = value
    start = perf_counter()
    sim = (ScarcitySimulation if klass == "scarcity" else LeversSimulation)(cfg, parameters, seed=seed)
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


def smoke(workers):
    out = ROOT / "results" / "levers_smoke"; out.mkdir(parents=True, exist_ok=True)
    cases = {c["name"]: c for c in conditions()}
    jobs = []
    for name in ("local_b80_lag0", "mobile_b40_lag10"):
        jobs += [(cases[name], "staff_rollout", 103000, 1, 1, str(out), "same_scarcity_" + name, [], "scarcity"),
                 (cases[name], "staff_rollout", 103000, 1, 1, str(out), "same_levers_" + name, [], "levers")]
    for tag in SCENARIOS:
        for name in ("local_b40_lag0", "mobile_b40_lag0"):
            jobs += [(cases[name], pol, 103000, 1, 1, str(out), tag, SCENARIOS[tag], "levers") for pol in MAIN_POLICIES]
            jobs.append((dict(cases[name], admit_probability=.05), "matched_random", 103000, 1, 1, str(out), tag, SCENARIOS[tag], "levers"))
    res = {(j[6], j[0]["name"], j[1]): r for j, r in run_all(jobs, workers)}
    skip = {"elapsed_seconds", "decision_mean_ms", "decision_p95_ms", "scenario_tag", "active_hours", "tour_capacity",
            "tour_hold_minutes", "gated_requests", "tours", "tour_items", "joined_requests", "tour_hold_total_minutes",
            "mean_tour_size"}
    for name in ("local_b80_lag0", "mobile_b40_lag10"):
        a = res[("same_scarcity_" + name, name, "staff_rollout")][2]
        b = res[("same_levers_" + name, name, "staff_rollout")][2]
        diff = [k for k in a if k not in skip and a[k] != b.get(k)]
        print(name, "LeversSimulation without flags vs ScarcitySimulation, differing keys:", diff)
        if diff:
            raise RuntimeError("LeversSimulation without flags does not reproduce ScarcitySimulation")
    for (tag, name, pol), (cov, J, r) in sorted(res.items()):
        if tag.startswith("same_"):
            continue
        print(f"{tag:14s} {name:16s} {pol:20s} cov {cov:.4f} J {J:.3f} util {r['human_utilization']:.3f} "
              f"created {r['created']} gated {r['gated_requests']} tours {r['tours']} joined {r['joined_requests']} "
              f"size {r['mean_tour_size']:.2f} hold {r['tour_hold_total_minutes']:.1f} released {r['net_released_minutes']:.1f}")


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
        freeze("levers", dict(phase="levers", scenarios=SCENARIOS, seeds=SEEDS, warmup_days=7, measurement_days=7,
                              policies=MAIN_POLICIES, cases=cases, fleet_size=2, analysis_plan=PLAN))
        jobs = [(c, pol, s, 7, 7, str(OUT), tag, ov, "levers") for s in SEEDS for tag, ov in SCENARIOS.items()
                for c in cases for pol in MAIN_POLICIES if not (OUT / f'{tag}__{c["name"]}__{pol}__{s}.json').exists()]
        jobs.sort(key=lambda j: -float(dict((k, v) for _, k, v in j[7]).get("demand_multiplier", 1.0)))
        print("levers main pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)
        return
    if args.phase == "calibrate":
        targets = {}
        for tag in SCENARIOS:
            for c in cases:
                vals = [json.loads((OUT / f'{tag}__{c["name"]}__staff_rollout__{s}.json').read_text())["robot_coverage"] for s in SEEDS]
                targets.setdefault(tag, {})[c["name"]] = sum(vals) / len(vals)
        cal_out = ROOT / "results" / "levers_calibration"; cal_out.mkdir(parents=True, exist_ok=True)
        jobs = [(dict(c, admit_probability=1.0), "greedy_robot", s, 2, 4, str(cal_out), tag, ov, "levers")
                for tag, ov in SCENARIOS.items() for c in cases for s in PILOT_SEEDS]
        print("greedy", len(jobs), flush=True)
        cmax = mean_coverage(run_all(jobs, args.workers))
        p = {tag: {n: min(1.0, targets[tag][n] / cmax[(tag, n)]) if cmax[(tag, n)] > 0 else 1.0 for n in targets[tag]} for tag in SCENARIOS}
        log = dict(seeds=PILOT_SEEDS, warmup_days=2, measurement_days=4, targets=targets,
                   rounds=[dict(policy="greedy_robot", coverage={f"{t}|{n}": v for (t, n), v in cmax.items()}, next_p=p)])
        for rnd in (1, 2):
            jobs = [(dict(c, admit_probability=p[tag][c["name"]]), "matched_random", s, 2, 4, str(cal_out), tag, ov, "levers")
                    for tag, ov in SCENARIOS.items() for c in cases for s in PILOT_SEEDS]
            print("matched_random round", rnd, len(jobs), flush=True)
            cov = mean_coverage(run_all(jobs, args.workers))
            used = json.loads(json.dumps(p))
            p = {tag: {n: min(1.0, p[tag][n] * targets[tag][n] / cov[(tag, n)]) if cov[(tag, n)] > 0 else min(1.0, p[tag][n] * 2)
                       for n in targets[tag]} for tag in SCENARIOS}
            log["rounds"].append(dict(policy="matched_random", round=rnd, p=used, coverage={f"{t}|{n}": v for (t, n), v in cov.items()}, next_p=p))
        log["final_p"] = p
        (ROOT / "levers_calibration.json").write_text(json.dumps(log, indent=2))
        print("calibration done", flush=True)
        return
    if args.phase == "random":
        p = json.loads((ROOT / "levers_calibration.json").read_text())["final_p"]
        arms = {tag: [dict(c, admit_probability=p[tag][c["name"]]) for c in cases] for tag in SCENARIOS}
        freeze("levers_random", dict(phase="levers_random", scenarios=SCENARIOS, seeds=SEEDS, warmup_days=7,
                                     measurement_days=7, policies=["matched_random"], arms=arms, fleet_size=2, analysis_plan=PLAN))
        jobs = [(c, "matched_random", s, 7, 7, str(OUT), tag, SCENARIOS[tag], "levers") for s in SEEDS for tag in SCENARIOS
                for c in arms[tag] if not (OUT / f'{tag}__{c["name"]}__matched_random__{s}.json').exists()]
        print("levers random pending", len(jobs), flush=True)
        run_all(jobs, args.workers); print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
