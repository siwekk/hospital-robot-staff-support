"""Paired analysis of control arms against the existing 1800 main runs (same seeds)."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["seed", "mode", "background_fraction", "information_lag", "policy", "created", "robot_completed",
        "late_fraction", "weighted_tardiness_per_request", "robot_coverage", "net_released_minutes",
        "human_transport_minutes", "total_staff_work_minutes"]
old = pd.read_csv(ROOT / "main_runs_subset.csv")
rows = []
for f in sorted(list((ROOT / "results" / "controls").glob("*.json")) + list((ROOT / "results" / "controls2").glob("*.json"))):
    r = json.loads(f.read_text())
    w = r["workflow"]
    rows.append({k: r.get(k) for k in KEYS if k not in ("mode", "background_fraction", "information_lag")}
                | {"mode": w["mode"], "background_fraction": w["background_fraction"],
                   "information_lag": w["information_lag"], "seed": int(f.stem.split("__")[-1])})
new = pd.DataFrame(rows)[KEYS]
d = pd.concat([old[KEYS], new], ignore_index=True)
d["J"] = d["weighted_tardiness_per_request"]
cond = ["mode", "background_fraction", "information_lag"]
piv = d.pivot_table(index=["seed"] + cond, columns="policy", values="J")
seedmean = piv.groupby("seed").mean()
n = len(seedmean)

def contrast(a, b):
    x = (seedmean[a] - seedmean[b]).dropna()
    m, se = x.mean(), x.std(ddof=1) / np.sqrt(len(x))
    t = stats.t.ppf(.975, len(x) - 1)
    p = 2 * stats.t.sf(abs(m / se), len(x) - 1)
    return dict(contrast=f"{a} - {b}", n_seeds=len(x), mean=m, lo=m - t * se, hi=m + t * se, p=p,
                seeds_favoring_first=int((x < 0).sum()))

pairs = [("staff_rollout", "matched_random"), ("staff_rollout", "idle_pair_rule"),
         ("no_support_forecast", "matched_random"), ("matched_random", "human_only"),
         ("idle_pair_rule", "human_only"), ("optimizer", "idle_pair_rule"), ("own_completion", "matched_random")]
HAS2 = "idle_surplus_rule" in piv.columns
if HAS2:
    pairs += [("idle_surplus_rule", "human_only"), ("staff_rollout", "idle_surplus_rule"),
              ("idle_surplus_rule", "matched_random")]
out = pd.DataFrame([contrast(a, b) for a, b in pairs])
primary = out.iloc[:2].p.values
order = np.argsort(primary)
adj = np.empty(2)
run = 0
for rank, i in enumerate(order):
    run = max(run, (2 - rank) * primary[i]); adj[i] = min(1, run)
out["holm_p_two_primary"] = list(adj) + [np.nan] * (len(out) - 2)
pd.set_option("display.width", 200)
print(out.round(6).to_string(index=False))

agg = d.groupby("policy").agg(J=("J", "mean"), coverage=("robot_coverage", "mean"), late=("late_fraction", "mean"),
                              released=("net_released_minutes", "mean"), human_min=("human_transport_minutes", "mean"))
agg["released_pct"] = 100 * agg["released"] / agg["human_min"]
print(agg.round(5).to_string())

cell = d.groupby(cond + ["policy"]).agg(J=("J", "mean"), cov=("robot_coverage", "mean")).unstack("policy")
cell.round(4).to_csv(ROOT / "controls_cell_means.csv")
# coverage matching check
for pol in ("matched_random", "idle_pair_rule") + (("idle_surplus_rule",) if HAS2 else ()):
    ratio = (cell["cov"][pol] / cell["cov"]["staff_rollout"]).replace([np.inf], np.nan)
    print(pol, "coverage ratio vs staff_rollout: median %.2f, min %.2f, max %.2f" % (ratio.median(), ratio.min(), ratio.max()))

# coverage adjusted comparison: pooled regression of J - J_human on coverage over robot policies
rel = cell["J"].sub(cell["J"]["human_only"], axis=0)
rows = []
for pol in ("no_support_forecast", "staff_rollout", "own_completion", "optimizer", "matched_random", "idle_pair_rule") + (("idle_surplus_rule",) if HAS2 else ()):
    for idx in cell.index:
        rows.append((pol, idx, cell["cov"][pol][idx], rel[pol][idx]))
reg = pd.DataFrame(rows, columns=["policy", "cell", "cov", "dJ"])
slope, icpt = np.polyfit(reg["cov"], reg["dJ"], 1)
reg["resid"] = reg["dJ"] - (icpt + slope * reg["cov"])
print("pooled slope dJ per unit coverage %.2f, intercept %.4f, r=%.3f" % (slope, icpt, np.corrcoef(reg["cov"], reg["dJ"])[0, 1]))
print(reg.groupby("policy")["resid"].agg(["mean", "std"]).round(4).to_string())

# condition level contrast rollout - random
cc = (piv["staff_rollout"] - piv["matched_random"]).groupby(cond).agg(["mean", "std"])
cc["se"] = cc["std"] / np.sqrt(n)
cc.round(4).to_csv(ROOT / "controls_condition_contrast.csv")
print(cc.round(3).to_string())
out.to_csv(ROOT / "controls_paired_contrasts.csv", index=False)
agg.to_csv(ROOT / "controls_policy_means.csv")
