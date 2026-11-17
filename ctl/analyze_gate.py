"""Selection value of the availability gate against the random admission curve (IJSR revision, 17 November 2026).
Curve per seed and condition through human transport (coverage 0), matched random at the coverage of staff rollout,
and the random arm at the coverage of omitted support (per-condition mean coverages, per-seed J), linear between
neighbouring points. S_P = R(cov_P) - J_P for the gate and, on the same three-point curve, for staff rollout.
Reads analysis_human/human_side_runs.csv.gz, analysis_frontvol/frontvol_seed_condition.csv and
analysis_omitvol/omitvol_coverage.csv; writes analysis_human/gate_selection.csv."""
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
ROOT = Path(__file__).resolve().parents[1]
k = ["seed", "mode", "b", "lag"]
D = pd.read_csv(ROOT / "analysis_human" / "human_side_runs.csv.gz")
J = D.pivot_table(index=k, columns="policy", values="J")
cov = D.groupby(["mode", "b", "lag", "policy"]).coverage.mean().unstack("policy")
F = pd.read_csv(ROOT / "analysis_frontvol" / "frontvol_seed_condition.csv").rename(columns={"background_fraction": "b", "information_lag": "lag"}).set_index(k)
O = pd.read_csv(ROOT / "analysis_omitvol" / "omitvol_coverage.csv").rename(columns={"background_fraction": "b", "information_lag": "lag"}).set_index(["mode", "b", "lag"])
rows = []
for idx, j in J.iterrows():
    c = cov.loc[idx[1:]]
    xs = [0.0, c["matched_random"], O.loc[idx[1:], "r2omit"]]
    ys = [j["human_only"], F.loc[idx, "J_rand"], F.loc[idx, "J_r2omit"]]
    order = np.argsort(xs); xs = np.array(xs)[order]; ys = np.array(ys)[order]
    def R(x):
        if x <= xs[1] or xs[2] - xs[1] < 1e-4 * max(xs[2], 1e-9):  # second segment degenerate: extend the first
            return ys[0] + (ys[1] - ys[0]) * x / xs[1]
        return ys[1] + (ys[2] - ys[1]) * (x - xs[1]) / (xs[2] - xs[1])
    rows.append(dict(zip(k, idx), S_gate=R(c["staff_gate"]) - j["staff_gate"], S_sr=R(c["staff_rollout"]) - j["staff_rollout"],
                     V_gate=R(c["staff_rollout"]) - R(c["staff_gate"])))
G = pd.DataFrame(rows)
G["dS"] = G.S_gate - G.S_sr
out = []
for sub, m in [("all", G.index == G.index), ("mobile", G["mode"] == "mobile"), ("mixed", G["mode"] == "mixed"),
               ("local", G["mode"] == "local"), ("b=0.8", G.b == 0.8), ("current reports", G.lag == 0)]:
    for var in ("S_gate", "S_sr", "dS", "V_gate"):
        d = G[m].groupby("seed")[var].mean(); n = len(d); h = stats.t.ppf(.975, n - 1) * d.std(ddof=1) / np.sqrt(n)
        out.append(dict(subset=sub, quantity=var, mean=d.mean(), lo=d.mean() - h, hi=d.mean() + h, seeds_positive=int((d > 0).sum())))
out = pd.DataFrame(out); out.to_csv(ROOT / "analysis_human" / "gate_selection.csv", index=False)
print(out.round(3).to_string(index=False))
