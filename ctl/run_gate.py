"""Staff availability gate (ctl/gate_simulation.py) on the main design: 18 conditions, seeds 103000-103019,
7 warm-up and 7 measured days, class mix of the main experiment. Added on 17 November 2026 (IJSR revision).

Phases
  test   staff_gate with the gate disabled reproduces two stored staff_rollout runs of the main experiment
  main   staff_gate on all conditions and seeds; writes design_gate.json on first use
"""
import argparse, hashlib, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_workflows as rw
from gate_simulation import HriSimulation

SEEDS = list(range(103000, 103020))
OUT = ROOT / "results" / "gate"


def job(args):
    case, policy, seed, warmup, days, output, tag = args
    path = Path(output) / f'{tag}__{case["name"]}__{policy}__{seed}.json'
    if path.exists():
        r = json.loads(path.read_text()); return r["robot_coverage"], r["weighted_tardiness_per_request"]
    parameters = dict(base.PARAMETERS, task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1))
    cfg = rw.config(case, policy, warmup, days)
    start = perf_counter()
    result = HriSimulation(cfg, parameters, seed=seed).run()
    result.update(case=case["name"], policy=policy, workflow=case, warmup_days=warmup, measurement_days=days,
                  scenario_tag=tag, elapsed_seconds=perf_counter() - start)
    assert result["created"] == result["completed"] + result["incomplete"]
    assert result["battery_infeasible_missions"] == 0
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(result, indent=1)); tmp.replace(path)
    return result["robot_coverage"], result["weighted_tardiness_per_request"]


def run_all(jobs, workers):
    t0 = perf_counter(); out = []
    print(f"{len(jobs)} runs", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=base.initialize) as pool:
        futures = {pool.submit(job, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            out.append((futures[f], f.result()))
            if i % 20 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} {perf_counter() - t0:.0f} s", flush=True)
    return out


def test(workers, ref_dir):
    out = OUT / "test"; out.mkdir(parents=True, exist_ok=True)
    names = ["mobile_b40_lag0", "local_b80_lag10"]
    cs = {c["name"]: c for c in rw.cases()}
    res = run_all([(dict(cs[n], gate=False), "staff_gate", 103000, 7, 7, str(out), "nogate") for n in names], workers)
    ok = True
    for (j, (cov, J)) in res:
        ref = json.loads((Path(ref_dir) / f'{j[0]["name"]}__staff_rollout__103000.json').read_text())
        same = cov == ref["robot_coverage"] and J == ref["weighted_tardiness_per_request"]
        ok &= same
        print(j[0]["name"], "J", J, ref["weighted_tardiness_per_request"], "cov", cov, ref["robot_coverage"], "identical" if same else "DIFFERENT")
    if not ok:
        raise RuntimeError("gate disabled does not reproduce staff_rollout")


def main(workers):
    hashes = {str(f.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(f.read_bytes()).hexdigest()
              for d in ("src", "ctl") for f in sorted((ROOT / d).rglob("*.py"))}
    design = dict(phase="gate", policy="staff_gate", seeds=SEEDS, warmup_days=7, measurement_days=7, cases=rw.cases(),
                  task_mix=dict(specimen=.4, medication=.3, supply=.2, instrument=.1), simulator="HriSimulation", code_hashes=hashes)
    path = ROOT / "design_gate.json"
    if not path.exists():
        path.write_text(json.dumps(design, indent=2))
    else:
        old = json.loads(path.read_text())
        if {k: v for k, v in old.items() if k != "code_hashes"} != json.loads(json.dumps({k: v for k, v in design.items() if k != "code_hashes"})):
            raise RuntimeError("design_gate.json differs: refusing to mix runs")
    OUT.mkdir(parents=True, exist_ok=True)
    run_all([(c, "staff_gate", s, 7, 7, str(OUT), "gate") for s in SEEDS for c in rw.cases()], workers)
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["test", "main"], required=True)
    ap.add_argument("--workers", type=int, default=11)
    ap.add_argument("--ref", default=str(ROOT / "ref"))
    a = ap.parse_args()
    test(a.workers, a.ref) if a.phase == "test" else main(a.workers)
