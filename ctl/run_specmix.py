"""Sensitivity of the main contrasts to the share of urgent specimens in the class mix.
Frozen source in ../src is imported unchanged. Designed on 17 November 2026 after the IJSR review, which asked
whether the results depend on the synthetic assumption that 40% of requests are urgent specimens.

Class mix: specimens 20% instead of 40%; medication, supply and instrument keep their 3:2:1 ratio
(40.0%, 26.7%, 13.3%). Everything else is the design of the main experiment.

Policies on seeds 103000-103009 (7 warm-up and 7 measured days, 18 conditions):
  human_only, staff_rollout, no_support_forecast (omitted support),
  matched_random at the coverage of staff rollout in the new mix, calibrated per condition,
  omitted_quota (threshold rule) at the coverage of staff rollout in the new mix, calibrated per condition.
Calibration on pilot seeds 104900-104907 (2 + 4 days), as in run_omitvol.py and run_frontvol.py:
  random arm: greedy coverage, then two multiplicative corrections towards the target;
  threshold: reduced grid on four pilot seeds, then two interpolation refinements on eight.
All runs use FrontSimulation (mission log, read only).

Phases (each resumable; existing run files are skipped)
  a      staff_rollout, human_only, no_support_forecast on main seeds; greedy arm and theta grid on pilot seeds
  b      targets from the staff rollout runs; random and threshold calibration rounds; specmix_calibration.json
  c      design_specmix.json; matched_random and omitted_quota on main seeds
  all    a, b, c
"""
import argparse, hashlib, json, math, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from frontvol_simulation import FrontSimulation

MIX = dict(specimen=0.2, medication=0.4, supply=0.8 / 3, instrument=0.4 / 3)
PILOT_SEEDS = list(range(104900, 104908))
MAIN_SEEDS = list(range(103000, 103010))
THETA_GRID = [0.0, 1.0, 4.0, 16.0, 64.0, 256.0, 999.0, 1025.0, 1100.0, 1400.0, 2600.0]
OUT = ROOT / "results" / "specmix"
CAL = ROOT / "specmix_calibration.json"
DESIGN = ROOT / "design_specmix.json"


