"""Analysis of the demand, night and multi-load phases (design_levers*.json)."""
import json
from pathlib import Path

import numpy as np, pandas as pd

from analyze_scarcity import ci, contrasts, COND, POL, SEEDS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_levers"; OUT.mkdir(exist_ok=True)
TAGS = ["demand110", "demand120", "night", "night4", "night4_allday", "cap3", "cap3_hold10", "favorable"]


def load(folder, pattern, scenario):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append(dict(scenario=scenario, seed=int(f.stem.split("__")[-1]), policy=POL[r["policy"]], mode=w["mode"],
                         background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                         J=r["weighted_tardiness_per_request"], coverage=r["robot_coverage"], late=r["late_fraction"],
                         released=r["net_released_minutes"] / 7, utilization=r.get("human_utilization"),
                         created=r["created"] / 7, joined=r.get("joined_requests", 0) / 7,
                         tour_size=r.get("mean_tour_size", np.nan) if r.get("tours") else np.nan))
    return pd.DataFrame(rows)


def main():
    main_runs = pd.read_csv(ROOT / "main_runs_subset.csv")
    main_runs = main_runs[main_runs.policy.isin(["human_only", "staff_rollout", "no_support_forecast"])]
    base = pd.DataFrame(dict(scenario="baseline", seed=main_runs.seed, policy=main_runs.policy.map(POL), mode=main_runs["mode"],
                             background_fraction=main_runs.background_fraction, information_lag=main_runs.information_lag,
                             J=main_runs.weighted_tardiness_per_request, coverage=main_runs.robot_coverage,
                             late=main_runs.late_fraction, released=main_runs.net_released_minutes / 7, utilization=np.nan,
                             created=np.nan, joined=0.0, tour_size=np.nan))
    data = [base, load(ROOT / "results" / "controls", "*__matched_random__*.json", "baseline")]
    for tag in TAGS:
        data.append(load(ROOT / "results" / "levers", f"{tag}__*.json", tag))
    df = pd.concat(data, ignore_index=True)
    df = df[df.seed.isin(SEEDS) & df["mode"].isin(["mobile", "local"]) & df.background_fraction.isin([.4, .8])]
    rows = []
    for scen, d in df.groupby("scenario", sort=False):
        rows += contrasts(d, scen)
        for (mode, b), g in d.groupby(["mode", "background_fraction"]):
            cell = g.pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()
            for k, v in (("rollout - human", cell.rollout - cell.human), ("S = random - rollout", cell.random - cell.rollout),
                         ("omitted - human", cell.omitted - cell.human)):
                rows.append(dict(subset=f"{scen} | {mode} b={b}", contrast=k, **ci(v)))
        for mode, g in d.groupby("mode"):
            cell = g.pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()
            rows.append(dict(subset=f"{scen} | {mode}", contrast="rollout - human", **ci(cell.rollout - cell.human)))
    # rollout in a scenario against rollout of the baseline (same demand and roster only)
    b = df[(df.scenario == "baseline") & (df.policy == "rollout")].groupby("seed").J.mean()
    for tag in ("night", "cap3", "cap3_hold10"):
        s = df[(df.scenario == tag) & (df.policy == "rollout")].groupby("seed").J.mean()
        rows.append(dict(subset=tag, contrast="rollout - baseline rollout", **ci((s - b).dropna())))
    T = pd.DataFrame(rows)
    means = df.groupby(["scenario", "policy"])[["J", "late", "coverage", "released", "utilization", "created", "joined", "tour_size"]].mean().reset_index()
    cells = df.groupby(["scenario", "policy"] + COND)[["J", "coverage", "released", "utilization", "joined"]].mean().reset_index()
    T.to_csv(OUT / "levers_contrasts.csv", index=False); means.to_csv(OUT / "levers_means.csv", index=False)
    cells.to_csv(OUT / "levers_cells.csv", index=False)
    pd.set_option("display.width", 240); pd.set_option("display.max_rows", 800)
    print(means.round(4).to_string(index=False)); print(T.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
