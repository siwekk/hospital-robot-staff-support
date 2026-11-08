"""Warm-up check: 14 instead of 7 warm-up days for human transport and staff rollout in three conditions,
20 main seeds. A longer warm-up shifts the demand stream, so the comparison with the stored 7-day runs is unpaired
(Welch intervals). Output warmup_check.json; runs in results/warmup_check.
"""
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "ctl"))
import run_workflows as rw
from run_frontvol import run_all, MAIN_SEEDS, stored

CASES = ["mobile_b80_lag0", "local_b80_lag0", "mixed_b40_lag0"]
POLICIES = ["human_only", "staff_rollout"]


def main(workers):
    out = ROOT / "results" / "warmup_check"; out.mkdir(parents=True, exist_ok=True)
    cs = [c for c in rw.cases() if c["name"] in CASES]
    jobs = [(c, p, s, 14, 7, str(out), "wu14") for c in cs for p in POLICIES for s in MAIN_SEEDS
            if not (out / f'wu14__{c["name"]}__{p}__{s}.json').exists()]
    # anchor of the random curve: matched random with probability zero must equal human transport
    c0 = next(c for c in cs if c["name"] == "mobile_b80_lag0")
    jobs.append((dict(c0, admit_probability=0.0), "matched_random", 103000, 7, 7, str(out), "p0"))
    run_all(jobs, workers)
    p0 = json.loads((out / "p0__mobile_b80_lag0__matched_random__103000.json").read_text())
    h = stored("human_only"); h = h[(h.case == "mobile_b80_lag0") & (h.seed == 103000)].iloc[0]
    anchor = dict(J_p0=p0["weighted_tardiness_per_request"], J_human=float(h.weighted_tardiness_per_request),
                  identical=abs(p0["weighted_tardiness_per_request"] - float(h.weighted_tardiness_per_request)) <= 1e-12)
    print("anchor", anchor, flush=True)
    rows = []
    for f in out.glob("wu14__*.json"):
        r = json.loads(f.read_text())
        rows.append(dict(case=r["case"], policy=r["policy"], seed=int(f.stem.split("__")[-1]), J=r["weighted_tardiness_per_request"]))
    new = pd.DataFrame(rows)
    rep = {}
    for p in POLICIES:
        old = stored(p)
        for c in CASES:
            a = new[(new.case == c) & (new.policy == p)].J.values
            b = old[(old.case == c)].weighted_tardiness_per_request.values
            t = stats.ttest_ind(a, b, equal_var=False)
            rep[f"{c}|{p}"] = dict(J14=float(a.mean()), J7=float(b.mean()), diff=float(a.mean() - b.mean()),
                                   rel=float(a.mean() / b.mean() - 1), p=float(t.pvalue), n=[len(a), len(b)])
    rep["anchor_p0_equals_human"] = anchor
    (ROOT / "warmup_check.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
