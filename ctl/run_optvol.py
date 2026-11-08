"""Volume control for the optimization policy. Frozen source in ../src is imported unchanged.

Question: is the advantage of optimization over staff rollout a selection effect or a consequence of
admitting fewer robots? matched_random is recalibrated to the per condition robot coverage of the
optimizer, and for larger fleets also to that of staff rollout (the main design has that arm only for
two robots, in results/controls).

Arms (tag = file prefix)
  r2opt       two robots, 18 conditions, seeds 103000-103019, p tuned to optimizer coverage (main runs)
  fleet4opt   four robots, 8 sensitivity conditions, seeds 103000-103005, p tuned to optimizer coverage
  fleet4roll  four robots, same, p tuned to staff rollout coverage (results/sens)
  fleet8opt, fleet8roll   the same for eight robots

Phases
  targets    write optvol_targets.json from stored outcomes (no simulation)
  smoke      one short run per arm
  calibrate  pilot seeds 104900-104907 (never used for inference), 2 + 4 days, greedy run and two
             multiplicative corrections, as in the original calibration; writes optvol_calibration.json
  freeze     writes design_optvol.json (probabilities, seeds, conditions, analysis plan, code hashes)
  main       runs the frozen design; existing outputs are skipped; refuses to run if the design changed
"""
import argparse, hashlib, json, sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_workflows as rw
from run_extra import SCENARIOS, job, run_all

PILOT_SEEDS = list(range(104900, 104908))
MAIN_SEEDS = list(range(103000, 103020))
SENS_SEEDS = list(range(103000, 103006))
OUT = ROOT / "results" / "optvol"
ARMS = {  # tag: (fleet scenario or None, condition subset, seeds)
    "r2opt": (None, "all", MAIN_SEEDS),
    "fleet4opt": ("fleet4", "sens", SENS_SEEDS), "fleet4roll": ("fleet4", "sens", SENS_SEEDS),
    "fleet8opt": ("fleet8", "sens", SENS_SEEDS), "fleet8roll": ("fleet8", "sens", SENS_SEEDS),
}
PLAN = (
    "Primary (two robots, 20 seeds, 18 conditions, seed averages over equally weighted conditions): "
    "S_opt = J(r2opt) - J(optimizer), selection value of optimization at matched volume, 95% t interval. "
    "Secondary: V_opt = J(matched_random, results/controls) - J(r2opt), the effect of reducing random admission "
    "from rollout to optimizer coverage, and the exact identity J(staff_rollout) - J(optimizer) = V_opt + S_opt - S_roll "
    "with S_roll = J(matched_random) - J(staff_rollout). Coverage match is reported as the ratio of random to target "
    "coverage per condition. Fleets four and eight (6 seeds, 8 conditions): the same decomposition with fleetXroll "
    "replacing matched_random, exploratory. Subgroups by arrangement are exploratory."
)


def conditions(subset):
    cases = rw.cases()
    if subset == "sens":
        cases = [c for c in cases if c["mode"] in ("mobile", "local") and c["background_fraction"] in (.4, .8)]
    return cases


def stored(folder, pattern):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text())
        rows.append(dict(case=r["case"], policy=r["policy"], seed=int(f.stem.split("__")[-1]), coverage=r["robot_coverage"]))
    return pd.DataFrame(rows)


def targets():
    main = pd.read_csv(ROOT / "main_runs_subset.csv")
    main = main[(main.policy == "optimizer") & main.seed.isin(MAIN_SEEDS)]
    main["case"] = main["mode"] + "_b" + (main.background_fraction * 100).round().astype(int).astype(str) + "_lag" + main.information_lag.astype(str)
    out = {"r2opt": main.groupby("case").robot_coverage.mean().to_dict()}
    for fleet in ("fleet4", "fleet8"):
        opt = stored(ROOT / "results" / "sens_opt", f"{fleet}__*__optimizer__*.json")
        roll = stored(ROOT / "results" / "sens", f"{fleet}__*__staff_rollout__*.json")
        for tag, d in ((f"{fleet}opt", opt), (f"{fleet}roll", roll)):
            d = d[d.seed.isin(SENS_SEEDS)]
            counts = d.groupby("case").size()
            if len(counts) != 8 or (counts != len(SENS_SEEDS)).any():
                raise RuntimeError(f"{tag}: incomplete stored outcomes {counts.to_dict()}")
            out[tag] = d.groupby("case").coverage.mean().to_dict()
    for tag, (_, subset, _) in ARMS.items():
        names = {c["name"] for c in conditions(subset)}
        if set(out[tag]) != names:
            raise RuntimeError(f"{tag}: conditions {sorted(out[tag])} differ from design {sorted(names)}")
    (ROOT / "optvol_targets.json").write_text(json.dumps(out, indent=2, sort_keys=True))
    for tag, t in out.items():
        print(tag, "mean target coverage", round(sum(t.values()) / len(t), 5))


def jobs_for(tag, p, seeds, warmup, days, output, policy="matched_random"):
    fleet, subset, _ = ARMS[tag]
    ov = SCENARIOS[fleet] if fleet else []
    return [(dict(c, admit_probability=(1.0 if p is None else p[c["name"]])), policy, s, warmup, days, str(output), tag, ov)
            for c in conditions(subset) for s in seeds]


def mean_coverage(results):
    table = {}
    for (case, *_), (coverage, _) in results:
        table.setdefault(case["name"], []).append(coverage)
    return {k: sum(v) / len(v) for k, v in table.items()}


