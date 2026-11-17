"""Analysis of the class-mix sensitivity (ctl/run_specmix.py): main contrasts with 20% and 40% specimens on the
same seeds 103000-103009 and 18 conditions. The 40% values come from the stored runs of the main, control and
equal coverage phases (analysis_human/human_side_runs.csv.gz, written by ctl/analyze_human_side.py).
Seed means over equally weighted conditions, 95% Student t intervals across seeds. S is not coverage adjusted.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_specmix"
SEEDS = list(range(103000, 103010))
POL = {"human_only": "H", "staff_rollout": "SR", "no_support_forecast": "OS", "matched_random": "MR", "omitted_quota": "Thr",
       "threshold_rule": "Thr"}


def tci(x):
    x = np.asarray(x, float); n = len(x); m = x.mean()
    h = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)
    return m, m - h, m + h


def load20():
    rows, mis = [], []
    for p in sorted((ROOT / "results" / "specmix" / "main").glob("mix20__*.json")):
        r = json.loads(p.read_text()); w = r["workflow"]
        calls = r["human_support_tasks"]
        rows.append(dict(policy=POL[r["policy"]], seed=r["seed"], mode=w["mode"], b=w["background_fraction"], lag=w["information_lag"],
                         J=r["weighted_tardiness_per_request"], coverage=r["robot_coverage"], late=r["late_fraction"],
                         calls_per_day=calls / 7, wait_per_call=r["human_support_wait_minutes"] / calls if calls else np.nan,
                         released_per_day=r["net_released_minutes"] / 7,
                         urgent_share=r["urgent_created"] / r["created"]))
        for m in r["mission_log"]["missions"]:
            mis.append(dict(policy=POL[r["policy"]], seed=r["seed"], mode=w["mode"], specimen=float(m["task_type"] == "specimen"),
                            no_idle=float(m["idle_mobile"] == 0), late=float(m["weighted_tardiness"] > 0)))
    return pd.DataFrame(rows), pd.DataFrame(mis)


def contrasts(D, label):
    key = ["seed", "mode", "b", "lag"]
    W = D.pivot_table(index=key, columns="policy", values="J")
    out = []
    defs = [("SR - H", "SR", "H"), ("B = OS - SR", "OS", "SR"), ("S = MR - SR", "MR", "SR"), ("Thr - SR", "Thr", "SR"),
            ("OS - Thr", "OS", "Thr"), ("Thr - MR", "Thr", "MR")]
    for sub, sel in [("all", None), ("mobile", "mobile"), ("mixed", "mixed"), ("local", "local"), ("b=0.8", 0.8)]:
        w = W if sel is None else (W[W.index.get_level_values("b") == sel] if isinstance(sel, float) else W[W.index.get_level_values("mode") == sel])
        for name, a, b in defs:
            if a in w and b in w:
                m, lo, hi = tci((w[a] - w[b]).groupby(level="seed").mean())
                out.append(dict(mix=label, subset=sub, contrast=name, mean=m, lo=lo, hi=hi))
    return pd.DataFrame(out)


def main():
    OUT.mkdir(exist_ok=True)
    D20, M20 = load20()
    H = pd.read_csv(ROOT / "analysis_human" / "human_side_runs.csv.gz")
    H = H[H.policy.isin(POL) & H.seed.isin(SEEDS)].copy(); H["policy"] = H.policy.map(POL)
    C = pd.concat([contrasts(D20, "20%"), contrasts(H, "40%")])
    # difference of contrasts between the mixes, paired by seed
    key = ["seed", "mode", "b", "lag"]
    W20 = D20.pivot_table(index=key, columns="policy", values="J"); W40 = H.pivot_table(index=key, columns="policy", values="J")
    for name, a, b in [("SR - H", "SR", "H"), ("B = OS - SR", "OS", "SR"), ("Thr - SR", "Thr", "SR"), ("S = MR - SR", "MR", "SR")]:
        d = ((W20[a] - W20[b]) - (W40[a] - W40[b])).dropna().groupby(level="seed").mean()
        m, lo, hi = tci(d)
        C = pd.concat([C, pd.DataFrame([dict(mix="20% - 40%", subset="all", contrast=name, mean=m, lo=lo, hi=hi)])])
    C.to_csv(OUT / "specmix_contrasts.csv", index=False)
    means = []
    for label, D in (("20%", D20), ("40%", H)):
        cm = D.groupby(["policy", "mode", "b", "lag"])[["J", "coverage"]].mean().groupby("policy").mean()
        for pol, r in cm.iterrows():
            means.append(dict(mix=label, policy=pol, J=r.J, coverage=r.coverage))
    means = pd.DataFrame(means)
    means.to_csv(OUT / "specmix_means.csv", index=False)
    prof = []
    for (pol, mode), g in M20.groupby(["policy", "mode"]):
        prof.append(dict(policy=pol, mode=mode, missions=len(g), specimen=g.specimen.mean(), no_idle=g.no_idle.mean(), late=g.late.mean()))
    for pol, g in M20[M20["mode"] != "local"].groupby("policy"):
        prof.append(dict(policy=pol, mode="transporters", missions=len(g), specimen=g.specimen.mean(), no_idle=g.no_idle.mean(), late=g.late.mean()))
    P = pd.DataFrame(prof); P.to_csv(OUT / "specmix_mission_profile.csv", index=False)
    side = D20.groupby(["policy", "mode", "b", "lag"])[["calls_per_day", "wait_per_call", "released_per_day", "urgent_share"]].mean().groupby("policy").mean()
    side.to_csv(OUT / "specmix_staff_side.csv")
    cov = D20.groupby(["policy", "mode", "b", "lag"]).coverage.mean().unstack("policy")
    ratio = (cov["MR"] / cov["SR"]).describe(); ratio_t = (cov["Thr"] / cov["SR"]).describe()
    pd.set_option("display.width", 220)
    print(means.round(4).to_string(index=False))
    print(C.round(3).to_string(index=False))
    print(P.round(3).to_string(index=False))
    print(side.round(2).to_string())
    print("coverage ratio MR/SR", ratio.round(3).to_dict()); print("coverage ratio Thr/SR", ratio_t.round(3).to_dict())


if __name__ == "__main__":
    main()