def job(args):
    case, policy, seed, warmup, days, output, tag = args
    path = Path(output) / f'{tag}__{case["name"]}__{policy}__{seed}.json'
    if path.exists():
        r = json.loads(path.read_text())
        return r["robot_coverage"], r["weighted_tardiness_per_request"]
    parameters = dict(base.PARAMETERS, task_mix=dict(MIX))
    cfg = rw.config(case, policy, warmup, days)
    start = perf_counter()
    result = FrontSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  scenario_tag=tag, task_mix=MIX, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["human_completed"] + result["robot_completed"] == result["completed"]
    assert result["battery_infeasible_missions"] == 0
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(result, indent=1)); tmp.replace(path)
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers, label):
    out = []
    t0 = perf_counter()
    print(f"{label}: {len(jobs)} runs", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 25 == 0 or i == len(jobs):
                print(f"  {label} {i}/{len(jobs)}  {perf_counter() - t0:.0f} s", flush=True)
    return out


def mean_cov(results, key):
    table = {}
    for j, (coverage, _) in results:
        table.setdefault(key(j), []).append(coverage)
    return {k: sum(v) / len(v) for k, v in table.items()}


def cases():
    return rw.cases()


def d(sub):
    p = OUT / sub; p.mkdir(parents=True, exist_ok=True); return str(p)


def interpolate(points, target):
    pts = sorted(points)
    if target >= pts[0][1]:
        return pts[0][0]
    for (t0, c0), (t1, c1) in zip(pts, pts[1:]):
        if (c0 - target) * (c1 - target) <= 0 and c0 != c1:
            x0, x1 = math.log1p(t0), math.log1p(t1)
            return math.expm1(x0 + (target - c0) / (c1 - c0) * (x1 - x0))
    return pts[-1][0]


def main_jobs(policies):
    return [(c, p, s, 7, 7, d("main"), "mix20") for s in MAIN_SEEDS for c in cases() for p in policies]


def greedy_jobs():
    return [(c, "greedy_robot", s, 2, 4, d("calib"), "greedy") for c in cases() for s in PILOT_SEEDS]


def grid_jobs():
    return [(dict(c, theta=t), "omitted_quota", s, 2, 4, d("calib"), f"q{t}") for t in THETA_GRID
            for c in cases() for s in PILOT_SEEDS[:4]]


def phase_a(workers):
    run_all(main_jobs(["staff_rollout", "human_only", "no_support_forecast"]) + greedy_jobs() + grid_jobs(), workers, "phase a")


def phase_b(workers):
    sr = [json.loads((Path(d("main")) / f'mix20__{c["name"]}__staff_rollout__{s}.json').read_text())
          for c in cases() for s in MAIN_SEEDS]
    target = {}
    for r in sr:
        target.setdefault(r["case"], []).append(r["robot_coverage"])
    target = {k: sum(v) / len(v) for k, v in target.items()}
    cmax = mean_cov(run_all(greedy_jobs(), workers, "greedy"), lambda j: j[0]["name"])
    grid_res = run_all(grid_jobs(), workers, "theta grid")
    grid = {}
    for (name, t), v in mean_cov(grid_res, lambda j: (j[0]["name"], j[0]["theta"])).items():
        grid.setdefault(name, []).append((t, v))
    p = {n: min(1.0, target[n] / cmax[n]) if cmax[n] > 0 else 1.0 for n in target}
    theta = {n: interpolate(grid[n], target[n]) for n in target}
    rounds = [dict(greedy_coverage=cmax, next_p=dict(p), next_theta=dict(theta))]
    for rnd in (1, 2):
        jobs = [(dict(c, admit_probability=p[c["name"]]), "matched_random", s, 2, 4, d("calib"), f"r{rnd}") for c in cases() for s in PILOT_SEEDS]
        jobs += [(dict(c, theta=theta[c["name"]]), "omitted_quota", s, 2, 4, d("calib"), f"qr{rnd}") for c in cases() for s in PILOT_SEEDS]
        cov = mean_cov(run_all(jobs, workers, f"calibration round {rnd}"), lambda j: (j[1], j[0]["name"]))
        used_p, used_t = dict(p), dict(theta)
        for n in target:
            c = cov[("matched_random", n)]
            p[n] = min(1.0, p[n] * target[n] / c) if c > 0 else min(1.0, p[n] * 2)
            grid[n].append((theta[n], cov[("omitted_quota", n)]))
            theta[n] = interpolate(grid[n], target[n])
        rounds.append(dict(round=rnd, p=used_p, theta=used_t,
                           coverage={f"{a}|{n}": v for (a, n), v in cov.items()}, next_p=dict(p), next_theta=dict(theta)))
    log = dict(task_mix=MIX, pilot_seeds=PILOT_SEEDS, grid_seeds=PILOT_SEEDS[:4], warmup_days=2, measurement_days=4,
               targets=target, grid=grid, rounds=rounds, final_p=p, final_theta=theta)
    CAL.write_text(json.dumps(log, indent=2))
    print("calibration written", flush=True)


def phase_c(workers):
    cal = json.loads(CAL.read_text())
    hashes = {str(f.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
              for dd in ("src", "ctl") for f in sorted((ROOT / dd).rglob("*.py"))}
    design = dict(phase="specmix", task_mix=MIX, warmup_days=7, measurement_days=7, seeds=MAIN_SEEDS, simulator="FrontSimulation",
                  policies=["human_only", "staff_rollout", "no_support_forecast", "matched_random", "omitted_quota"],
                  matched_random=[dict(c, admit_probability=cal["final_p"][c["name"]]) for c in cases()],
                  omitted_quota=[dict(c, theta=cal["final_theta"][c["name"]]) for c in cases()], code_hashes=hashes)
    if DESIGN.exists():
        old = json.loads(DESIGN.read_text())
        if {k: v for k, v in old.items() if k != "code_hashes"} != json.loads(json.dumps({k: v for k, v in design.items() if k != "code_hashes"})):
            raise RuntimeError("design_specmix.json differs from the calibration: refusing to mix runs")
    else:
        DESIGN.write_text(json.dumps(design, indent=2))
    jobs = [(c, "matched_random", s, 7, 7, d("main"), "mix20") for s in MAIN_SEEDS for c in design["matched_random"]]
    jobs += [(c, "omitted_quota", s, 7, 7, d("main"), "mix20") for s in MAIN_SEEDS for c in design["omitted_quota"]]
    run_all(jobs, workers, "phase c")
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["a", "b", "c", "all"])
    ap.add_argument("--workers", type=int, default=11)
    a = ap.parse_args()
    for ph in (["a", "b", "c"] if a.phase == "all" else [a.phase]):
        globals()[f"phase_{ph}"](a.workers)
