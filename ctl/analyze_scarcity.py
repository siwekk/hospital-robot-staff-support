"""Analysis of the scarcity and unattended receiving phases (design_scarcity*.json)."""
import json
from pathlib import Path

import numpy as np, pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_scarcity"; OUT.mkdir(exist_ok=True)
SEEDS = list(range(103000, 103012))
COND = ["mode", "background_fraction", "information_lag"]
POL = {"human_only": "human", "staff_rollout": "rollout", "no_support_forecast": "omitted", "matched_random": "random"}


def load(folder, pattern, scenario):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append(dict(scenario=scenario, seed=int(f.stem.split("__")[-1]), policy=POL[r["policy"]], mode=w["mode"],
                         background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                         J=r["weighted_tardiness_per_request"], coverage=r["robot_coverage"], late=r["late_fraction"],
                         released=r["net_released_minutes"] / 7, utilization=r.get("human_utilization")))
    return pd.DataFrame(rows)


def ci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x)); t = stats.t.ppf(.975, len(x) - 1)
    return dict(mean=m, lo=m - t * se, hi=m + t * se, seeds_positive=int((x > 0).sum()), n_seeds=len(x))


def contrasts(d, label):
    cell = d.pivot_table(index=["seed"] + COND, columns="policy", values="J").dropna()
    n = cell.groupby("seed").size()
    if len(n) != len(SEEDS) or (n != 8).any():
        raise RuntimeError(f"{label}: incomplete cells {n.to_dict()}")
    P = cell.groupby("seed").mean()
    return [dict(subset=label, contrast=k, **ci(v)) for k, v in (
        ("rollout - human", P.rollout - P.human), ("random - human", P.random - P.human),
        ("B = omitted - rollout", P.omitted - P.rollout), ("V = omitted - random", P.omitted - P.random),
        ("S = random - rollout", P.random - P.rollout))]


def main():
    main_runs = pd.read_csv(ROOT / "main_runs_subset.csv")
    main_runs = main_runs[main_runs.policy.isin(["human_only", "staff_rollout", "no_support_forecast"])]
    base = pd.DataFrame(dict(scenario="baseline", seed=main_runs.seed, policy=main_runs.policy.map(POL), mode=main_runs["mode"],
                             background_fraction=main_runs.background_fraction, information_lag=main_runs.information_lag,
                             J=main_runs.weighted_tardiness_per_request, coverage=main_runs.robot_coverage,
                             late=main_runs.late_fraction, released=main_runs.net_released_minutes / 7, utilization=np.nan))
    data = [base, load(ROOT / "results" / "controls", "*__matched_random__*.json", "baseline")]
    for tag in ("roster85", "roster70", "unattended"):
        data.append(load(ROOT / "results" / "scarcity", f"{tag}__*.json", tag))
    df = pd.concat(data, ignore_index=True)
    df = df[df.seed.isin(SEEDS) & df["mode"].isin(["mobile", "local"]) & df.background_fraction.isin([.4, .8])]
    rows = []
    for scen, d in df.groupby("scenario", sort=False):
        rows += contrasts(d, scen)
        for (mode, b), g in d.groupby(["mode", "background_fraction"]):
            cell = g.pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()
            for k, v in (("rollout - human", cell.rollout - cell.human), ("S = random - rollout", cell.random - cell.rollout)):
                rows.append(dict(subset=f"{scen} | {mode} b={b}", contrast=k, **ci(v)))
    T = pd.DataFrame(rows)
    means = df.groupby(["scenario", "policy"])[["J", "late", "coverage", "released", "utilization"]].mean().reset_index()
    cells = df.groupby(["scenario", "policy"] + COND)[["J", "coverage", "released", "utilization"]].mean().reset_index()
    T.to_csv(OUT / "scarcity_contrasts.csv", index=False); means.to_csv(OUT / "scarcity_means.csv", index=False)
    cells.to_csv(OUT / "scarcity_cells.csv", index=False)
    pd.set_option("display.width", 240); pd.set_option("display.max_rows", 500)
    print(means.round(4).to_string(index=False)); print(T.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
