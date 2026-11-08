"""Volume control along the staff time front and at matched coverage of the forecast without support.
Frozen source in ../src is imported unchanged. Designed on 8 November 2026 after the second manuscript review.

Question 1 (front). Does representing support add selection value when robots are admitted more often?
  The allowance rules staff_phi and omitted_phi (phi = 3, 10; results/phi_main, seeds 103000-103007) are extended
  to seeds 103008-103019, and matched random arms are calibrated per condition to the coverage of each of the four
  allowance rules (arms rf_staff3, rf_staff10, rf_omit3, rf_omit10). With the existing arms at the coverage of
  staff rollout (results/controls) and of omitted support (results/omitvol), each condition has a curve of random
  admission against coverage; the selection value of a rule is the random curve at its coverage minus its J.

Question 2 (selection at equal coverage). omitted_quota keeps the choice of omitted support but admits only if the
  predicted reduction of weighted tardiness is at least theta_c, calibrated per condition to the coverage of staff
  rollout. J(omitted_quota) - J(staff_rollout) compares the two forecasts' selection at the same volume.

Phases
  test       theta = 0 reproduces no_support_forecast, and FrontSimulation reproduces a stored staff_phi run
  targets    frontvol_targets.json (coverage of the four allowance rules from phi_main; staff rollout coverage)
  qpilot     theta grid on pilot seeds 104900-104907 (2 + 4 days)
  qcalib     two interpolation refinements of theta per condition
  rcalib     random arms: greedy coverage from omitvol_calibration.json, two multiplicative corrections
  verify     pilot coverage of the final theta and probabilities
  freeze     design_frontvol.json
  main       phi extension, four random arms and omitted_quota on seeds 103000-103019 (phi: 103008-103019)
"""
import argparse, hashlib, json, math, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from frontvol_simulation import FrontSimulation

PILOT_SEEDS = list(range(104900, 104908))
MAIN_SEEDS = list(range(103000, 103020))
PHI_EXT_SEEDS = list(range(103008, 103020))
PHIS = (3.0, 10.0)
ARMS = {"rf_staff3": ("staff_phi", 3.0), "rf_staff10": ("staff_phi", 10.0),
        "rf_omit3": ("omitted_phi", 3.0), "rf_omit10": ("omitted_phi", 10.0)}
# lexicographic threshold (ctl/frontvol_simulation.py): below 1000 a flow-time margin for tardiness ties,
# from 1000 on a tardiness margin of (t - 1000) / 100 weighted minutes
THETA_GRID = [0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 999.0,
              1025.0, 1050.0, 1100.0, 1200.0, 1400.0, 1800.0, 2600.0]
OUT = ROOT / "results" / "frontvol"
PLAN = (
    "Primary (two robots, 20 seeds, 18 conditions, seed averages over equally weighted conditions, 95% t intervals). "
    "(1) Front: for each allowance rule f in {staff_phi, omitted_phi} x phi in {3, 10}, the selection value "
    "S_f = R(cov_f) - J_f, where R(cov) is the random admission curve of the condition, linear in coverage between "
    "the random arms that bracket cov_f (arms at the coverage of staff rollout, omitted support and the four "
    "allowance rules; per seed J, per condition mean coverage); and the difference S_staff(phi) - S_omit(phi). "
    "(2) Equal coverage: J(omitted_quota) - J(staff_rollout), with omitted_quota calibrated to the coverage of "
    "staff rollout, and the path B = [J(omit) - J(quota)] + [J(quota) - J(staff)]. "
    "(3) Coverage adjustment per condition: slope between the random arms at the coverage of staff rollout and of "
    "omitted support in each condition. Secondary, exploratory: subsets by arrangement, unavailability and delay; "
    "mission composition of omitted_quota and the random arms."
)


def job(args):
    case, policy, seed, warmup, days, output, tag = args
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    start = perf_counter()
    result = FrontSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  scenario_tag=tag, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    path = Path(output) / f'{tag}__{case["name"]}__{policy}__{seed}.json'
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(result, indent=1)); tmp.replace(path)
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers):
    out = []
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    return out


