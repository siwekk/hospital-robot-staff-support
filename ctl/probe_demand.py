"""Probe: where does human transport saturate as demand rises? Human only and staff rollout, one seed."""
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_levers as rl

out = ROOT / "results" / "levers_probe"; out.mkdir(parents=True, exist_ok=True)
cases = {c["name"]: c for c in rl.conditions()}
jobs = []
for m in (1.25, 1.5, 1.75):
    for name in ("mobile_b40_lag0", "mobile_b80_lag0", "local_b40_lag0", "local_b80_lag0"):
        for pol in ("human_only", "staff_rollout"):
            jobs.append((cases[name], pol, 103000, 7, 7, str(out), f"d{int(m*100)}", [("scenario", "demand_multiplier", m)], "levers"))
with ProcessPoolExecutor(max_workers=10, initializer=base.initialize) as pool:
    futures = {pool.submit(rl.job, j): j for j in jobs}
    for f in as_completed(futures):
        case, pol, *_r, tag, _o, _k = futures[f]
        cov, J, r = f.result()
        print(f"{tag:5s} {case['name']:16s} {pol:14s} J {J:8.3f} cov {cov:.4f} util {r['human_utilization']:.3f} "
              f"created/day {r['created']/7:.0f} trunc {r['queue_truncations']} s {r['elapsed_seconds']:.0f}", flush=True)
