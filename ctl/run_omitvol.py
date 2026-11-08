"""Volume control at the coverage of omitted support, and mission composition logs.
Frozen source in ../src is imported unchanged.

Question 1 (three-term split). B = J(omit) - J(staff) = -S_omit + V* + S, with
  S_omit = J(r2omit) - J(omit)    selection of omitted support relative to random admission at its coverage
  V*     = J(r2omit) - J(rand)    pure volume effect: random admission at omit coverage vs at staff coverage
  S      = J(rand) - J(staff)     selection of staff rollout (results/controls)
r2omit is matched_random recalibrated to the per condition robot coverage of no_support_forecast in the main runs.

Question 2 (mechanism of selection). The composition of robot missions (class, deadline, route, shift, queue at
decision) and the split of weighted tardiness into the robot missions' own tardiness and that of human-served
requests, for staff_rollout, no_support_forecast, matched_random (staff coverage) and r2omit. The three stored
policies are rerun with MissionLogSimulation, which only reads state; J and coverage must equal the stored runs.

Phases
  targets    write omitvol_targets.json from main_runs_subset.csv (no simulation)
  calibrate  pilot seeds 104900-104907 (never used for inference), 2 + 4 days, greedy run and two
             multiplicative corrections, as in the original calibration; writes omitvol_calibration.json
  verify     pilot coverage of the final probabilities; writes omitvol_verify.json
  freeze     writes design_omitvol.json (probabilities, seeds, conditions, analysis plan, code hashes)
  main       runs r2omit and the mission reruns; existing outputs are skipped; refuses to run if the design changed
  check      compares the reruns with the stored runs; writes omitvol_identity.json
"""
import argparse, hashlib, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from mission_simulation import MissionLogSimulation

PILOT_SEEDS = list(range(104900, 104908))
MAIN_SEEDS = list(range(103000, 103020))
OUT_R = ROOT / "results" / "omitvol"
OUT_M = ROOT / "results" / "missions"
RERUN = ("staff_rollout", "no_support_forecast", "matched_random")
PLAN = (
    "Primary (two robots, 20 seeds, 18 conditions, seed averages over equally weighted conditions, 95% t intervals): "
    "V* = J(r2omit) - J(matched_random) and S_omit = J(r2omit) - J(no_support_forecast), with the exact identity "
    "B = J(no_support_forecast) - J(staff_rollout) = -S_omit + V* + S. Coverage match reported as the ratio of r2omit "
    "to target coverage per condition; a coverage adjustment uses the slope between r2omit and matched_random. "
    "Secondary, exploratory: mission composition (share of specimens, deadline, slack = deadline - deterministic "
    "robot duration, route, shift, queue at decision) by policy and arrangement, and the split of S into the "
    "difference in robot missions' own weighted tardiness and in that of human-served requests. "
    "Subgroups by arrangement, unavailability and reporting delay are exploratory."
)


def job(args):
    case, policy, seed, warmup, days, output, tag = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    start = perf_counter()
    result = MissionLogSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  scenario_tag=tag, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    name = f'{tag}__{case["name"]}__{policy}__{seed}.json'
    path = Path(output) / name
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(result, indent=1)); tmp.replace(path)
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 50 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    return out


def mean_coverage(results):
    table = {}
    for (case, *_), (coverage, _) in results:
        table.setdefault(case["name"], []).append(coverage)
    return {k: sum(v) / len(v) for k, v in table.items()}


def case_name(df):
    return df["mode"] + "_b" + (df.background_fraction * 100).round().astype(int).astype(str) + "_lag" + df.information_lag.astype(str)


def targets():
    main = pd.read_csv(ROOT / "main_runs_subset.csv")
    main = main[(main.policy == "no_support_forecast") & main.seed.isin(MAIN_SEEDS)].copy()
    main["case"] = case_name(main)
    counts = main.groupby("case").size()
    if len(counts) != 18 or (counts != len(MAIN_SEEDS)).any():
        raise RuntimeError(f"incomplete stored outcomes {counts.to_dict()}")
    out = main.groupby("case").robot_coverage.mean().to_dict()
    (ROOT / "omitvol_targets.json").write_text(json.dumps(out, indent=2, sort_keys=True))
    print("r2omit mean target coverage", round(sum(out.values()) / len(out), 5))