def mean_by(results, key):
    table = {}
    for j, (coverage, _) in results:
        table.setdefault(key(j), []).append(coverage)
    return {k: sum(v) / len(v) for k, v in table.items()}


def cases():
    return rw.cases()


def stored(policy):
    main = pd.read_csv(ROOT / "main_runs_subset.csv")
    main = main[main.policy == policy].copy()
    main["case"] = main["mode"] + "_b" + (main.background_fraction * 100).round().astype(int).astype(str) + "_lag" + main.information_lag.astype(str)
    return main


def test(workers):
    out = ROOT / "results" / "frontvol_test"; out.mkdir(parents=True, exist_ok=True)
    c = next(c for c in cases() if c["name"] == "mobile_b40_lag0")
    c2 = next(c for c in cases() if c["name"] == "local_b0_lag0")
    jobs = [(dict(c, theta=0.0), "omitted_quota", 103000, 7, 7, str(out), "test"),
            (dict(c2, phi=10.0), "staff_phi", 103000, 7, 7, str(out), "test")]
    res = dict(((j[1]), r) for j, r in run_all(jobs, workers))
    ref = stored("no_support_forecast")
    ref = ref[(ref.case == "mobile_b40_lag0") & (ref.seed == 103000)].iloc[0]
    phi = json.loads((ROOT / "results" / "phi_main" / "phi10.0__local_b0_lag0__staff_phi__103000.json").read_text())
    rep = dict(quota_theta0=dict(J=res["omitted_quota"][1], cov=res["omitted_quota"][0],
                                 J_ref=float(ref.weighted_tardiness_per_request), cov_ref=float(ref.robot_coverage)),
               staff_phi10=dict(J=res["staff_phi"][1], cov=res["staff_phi"][0],
                                J_ref=phi["weighted_tardiness_per_request"], cov_ref=phi["robot_coverage"]))
    ok = all(abs(v["J"] - v["J_ref"]) <= 1e-12 and abs(v["cov"] - v["cov_ref"]) <= 1e-12 for v in rep.values())
    rep["identical"] = ok
    (ROOT / "frontvol_test.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=1), flush=True)
    if not ok:
        raise RuntimeError("reproduction test failed")


def targets():
    rows = []
    for f in (ROOT / "results" / "phi_main").glob("*.json"):
        r = json.loads(f.read_text())
        rows.append(dict(case=r["case"], policy=r["policy"], phi=float(r["workflow"]["phi"]), cov=r["robot_coverage"]))
    df = pd.DataFrame(rows)
    if len(df) != 576:
        raise RuntimeError("phi_main incomplete")
    out = {}
    for arm, (pol, phi) in ARMS.items():
        d = df[(df.policy == pol) & (df.phi == phi)]
        out[arm] = d.groupby("case")["cov"].mean().to_dict()
    out["omitted_quota"] = json.loads((ROOT / "coverage_targets.json").read_text())
    (ROOT / "frontvol_targets.json").write_text(json.dumps(out, indent=2, sort_keys=True))
    for k, v in out.items():
        print(k, "mean target", round(sum(v.values()) / len(v), 5), flush=True)


def quota_jobs(theta, seeds, warmup, days, output, tag="q"):
    return [(dict(c, theta=float(theta[c["name"]] if isinstance(theta, dict) else theta)), "omitted_quota", s, warmup, days, str(output), tag)
            for c in cases() for s in seeds]


def interpolate(points, target):
    """points: list of (theta, coverage); coverage decreases with theta on average. Linear in log(1 + theta)."""
    pts = sorted(points)
    if target >= pts[0][1]:
        return pts[0][0]
    for (t0, c0), (t1, c1) in zip(pts, pts[1:]):
        if (c0 - target) * (c1 - target) <= 0 and c0 != c1:
            x0, x1 = math.log1p(t0), math.log1p(t1)
            return math.expm1(x0 + (target - c0) / (c1 - c0) * (x1 - x0))
    return pts[-1][0]


def qpilot(workers):
    out = ROOT / "results" / "frontvol_qpilot"; out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for t in THETA_GRID:
        jobs += quota_jobs(t, PILOT_SEEDS[:4], 2, 4, out, f"q{t}")
    res = run_all(jobs, workers)
    cov = mean_by(res, lambda j: (j[0]["name"], j[0]["theta"]))
    grid = {}
    for (name, t), v in cov.items():
        grid.setdefault(name, []).append([t, v])
    (ROOT / "frontvol_qpilot.json").write_text(json.dumps(grid, indent=2, sort_keys=True))
    print("theta pilot done", flush=True)


def qcalib(workers):
    target = json.loads((ROOT / "frontvol_targets.json").read_text())["omitted_quota"]
    grid = {k: [tuple(p) for p in v] for k, v in json.loads((ROOT / "frontvol_qpilot.json").read_text()).items()}
    out = ROOT / "results" / "frontvol_qcalib"; out.mkdir(parents=True, exist_ok=True)
    theta = {n: interpolate(grid[n], target[n]) for n in target}
    rounds = []
    for rnd in (1, 2):
        print("theta round", rnd, flush=True)
        cov = mean_by(run_all(quota_jobs(theta, PILOT_SEEDS, 2, 4, out, f"qr{rnd}"), workers), lambda j: j[0]["name"])
        rounds.append(dict(theta=dict(theta), coverage=cov))
        for n in target:
            grid[n].append((theta[n], cov[n]))
        theta = {n: interpolate(grid[n], target[n]) for n in target}
    log = dict(seeds=PILOT_SEEDS, grid_seeds=PILOT_SEEDS[:4], warmup_days=2, measurement_days=4, targets=target,
               grid=grid, rounds=rounds, final_theta=theta,
               threshold="t < 1000: flow margin for tardiness ties; t >= 1000: tardiness margin (t - 1000) / 100")
    (ROOT / "frontvol_qcalibration.json").write_text(json.dumps(log, indent=2))
    print("theta calibration done", flush=True)


def random_jobs(p, arms, seeds, warmup, days, output):
    return [(dict(c, admit_probability=float(p[arm][c["name"]])), "matched_random", s, warmup, days, str(output), arm)
            for arm in arms for c in cases() for s in seeds]


def rcalib(workers):
    target = json.loads((ROOT / "frontvol_targets.json").read_text())
    cmax = json.loads((ROOT / "omitvol_calibration.json").read_text())["rounds"][0]["coverage"]
    out = ROOT / "results" / "frontvol_rcalib"; out.mkdir(parents=True, exist_ok=True)
    p = {a: {n: min(1.0, target[a][n] / cmax[n]) for n in cmax} for a in ARMS}
    rounds = [dict(greedy_coverage=cmax, next_p=json.loads(json.dumps(p)))]
    for rnd in (1, 2):
        print("random round", rnd, flush=True)
        cov = mean_by(run_all(random_jobs(p, ARMS, PILOT_SEEDS, 2, 4, out), workers), lambda j: (j[-1], j[0]["name"]))
        used = json.loads(json.dumps(p))
        for a in ARMS:
            for n in cmax:
                c = cov[(a, n)]
                p[a][n] = min(1.0, p[a][n] * target[a][n] / c) if c > 0 else min(1.0, p[a][n] * 2)
        rounds.append(dict(round=rnd, p=used, coverage={f"{a}|{n}": v for (a, n), v in cov.items()}, next_p=json.loads(json.dumps(p))))
    log = dict(seeds=PILOT_SEEDS, warmup_days=2, measurement_days=4, targets={a: target[a] for a in ARMS}, rounds=rounds, final_p=p)
    (ROOT / "frontvol_rcalibration.json").write_text(json.dumps(log, indent=2))
    print("random calibration done", flush=True)


def verify(workers):
    t = json.loads((ROOT / "frontvol_targets.json").read_text())
    theta = json.loads((ROOT / "frontvol_qcalibration.json").read_text())["final_theta"]
    p = json.loads((ROOT / "frontvol_rcalibration.json").read_text())["final_p"]
    out = ROOT / "results" / "frontvol_verify"; out.mkdir(parents=True, exist_ok=True)
    jobs = quota_jobs(theta, PILOT_SEEDS, 2, 4, out, "omitted_quota") + random_jobs(p, ARMS, PILOT_SEEDS, 2, 4, out)
    cov = mean_by(run_all(jobs, workers), lambda j: (j[-1], j[0]["name"]))
    rep = {}
    for arm in list(ARMS) + ["omitted_quota"]:
        ratio = sorted(cov[(arm, n)] / t[arm][n] for n in t[arm] if t[arm][n] > 0)
        rep[arm] = dict(target_mean=sum(t[arm].values()) / 18, coverage_mean=sum(cov[(arm, n)] for n in t[arm]) / 18,
                        ratio_median=ratio[len(ratio) // 2], ratio_min=ratio[0], ratio_max=ratio[-1])
        print(arm, " ".join(f"{k} {v:.4f}" for k, v in rep[arm].items()), flush=True)
    (ROOT / "frontvol_verify.json").write_text(json.dumps(rep, indent=2))


def design():
    theta = json.loads((ROOT / "frontvol_qcalibration.json").read_text())["final_theta"]
    p = json.loads((ROOT / "frontvol_rcalibration.json").read_text())["final_p"]
    hashes = {str(f.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
              for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))}
    return dict(
        phase="frontvol", warmup_days=7, measurement_days=7, seeds=MAIN_SEEDS, simulator="FrontSimulation",
        phi_extension=dict(policies=["staff_phi", "omitted_phi"], phis=list(PHIS), seeds=PHI_EXT_SEEDS,
                           note="extends results/phi_main (seeds 103000-103007) with the same design"),
        random_arms={a: dict(reference=list(ARMS[a]), cases=[dict(c, admit_probability=p[a][c["name"]]) for c in cases()]) for a in ARMS},
        omitted_quota=dict(cases=[dict(c, theta=theta[c["name"]]) for c in cases()]),
        analysis_plan=PLAN, code_hashes=hashes)


def body(d):
    return json.loads(json.dumps({k: v for k, v in d.items() if k != "code_hashes"}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["test", "targets", "qpilot", "qcalib", "rcalib", "verify", "freeze", "main"])
    parser.add_argument("--workers", type=int, default=2)
    a = parser.parse_args()
    if a.phase in ("test", "qpilot", "qcalib", "rcalib", "verify"):
        return globals()[a.phase](a.workers)
    if a.phase == "targets":
        return targets()
    path = ROOT / "design_frontvol.json"
    if a.phase == "freeze":
        new = design()
        if path.exists():
            if body(json.loads(path.read_text())) != body(new):
                raise RuntimeError("design_frontvol.json exists and differs: refusing to overwrite.")
            print("design already frozen and unchanged"); return
        path.write_text(json.dumps(new, indent=2)); print("frozen", path); return
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
        if s in PHI_EXT_SEEDS:
            for c in cases():
                for phi in PHIS:
                    for pol in ("staff_phi", "omitted_phi"):
                        if not (OUT / f'phi{phi}__{c["name"]}__{pol}__{s}.json').exists():
                            jobs.append((dict(c, phi=phi), pol, s, 7, 7, str(OUT), f"phi{phi}"))
        for arm, spec in frozen["random_arms"].items():
            for c in spec["cases"]:
                if not (OUT / f'{arm}__{c["name"]}__matched_random__{s}.json').exists():
                    jobs.append((c, "matched_random", s, 7, 7, str(OUT), arm))
        for c in frozen["omitted_quota"]["cases"]:
            if not (OUT / f'quota__{c["name"]}__omitted_quota__{s}.json').exists():
                jobs.append((c, "omitted_quota", s, 7, 7, str(OUT), "quota"))
    print("frontvol pending", len(jobs), flush=True)
    run_all(jobs, a.workers)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