def calibrate(workers):
    T = json.loads((ROOT / "optvol_targets.json").read_text())
    out = ROOT / "results" / "optvol_calibration"; out.mkdir(parents=True, exist_ok=True)
    log = {"seeds": PILOT_SEEDS, "warmup_days": 2, "measurement_days": 4, "arms": {}}
    greedy = {}
    for tag, (fleet, subset, _) in ARMS.items():  # greedy coverage depends only on fleet and conditions
        key = (fleet, subset)
        if key not in greedy:
            print("greedy", tag, flush=True)
            greedy[key] = mean_coverage(run_all(jobs_for(tag, None, PILOT_SEEDS, 2, 4, out, "greedy_robot"), workers))
    for tag in ARMS:
        fleet, subset, _ = ARMS[tag]
        target, cmax = T[tag], greedy[(fleet, subset)]
        p = {n: min(1.0, target[n] / cmax[n]) if cmax[n] > 0 else 1.0 for n in target}
        rounds = [{"policy": "greedy_robot", "coverage": cmax, "next_p": dict(p)}]
        for rnd in (1, 2):
            print(tag, "round", rnd, flush=True)
            cov = mean_coverage(run_all(jobs_for(tag, p, PILOT_SEEDS, 2, 4, out), workers))
            used = dict(p)
            p = {n: min(1.0, p[n] * target[n] / cov[n]) if cov[n] > 0 else min(1.0, p[n] * 2) for n in target}
            rounds.append({"policy": "matched_random", "round": rnd, "p": used, "coverage": cov, "next_p": dict(p)})
        log["arms"][tag] = {"targets": target, "rounds": rounds, "final_p": p}
    (ROOT / "optvol_calibration.json").write_text(json.dumps(log, indent=2))
    print("calibration done", flush=True)


def verify(workers):
    """Coverage of the final probabilities on the pilot seeds; informs freezing, never inference."""
    cal = json.loads((ROOT / "optvol_calibration.json").read_text())
    out = ROOT / "results" / "optvol_verify"; out.mkdir(parents=True, exist_ok=True)
    report = {}
    for tag, arm in cal["arms"].items():
        cov = mean_coverage(run_all(jobs_for(tag, arm["final_p"], PILOT_SEEDS, 2, 4, out), workers))
        t = arm["targets"]
        ratio = {n: cov[n] / t[n] if t[n] > 0 else None for n in t}
        report[tag] = dict(target_mean=sum(t.values()) / len(t), coverage_mean=sum(cov.values()) / len(cov),
                           ratio=ratio, coverage=cov)
        r = sorted(v for v in ratio.values() if v is not None)
        print(tag, "target %.5f coverage %.5f ratio median %.2f range %.2f-%.2f"
              % (report[tag]["target_mean"], report[tag]["coverage_mean"], r[len(r) // 2], r[0], r[-1]), flush=True)
    (ROOT / "optvol_verify.json").write_text(json.dumps(report, indent=2))


def design():
    cal = json.loads((ROOT / "optvol_calibration.json").read_text())
    hashes = {str(f.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
              for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))}
    arms = {tag: dict(scenario=fleet, overrides=SCENARIOS[fleet] if fleet else [], seeds=seeds,
                      cases=[dict(c, admit_probability=cal["arms"][tag]["final_p"][c["name"]]) for c in conditions(subset)])
            for tag, (fleet, subset, seeds) in ARMS.items()}
    return dict(phase="optvol", policy="matched_random", warmup_days=7, measurement_days=7, arms=arms,
                analysis_plan=PLAN, code_hashes=hashes,
                note="Designed after the optimizer fleet results of 5 November 2026; paired with results/main, "
                     "results/controls, results/sens and results/sens_opt on identical seeds and conditions.")


def body(d):
    return json.loads(json.dumps({k: v for k, v in d.items() if k != "code_hashes"}))  # tuples -> lists


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["targets", "smoke", "calibrate", "verify", "freeze", "main"])
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.phase == "targets":
        return targets()
    if args.phase == "smoke":
        out = ROOT / "results" / "optvol_smoke"; out.mkdir(parents=True, exist_ok=True)
        jobs = [j for tag in ARMS for j in jobs_for(tag, None, [103000], 1, 1, out)[:1]]
        jobs = [(dict(c, admit_probability=.5), *rest) for (c, *rest) in jobs]
        for j, r in run_all(jobs, args.workers):
            print(j[6], j[0]["name"], "coverage %.4f J %.3f" % r)
        return
    if args.phase == "calibrate":
        return calibrate(args.workers)
    if args.phase == "verify":
        return verify(args.workers)
    path = ROOT / "design_optvol.json"
    if args.phase == "freeze":
        new = design()
        if path.exists():
            if body(json.loads(path.read_text())) != body(new):
                raise RuntimeError("design_optvol.json exists and differs: refusing to overwrite.")
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
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s in MAIN_SEEDS:  # seed major order keeps partial results balanced
        for tag, arm in frozen["arms"].items():
            if s not in arm["seeds"]:
                continue
            for c in arm["cases"]:
                if not (OUT / f'{tag}__{c["name"]}__matched_random__{s}.json').exists():
                    jobs.append((c, "matched_random", s, 7, 7, str(OUT), tag, arm["overrides"]))
    print("optvol pending", len(jobs), flush=True)
    run_all(jobs, args.workers)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