def jobs_for(p, seeds, warmup, days, output, policy="matched_random", tag="r2omit"):
    return [(dict(c, admit_probability=(1.0 if p is None else p[c["name"]])), policy, s, warmup, days, str(output), tag)
            for c in rw.cases() for s in seeds]


def calibrate(workers):
    target = json.loads((ROOT / "omitvol_targets.json").read_text())
    out = ROOT / "results" / "omitvol_calibration"; out.mkdir(parents=True, exist_ok=True)
    print("greedy", flush=True)
    cmax = mean_coverage(run_all(jobs_for(None, PILOT_SEEDS, 2, 4, out, "greedy_robot"), workers))
    p = {n: min(1.0, target[n] / cmax[n]) if cmax[n] > 0 else 1.0 for n in target}
    rounds = [{"policy": "greedy_robot", "coverage": cmax, "next_p": dict(p)}]
    for rnd in (1, 2):
        print("round", rnd, flush=True)
        cov = mean_coverage(run_all(jobs_for(p, PILOT_SEEDS, 2, 4, out), workers))
        used = dict(p)
        p = {n: min(1.0, p[n] * target[n] / cov[n]) if cov[n] > 0 else min(1.0, p[n] * 2) for n in target}
        rounds.append({"policy": "matched_random", "round": rnd, "p": used, "coverage": cov, "next_p": dict(p)})
    log = {"seeds": PILOT_SEEDS, "warmup_days": 2, "measurement_days": 4, "targets": target, "rounds": rounds, "final_p": p}
    (ROOT / "omitvol_calibration.json").write_text(json.dumps(log, indent=2))
    print("calibration done", flush=True)


