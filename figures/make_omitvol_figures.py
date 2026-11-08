"""Figures from the omitvol phase: three-term decomposition and mission profile.
Usage: python make_omitvol_figures.py ANALYSIS_OMITVOL_DIR OUTPUT_DIR
"""
import sys
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

src, out = Path(sys.argv[1]), Path(sys.argv[2])
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "savefig.bbox": "tight"})
BLUE, LBLUE, RED, LRED, GREY = "#1f4e79", "#9dc3e6", "#c0504d", "#f4b6b4", "#7f7f7f"

# ---- three-term decomposition ----
c = pd.read_csv(src / "omitvol_contrasts.csv")
order = ["all", "mobile", "mixed", "local", "b=0", "b=0.4", "b=0.8", "lag=0", "lag=10"]
labels = ["All", "Mobile", "Mixed", "Local", "b = 0", "b = 0.4", "b = 0.8", "Current\nreports", "10 min\ndelay"]
get = lambda q: c[c.quantity == q].set_index("subset").loc[order]
V, So, S, B = get("Vstar"), get("S_omit"), get("S"), get("B")
fig, ax = plt.subplots(figsize=(6.4, 2.7))
x = list(range(len(order))); w = 0.26
err = lambda d: [d["mean"] - d["lo"], d["hi"] - d["mean"]]
ax.bar([i - w for i in x], V["mean"], w, color=GREY, label=r"Pure volume $V^\ast$", yerr=err(V), capsize=1.5, error_kw={"lw": .7})
ax.bar(x, -So["mean"], w, color=LRED, label=r"Selection of omitted support, $-S_{\mathrm{omit}}$",
       yerr=[So["hi"] - So["mean"], So["mean"] - So["lo"]], capsize=1.5, error_kw={"lw": .7})
ax.bar([i + w for i in x], S["mean"], w, color=BLUE, label=r"Selection of staff rollout, $S$", yerr=err(S), capsize=1.5, error_kw={"lw": .7})
ax.scatter(x, B["mean"], marker="D", color=RED, zorder=3, s=14, label=r"Benefit $B=V^\ast-S_{\mathrm{omit}}+S$")
ax.axhline(0, color="black", lw=.6)
for xs in (3.5, 6.5):
    ax.axvline(xs, color="#cccccc", lw=.6, ls=":")
ax.set_xticks(x, labels); ax.set_ylabel("Weighted minutes per request")
ax.set_ylim(-0.45, 0.72)
ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=7)
fig.savefig(out / "fig_decomposition.pdf"); plt.close(fig)

# ---- mission profile ----
p = pd.read_csv(src / "missions_profile.csv")
pols = [("staff_rollout", "Staff rollout", BLUE), ("matched_random", "Random, rollout coverage", LBLUE),
        ("no_support_forecast", "Omitted support", RED), ("r2omit", "Random, omitted coverage", LRED)]
subs = [("mobile", "Mobile"), ("mixed", "Mixed"), ("local", "Local")]
panels = [("specimen_share", "Specimens among\nrobot missions (%)", 100), ("robot_minutes", "Robot route\n(min)", 1),
          ("queue_at_decision", "Human queue at\nadmission (jobs)", 1), ("late_share", "Late robot\nmissions (%)", 100)]
fig, axes = plt.subplots(1, 4, figsize=(7.0, 2.3))
w = 0.2
for ax, (col, title, k) in zip(axes, panels):
    for j, (pol, lab, colr) in enumerate(pols):
        vals = [p[(p.subset == s) & (p.policy == pol)][col].iloc[0] * k for s, _ in subs]
        ax.bar([i + (j - 1.5) * w for i in range(3)], vals, w, color=colr, label=lab)
    ax.set_xticks(range(3), [l for _, l in subs]); ax.set_title(title, fontsize=8)
    if col == "robot_minutes":
        ax.set_ylim(8, 12.5)
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=4, frameon=False, fontsize=7, bbox_to_anchor=(0.5, -0.07))
fig.tight_layout(rect=(0, 0.08, 1, 1))
fig.savefig(out / "fig_mission_profile.pdf"); plt.close(fig)
print("ok")
