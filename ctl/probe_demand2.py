"""Probe 2: human only, mobile, several seeds, fine demand grid."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_study as base
import run_levers as rl

out = ROOT / "results" / "levers_probe"; out.mkdir(parents=True, exist_ok=True)
cases = {c["name"]: c for c in rl.conditions()}
grid = (1.0, 1.05, 1.1, 1.15, 1.2, 1.25)
jobs = [(cases[n], "human_only", s, 7, 7, str(out), f"p{int(m*100)}", [("scenario", "demand_multiplier", m)], "levers")
        for m in grid for n in ("mobile_b40_lag0", "mobile_b80_lag0") for s in range(103000, 103006)]
with ProcessPoolExecutor(max_workers=10, initializer=base.initialize) as pool:
    res = list(pool.map(rl.job, jobs))
import collections
agg = collections.defaultdict(list)
for j, (cov, J, r) in zip(jobs, res):
    agg[(j[6], j[0]["name"])].append((J, r["human_utilization"], r["created"] / 7))
for k in sorted(agg):
    v = agg[k]
    print(k, "J", [round(x[0], 2) for x in v], "util", round(sum(x[1] for x in v) / len(v), 3), "req/day", round(sum(x[2] for x in v) / len(v)))