def verify(workers):
    cal = json.loads((ROOT / "omitvol_calibration.json").read_text())
    out = ROOT / "results" / "omitvol_verify"; out.mkdir(parents=True, exist_ok=True)
    cov = mean_coverage(run_all(jobs_for(cal["final_p"], PILOT_SEEDS, 2, 4, out), workers))
    t = cal["targets"]
    ratio = {n: cov[n] / t[n] if t[n] > 0 else None for n in t}
    r = sorted(v for v in ratio.values() if v is not None)
    rep = dict(target_mean=sum(t.values()) / len(t), coverage_mean=sum(cov.values()) / len(cov), ratio=ratio, coverage=cov)
    print("target %.5f coverage %.5f ratio median %.2f range %.2f-%.2f"
          % (rep["target_mean"], rep["coverage_mean"], r[len(r) // 2], r[0], r[-1]), flush=True)
    (ROOT / "omitvol_verify.json").write_text(json.dumps(rep, indent=2))


def design():
    cal = json.loads((ROOT / "omitvol_calibration.json").read_text())
    controls = json.loads((ROOT / "design_controls.json").read_text())
    p_staff = {c["name"]: c["admit_probability"] for c in controls["cases"]}
    hashes = {str(f.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
              for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))}
    return dict(
        phase="omitvol", warmup_days=7, measurement_days=7, seeds=MAIN_SEEDS,
        r2omit=dict(policy="matched_random", cases=[dict(c, admit_probability=cal["final_p"][c["name"]]) for c in rw.cases()]),
        missions=dict(policies=list(RERUN), simulator="MissionLogSimulation",
                      cases=[dict(c, admit_probability=p_staff[c["name"]]) for c in rw.cases()],
                      note="matched_random uses the probabilities of design_controls.json"),
        analysis_plan=PLAN, code_hashes=hashes,
        note="Designed on 5 November 2026 after the manuscript review; paired with results/main and results/controls "
             "on identical seeds and conditions.")


def body(d):
    return json.loads(json.dumps({k: v for k, v in d.items() if k != "code_hashes"}))


def stored_main():
    main = pd.read_csv(ROOT / "main_runs_subset.csv")
    main["case"] = case_name(main)
    return {(r.case, r.policy, int(r.seed)): (r.weighted_tardiness_per_request, r.robot_coverage) for r in main.itertuples()}


def check():
    ref = stored_main()
    for f in (ROOT / "results" / "controls").glob("*__matched_random__*.json"):
        r = json.loads(f.read_text())
        ref[(r["case"], "matched_random", int(f.stem.split("__")[-1]))] = (r["weighted_tardiness_per_request"], r["robot_coverage"])
    rows, worst = [], 0.0
    for f in sorted(OUT_M.glob("mis__*.json")):
        _, case, policy, seed = f.stem.split("__")
        r = json.loads(f.read_text())
        j0, c0 = ref[(case, policy, int(seed))]
        dj, dc = abs(r["weighted_tardiness_per_request"] - j0), abs(r["robot_coverage"] - c0)
        worst = max(worst, dj, dc)
        rec = abs(r["mission_log"]["reconstruction_error"])
        rows.append(dict(case=case, policy=policy, seed=int(seed), dJ=dj, dcov=dc, reconstruction=rec))
    df = pd.DataFrame(rows)
    # main_runs_subset.csv stores about 16 significant digits; exact equality is checked against the original JSONs
    rep = dict(n=len(df), max_abs_difference=worst, identical_within_csv_precision=bool(worst <= 1e-12),
               max_reconstruction_error=float(df.reconstruction.max()) if len(df) else None,
               by_policy=df.groupby("policy").size().to_dict() if len(df) else {})
    (ROOT / "omitvol_identity.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=1), flush=True)
    if len(df) != 3 * 18 * 20 or worst > 1e-12:
        raise RuntimeError("mission reruns do not reproduce the stored runs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["targets", "smoke", "calibrate", "verify", "freeze", "main", "check"])
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.phase == "targets":
        return targets()
    if args.phase == "smoke":
        out = ROOT / "results" / "omitvol_smoke"; out.mkdir(parents=True, exist_ok=True)
        c = next(c for c in rw.cases() if c["name"] == "mobile_b40_lag0")
        jobs = [(dict(c, admit_probability=.5), pol, 103000, 1, 1, str(out), "smoke") for pol in RERUN]
        for j, r in run_all(jobs, args.workers):
            print(j[1], "coverage %.4f J %.3f" % r, flush=True)
        return
    if args.phase == "calibrate":
        return calibrate(args.workers)
    if args.phase == "verify":
        return verify(args.workers)
    if args.phase == "check":
        return check()
    path = ROOT / "design_omitvol.json"
    if args.phase == "freeze":
        new = design()
        if path.exists():
            if body(json.loads(path.read_text())) != body(new):
                raise RuntimeError("design_omitvol.json exists and differs: refusing to overwrite.")
            print("design already frozen and unchanged"); return
        path.write_text(json.dumps(new, indent=2))
        print("frozen", path); return
    frozen = json.loads(path.read_text())
    if body(frozen) != body(design()):
        raise RuntimeError("Design or calibration changed since freezing: refusing to mix runs.")
    changed = [k for k, v in frozen["code_hashes"].items() if k.startswith("src/")
               and hashlib.sha256((ROOT / k).read_bytes()).hexdigest() != v]
    if changed:
        raise RuntimeError(f"Frozen simulator source changed: {changed}")
    OUT_R.mkdir(parents=True, exist_ok=True); OUT_M.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s in MAIN_SEEDS:  # seed major order keeps partial results balanced
        for c in frozen["r2omit"]["cases"]:
            if not (OUT_R / f'r2omit__{c["name"]}__matched_random__{s}.json').exists():
                jobs.append((c, "matched_random", s, 7, 7, str(OUT_R), "r2omit"))
        for c in frozen["missions"]["cases"]:
            for pol in frozen["missions"]["policies"]:
                # the stored forecast runs were made without admit_probability in the workflow
                cc = c if pol == "matched_random" else {k: v for k, v in c.items() if k != "admit_probability"}
                if not (OUT_M / f'mis__{c["name"]}__{pol}__{s}.json').exists():
                    jobs.append((cc, pol, s, 7, 7, str(OUT_M), "mis"))
    print("omitvol pending", len(jobs), flush=True)
    run_all(jobs, args.workers)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
