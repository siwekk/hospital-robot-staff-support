"""Figures after the frontvol phase: staff time front with the random admission curve, and mission profile with
the threshold rule. Usage: python make_round2_figures.py STUDY_CONTROLS_DIR OUTPUT_DIR
"""
import sys
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root, out = Path(sys.argv[1]), Path(sys.argv[2])
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "savefig.bbox": "tight"})
BLUE, LBLUE, RED, LRED, GREY, GREEN = "#1f4e79", "#9dc3e6", "#c0504d", "#f4b6b4", "#7f7f7f", "#548235"

# ---- front: J against released staff time, by unavailable fraction ----
m = pd.read_csv(root / "analysis_frontvol" / "frontvol_means_by_b.csv")
fams = [("Staff rollout family", ["staff_rollout", "staff_phi3", "staff_phi10"], "o-", BLUE),
        ("Omitted support family", ["quota", "no_support_forecast", "omitted_phi3", "omitted_phi10"], "s-", RED),
        ("Random admission", ["human_only", "rand", "rf_staff3", "r2omit", "rf_omit3", "rf_staff10", "rf_omit10"], "x--", GREY)]
fig, axes = plt.subplots(1, 3, figsize=(6.8, 2.6))
for ax, b in zip(axes, [0.0, 0.4, 0.8]):
    g = m[m.background_fraction == b].set_index("policy")
    for lab, pols, st, col in fams:
        pts = sorted((g.loc[p, "released"], g.loc[p, "J"]) for p in pols if p in g.index)
        ax.plot(*zip(*pts), st, color=col, ms=3.5, lw=1, label=lab)
    ax.plot(0, g.loc["human_only", "J"], "^", color="k", ms=5, label="Human transport")
    ax.set_title(f"$b$ = {b:g}"); ax.set_xlabel("Net staff minutes released per day")
axes[0].set_ylabel("Weighted tardiness per request")
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=4, frameon=False, fontsize=7)
fig.tight_layout(rect=(0, 0.1, 1, 1)); fig.savefig(out / "front_staff_time.pdf"); plt.close(fig)

# ---- mission profile with the threshold rule ----
q = pd.read_csv(root / "analysis_frontvol" / "quota_mission_profile.csv")
o = pd.read_csv(root / "analysis_omitvol" / "missions_profile.csv")
o = o[o.policy == "r2omit"][["subset", "policy", "specimen_share", "robot_minutes", "queue_at_decision", "late_share"]]
p = pd.concat([q[["subset", "policy", "specimen_share", "robot_minutes", "queue_at_decision", "late_share"]], o])
pols = [("staff_rollout", "Staff rollout", BLUE, "o"), ("matched_random", "Random, rollout coverage", LBLUE, "o"),
        ("quota", "Omitted support, threshold", GREEN, "D"),
        ("no_support_forecast", "Omitted support", RED, "s"), ("r2omit", "Random, omitted coverage", LRED, "s")]
subs = [("mobile", "Mobile"), ("mixed", "Mixed"), ("local", "Local")]
panels = [("specimen_share", "Specimens among\nrobot missions (%)", 100, (0, 100)),
          ("robot_minutes", "Robot route (min)", 1, (9.5, 13.5)),
          ("queue_at_decision", "Human queue at\nadmission (jobs)", 1, (0, 3)),
          ("late_share", "Late robot\nmissions (%)", 100, (0, 100))]
fig, axes = plt.subplots(1, 4, figsize=(7.0, 2.3))
for ax, (col, title, k, ylim) in zip(axes, panels):
    for j, (pol, lab, colr, mk) in enumerate(pols):
        vals = [p[(p.subset == s) & (p.policy == pol)][col].iloc[0] * k for s, _ in subs]
        ax.plot([i + (j - 2) * 0.13 for i in range(3)], vals, mk, color=colr, ms=4, label=lab, ls="none")
    ax.set_xticks(range(3), [l for _, l in subs]); ax.set_title(title, fontsize=8); ax.set_ylim(*ylim)
    ax.set_xlim(-0.5, 2.5)
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=3, frameon=False, fontsize=7, bbox_to_anchor=(0.5, -0.1))
fig.tight_layout(rect=(0, 0.12, 1, 1))
fig.savefig(out / "fig_mission_profile.pdf"); plt.close(fig)
# ---- decomposition with the random admission curve and the equal coverage comparison ----
c = pd.read_csv(root / "analysis_frontvol" / "frontvol_contrasts.csv")
order = ["all", "mobile", "mixed", "local", "b=0", "b=0.4", "b=0.8", "lag=0", "lag=10"]
labels = ["All", "Mobile", "Mixed", "Local", "b = 0", "b = 0.4", "b = 0.8", "Current\nreports", "10 min\ndelay"]
get = lambda q: c[c.metric == q].set_index("subset").loc[order]
V, So, S, B, Q = get("Vstar_curve"), get("S_no_support_forecast"), get("S_staff_rollout"), get("B"), get("quota_minus_SR")
fig, ax = plt.subplots(figsize=(6.6, 2.8))
x = list(range(len(order))); w = 0.2
err = lambda d: [d["mean"] - d["lo"], d["hi"] - d["mean"]]
kw = dict(capsize=1.5, error_kw={"lw": .7})
ax.bar([i - 1.5 * w for i in x], V["mean"], w, color=GREY, label=r"Pure volume $V^\ast$", yerr=err(V), **kw)
ax.bar([i - 0.5 * w for i in x], -So["mean"], w, color=LRED, label=r"$-S_{\mathrm{omit}}$ (omitted support vs random, own coverage)",
       yerr=[So["hi"] - So["mean"], So["mean"] - So["lo"]], **kw)
ax.bar([i + 0.5 * w for i in x], S["mean"], w, color=BLUE, label=r"$S$ (staff rollout vs random)", yerr=err(S), **kw)
ax.bar([i + 1.5 * w for i in x], Q["mean"], w, color=GREEN, label="Threshold rule minus staff rollout (equal coverage)", yerr=err(Q), **kw)
ax.scatter(x, B["mean"], marker="D", color=RED, zorder=3, s=14, label=r"Benefit $B$")
ax.axhline(0, color="black", lw=.6)
for xs in (3.5, 6.5):
    ax.axvline(xs, color="#cccccc", lw=.6, ls=":")
ax.set_xticks(x, labels); ax.set_ylabel("Weighted minutes per request")
ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=7)
fig.savefig(out / "fig_decomposition.pdf"); plt.close(fig)
print("ok")
