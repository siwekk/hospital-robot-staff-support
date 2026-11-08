"""Paired analysis of the equal staff budget variant. Outputs ../analysis_budget."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_budget"; OUT.mkdir(exist_ok=True)
KEYS = ["weighted_tardiness_per_request", "robot_coverage", "net_released_minutes", "late_fraction"]


def load(folder):
    rows = []
    for f in sorted(Path(folder).glob("*.json")):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append(dict(seed=int(f.stem.split("__")[-1]), mode=w["mode"], k=w["k"], b=w["background_fraction"],
                         lag=w["information_lag"], policy=r["policy"], **{k: r[k] for k in KEYS}))
    return pd.DataFrame(rows)


d = pd.concat([load(ROOT / "results" / "budget_main"), load(ROOT / "results" / "budget_random")], ignore_index=True)
d["J"] = d.weighted_tardiness_per_request
seeds = sorted(d.seed.unique())
full = pd.read_csv(ROOT / "main_runs_subset.csv")
full = full[(full.policy == "human_only") & (full["mode"] == "mobile") & full.seed.isin(seeds)]
full = full.rename(columns={"background_fraction": "b", "information_lag": "lag"})[["seed", "b", "lag", "weighted_tardiness_per_request"]]
full = full.rename(columns={"weighted_tardiness_per_request": "J_full"})
piv = d.pivot_table(index=["seed", "mode", "k", "b", "lag"], columns="policy", values="J").reset_index()
cov = d.pivot_table(index=["seed", "mode", "k", "b", "lag"], columns="policy", values="robot_coverage").reset_index()
rel = d.pivot_table(index=["seed", "mode", "k", "b", "lag"], columns="policy", values="net_released_minutes").reset_index()
piv = piv.merge(full, on=["seed", "b", "lag"], how="left")
piv["S"] = piv.matched_random - piv.staff_rollout
piv["B"] = piv.no_support_forecast - piv.staff_rollout
piv["V"] = piv.no_support_forecast - piv.matched_random
piv["roll_vs_human"] = piv.staff_rollout - piv.human_only
piv["roll_vs_full"] = piv.staff_rollout - piv.J_full
piv["cap_cost"] = piv.human_only - piv.J_full


def ci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x)); t = stats.t.ppf(.975, len(x) - 1)
    return m, m - t * se, m + t * se, 2 * stats.t.sf(abs(m / se), len(x) - 1) if se > 0 else np.nan


rows = []
def block(label, g, c, r):
    row = dict(subset=label, n_seeds=g.seed.nunique())
    for col in ("S", "B", "V", "roll_vs_human", "roll_vs_full", "cap_cost"):
        m, lo, hi, p = ci(g.groupby("seed")[col].mean()); row.update({col: m, col + "_lo": lo, col + "_hi": hi, col + "_p": p})
    for pol in ("human_only", "staff_rollout", "no_support_forecast", "matched_random"):
        row["J_" + pol] = g[pol].mean()
    row["J_human_full"] = g.J_full.mean()
    row["cov_rollout"] = c.staff_rollout.mean(); row["cov_omitted"] = c.no_support_forecast.mean(); row["cov_random"] = c.matched_random.mean()
    row["released_rollout_per_day"] = r.staff_rollout.mean() / 7
    rows.append(row)

for (mode, k), g in piv.groupby(["mode", "k"]):
    c = cov[(cov["mode"] == mode) & (cov.k == k)]; r = rel[(rel["mode"] == mode) & (rel.k == k)]
    block(f"{mode} k={k} all", g, c, r)
    for b in (0.4, 0.8):
        block(f"{mode} k={k} b={b}", g[g.b == b], c[c.b == b], r[r.b == b])
    for lag in (0, 10):
        block(f"{mode} k={k} lag={lag}", g[g.lag == lag], c[c.lag == lag], r[r.lag == lag])
S = pd.DataFrame(rows); S.to_csv(OUT / "budget_summary.csv", index=False)
cond = piv.groupby(["mode", "k", "b", "lag"]).agg(S=("S", "mean"), B=("B", "mean"), V=("V", "mean"), human=("human_only", "mean"),
                                                  rollout=("staff_rollout", "mean"), random=("matched_random", "mean"),
                                                  omitted=("no_support_forecast", "mean"), human_full=("J_full", "mean")).reset_index()
cond.to_csv(OUT / "budget_conditions.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
show = ["subset", "n_seeds", "S", "S_lo", "S_hi", "B", "V", "roll_vs_human", "roll_vs_full", "cap_cost", "cov_rollout", "cov_random", "cov_omitted"]
print(S[show].round(4).to_string(index=False))
print(cond.round(3).to_string(index=False))
