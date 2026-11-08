"""Figures for the revised manuscript. Reads results/ and main_runs_subset.csv, writes ../paper_figures."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper_figures"; OUT.mkdir(exist_ok=True)
KEYS = ["seed", "mode", "background_fraction", "information_lag", "policy", "weighted_tardiness_per_request",
        "robot_coverage", "net_released_minutes"]
COND = ["mode", "background_fraction", "information_lag"]
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})


def load(folder, extra=()):
    rows = []
    for f in sorted(Path(folder).glob("*.json")):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append({k: r[k] for k in KEYS if k not in COND + ["seed"]}
                    | {"mode": w["mode"], "background_fraction": w["background_fraction"],
                       "information_lag": w["information_lag"], "seed": int(f.stem.split("__")[-1])}
                    | {k: w.get(k) for k in extra})
    return pd.DataFrame(rows)


main = pd.read_csv(ROOT / "main_runs_subset.csv")[KEYS]
ctl = load(ROOT / "results" / "controls")
base = pd.concat([main, ctl[KEYS]], ignore_index=True)
base["J"] = base["weighted_tardiness_per_request"]
piv = base.pivot_table(index=["seed"] + COND, columns="policy", values="J")


def tci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x))
    t = stats.t.ppf(.975, len(x) - 1); return m, m - t * se, m + t * se


# ---- Figure 1: selection value by condition (staff rollout minus matched random) ----
fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.5), sharey=True)
titles = {"mobile": "Mobile support", "mixed": "Mixed support", "local": "Local support"}
colors = {0: "#1f4e79", 10: "#c0504d"}
for ax, mode in zip(axes, ["mobile", "mixed", "local"]):
    for lag, dx in ((0, -0.03), (10, 0.03)):
        xs, ms, los, his = [], [], [], []
        for b in (0.0, 0.4, 0.8):
            g = piv.xs((mode, b, lag), level=COND)
            m, lo, hi = tci(g["matched_random"] - g["staff_rollout"])
            xs.append(b + dx); ms.append(m); los.append(m - lo); his.append(hi - m)
        ax.errorbar(xs, ms, yerr=[los, his], fmt="o", ms=4, capsize=2, color=colors[lag],
                    label=f"{'Current reports' if lag == 0 else 'Ten minute delay'}")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xticks([0, 0.4, 0.8]); ax.set_title(titles[mode]); ax.set_xlabel("Nominal unavailable fraction")
axes[0].set_ylabel("Selection value S, weighted minutes\nper request (positive favors rollout)")
axes[0].legend(frameon=False, fontsize=7, loc="upper left")
fig.tight_layout(); fig.savefig(OUT / "selection_by_condition.pdf"); plt.close(fig)

# ---- Figure 2: front of J versus released staff time ----
phi = load(ROOT / "results" / "phi_main", extra=("phi",))
seeds = sorted(phi.seed.unique())
ref = base[base.seed.isin(seeds)]
fig, axes = plt.subplots(1, 3, figsize=(6.8, 2.6))
for ax, b in zip(axes, [0.0, 0.4, 0.8]):
    for fam, pol_ref, pol_phi, mk, col, lab in (
            ("aware", "staff_rollout", "staff_phi", "o", "#1f4e79", "Staff aware forecast"),
            ("omitted", "no_support_forecast", "omitted_phi", "s", "#c0504d", "Support omitted from forecast")):
        r0 = ref[(ref.policy == pol_ref) & (ref.background_fraction == b)]
        pts = [(r0.net_released_minutes.mean() / 7, r0.J.mean())]
        for p, g in phi[(phi.policy == pol_phi) & (phi.background_fraction == b)].groupby("phi"):
            pts.append((g.net_released_minutes.mean() / 7, (g.weighted_tardiness_per_request).mean()))
        pts.sort()
        ax.plot(*zip(*pts), mk + "-", color=col, ms=4, lw=1, label=lab)
    for pol, mk, lab in (("human_only", "^", "Human transport"), ("matched_random", "x", "Matched random")):
        r0 = ref[(ref.policy == pol) & (ref.background_fraction == b)]
        ax.plot(r0.net_released_minutes.mean() / 7, r0.J.mean(), mk, color="k", ms=5, label=lab)
    ax.set_title(f"Unavailable fraction {b:g}"); ax.set_xlabel("Net staff minutes released per day")
axes[0].set_ylabel("Weighted tardiness per request")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=4, frameon=False, fontsize=7)
fig.tight_layout(rect=(0, 0.1, 1, 1)); fig.savefig(OUT / "front_staff_time.pdf"); plt.close(fig)
print("ok")
