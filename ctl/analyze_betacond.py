"""Coverage adjustment with a slope per condition (no new runs).

In every condition c, the random arms at the coverage of staff rollout (matched_random, results/controls) and of
omitted support (r2omit, results/omitvol) give beta_c = [mean J(r2omit) - mean J(rand)] / [mean cov(r2omit) - mean cov(rand)].
Per seed and condition:
  S_adj     = S     - beta_c * (cov_rand,c  - cov_staff,c)
  Somit_adj = Somit - beta_c * (cov_r2omit,c - cov_omit,c)
  Vstar_adj = Vstar - beta_c * [(cov_r2omit,c - cov_omit,c) - (cov_rand,c - cov_staff,c)]
with condition mean coverages. Outputs analysis_omitvol/betacond_*.csv.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_omitvol"
COND = ["mode", "background_fraction", "information_lag"]


def tci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x))
    h = stats.t.ppf(.975, len(x) - 1) * se
    return m, m - h, m + h


def load(folder, pattern, name):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append(dict(mode=w["mode"], background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                         seed=int(f.stem.split("__")[-1]), policy=name, J=r["weighted_tardiness_per_request"], cov=r["robot_coverage"]))
    return pd.DataFrame(rows)


main = pd.read_csv(ROOT / "main_runs_subset.csv")
main = main[main.policy.isin(["staff_rollout", "no_support_forecast"])]
main = main.rename(columns={"weighted_tardiness_per_request": "J", "robot_coverage": "cov"})[COND + ["seed", "policy", "J", "cov"]]
d = pd.concat([main, load(ROOT / "results" / "controls", "*__matched_random__*.json", "rand"),
               load(ROOT / "results" / "omitvol", "r2omit__*.json", "r2omit")], ignore_index=True)
J = d.pivot_table(index=["seed"] + COND, columns="policy", values="J").reset_index()
cm = d.groupby(COND + ["policy"])["cov"].mean().unstack()
jm = d.groupby(COND + ["policy"]).J.mean().unstack()
beta = (jm.r2omit - jm.rand) / ((cm.r2omit - cm.rand) * 100)  # per percentage point
cond = pd.DataFrame(dict(beta=beta, cov_staff=cm.staff_rollout * 100, cov_rand=cm.rand * 100,
                         cov_omit=cm.no_support_forecast * 100, cov_r2omit=cm.r2omit * 100))
J = J.merge(cond.reset_index(), on=COND)
J["S"] = J.rand - J.staff_rollout
J["Somit"] = J.r2omit - J.no_support_forecast
J["Vstar"] = J.r2omit - J.rand
J["S_adj"] = J.S - J.beta * (J.cov_rand - J.cov_staff)
J["Somit_adj"] = J.Somit - J.beta * (J.cov_r2omit - J.cov_omit)
J["Vstar_adj"] = J.Vstar - J.beta * ((J.cov_r2omit - J.cov_omit) - (J.cov_rand - J.cov_staff))
G = 0.215
J["S_adjG"] = J.S - G * (J.cov_rand - J.cov_staff)

subsets = {"all": J.index == J.index}
for m in ("mobile", "mixed", "local"):
    subsets[m] = J["mode"] == m
for b in (0.0, 0.4, 0.8):
    subsets[f"b={b:g}"] = J.background_fraction == b
for lag in (0, 10):
    subsets[f"lag={lag}"] = J.information_lag == lag
rows = []
for name, mask in subsets.items():
    sub = J[mask].groupby("seed")[["S", "S_adj", "S_adjG", "Somit", "Somit_adj", "Vstar", "Vstar_adj"]].mean()
    row = dict(subset=name)
    for col in sub.columns:
        m, lo, hi = tci(sub[col]); row.update({col: m, col + "_lo": lo, col + "_hi": hi})
    rows.append(row)
summary = pd.DataFrame(rows)
summary.to_csv(OUT / "betacond_summary.csv", index=False)
percell = J.groupby(COND)[["S", "S_adj", "Somit", "Somit_adj", "beta", "cov_staff", "cov_rand", "cov_omit", "cov_r2omit"]].mean()
percell.to_csv(OUT / "betacond_cells.csv")
pd.set_option("display.width", 200)
print(cond.round(3))
print(summary[["subset", "S", "S_adj", "S_adj_lo", "S_adj_hi", "S_adjG", "Somit_adj", "Somit_adj_lo", "Somit_adj_hi", "Vstar_adj", "Vstar_adj_lo", "Vstar_adj_hi"]].round(3).to_string())
print(percell.round(3).to_string())
