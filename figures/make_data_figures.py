"""Proposed extra figures for the JIRS manuscript, built only from numbers in its tables."""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)

BLUE, RED, GREY = "#1f4e79", "#c0504d", "#7f7f7f"
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "pdf.fonttype": 42, "savefig.bbox": "tight"})

# ---- 1. Forest plot: staff rollout minus human transport (Tables 7 and 8) ----
rows = [  # label, mean, lo, hi, group
    ("Baseline (62 transporters)", 0.191, 0.151, 0.230, "Staffing"),
    ("53 transporters", 0.274, 0.231, 0.316, "Staffing"),
    ("44 transporters", 0.455, 0.355, 0.556, "Staffing"),
    ("Equal budget, local, k=3", 0.035, -0.026, 0.096, "Staffing"),
    ("Equal budget, local, k=6", -0.204, -0.470, 0.062, "Staffing"),
    ("Equal budget, mixed, k=3", 0.081, 0.020, 0.141, "Staffing"),
    ("Equal budget, mixed, k=6", 0.309, 0.177, 0.442, "Staffing"),
    ("Four robots", 0.407, 0.290, 0.524, "Robot"),
    ("Eight robots", 0.732, 0.604, 0.861, "Robot"),
    ("Robot at 72 m/min", 0.303, 0.222, 0.384, "Robot"),
    ("Support ×0.5", 0.239, 0.147, 0.332, "Robot"),
    ("Support ×1.5", 0.129, 0.050, 0.207, "Robot"),
    ("Unattended receiving", 0.090, 0.053, 0.127, "Operation"),
    ("Demand ×1.1", 0.268, 0.178, 0.359, "Operation"),
    ("Demand ×1.2", 0.597, 0.366, 0.828, "Operation"),
    ("Night only", 0.006, -0.028, 0.040, "Operation"),
    ("Night only, 4 at night", 0.068, 0.041, 0.096, "Operation"),
    ("All hours, 4 at night", 0.261, 0.188, 0.335, "Operation"),
    ("Tours of up to three", 0.410, 0.367, 0.452, "Operation"),
    ("Tours, 10 min wait", 0.431, 0.402, 0.460, "Operation"),
    ("Combined, demand ×1.2", 0.359, 0.122, 0.596, "Operation"),
]
fig, ax = plt.subplots(figsize=(5.2, 5.0))
y, ticks, labels, prev = 0, [], [], None
for lab, m, lo, hi, g in rows:
    if prev is not None and g != prev:
        y += 0.8
    prev = g
    col = RED if lo > 0 else (BLUE if hi < 0 else GREY)
    ax.errorbar(m, -y, xerr=[[m - lo], [hi - m]], fmt="o", color=col, ms=3.5, capsize=2, lw=1)
    ticks.append(-y); labels.append(lab); y += 1
ax.axvline(0, color="black", lw=0.6)
ax.set_yticks(ticks, labels)
ax.set_xlabel("Staff rollout minus human transport\n(weighted tardiness, min per request; >0 favours human transport)")
fig.savefig(out / "fig_scenarios_forest.pdf")
plt.close(fig)

# ---- 2. Decomposition B = V + S (Table 4) ----
sub = ["All", "Mobile", "Mixed", "Local", "b = 0", "b = 0.4", "b = 0.8", "Current\nreports", "10 min\ndelay"]
B = [0.163, 0.238, 0.188, 0.064, 0.041, 0.084, 0.366, 0.273, 0.054]
V = [0.123, 0.253, 0.223, -0.107, 0.004, 0.053, 0.311, 0.215, 0.031]
S = [0.040, -0.015, -0.035, 0.171, 0.037, 0.031, 0.054, 0.058, 0.023]
Slo = [0.014, -0.046, -0.065, 0.120, 0.008, 0.000, 0.002, 0.016, 0.002]
Shi = [0.067, 0.016, -0.004, 0.223, 0.066, 0.062, 0.106, 0.099, 0.044]
fig, ax = plt.subplots(figsize=(6.0, 2.6))
x = range(len(sub)); w = 0.36
ax.bar([i - w / 2 for i in x], V, w, color=GREY, label="Volume V")
ax.bar([i + w / 2 for i in x], S, w, color=BLUE, label="Selection S (95% CI)",
       yerr=[[s - l for s, l in zip(S, Slo)], [h - s for s, h in zip(S, Shi)]], capsize=2, error_kw={"lw": 0.8})
ax.scatter(list(x), B, marker="D", color=RED, zorder=3, s=14, label="Total benefit B")
ax.axhline(0, color="black", lw=0.6)
for xs in (0.5, 3.5, 6.5):
    ax.axvline(xs, color="#cccccc", lw=0.6, ls=":")
ax.set_xticks(list(x), sub)
ax.set_ylabel("Weighted minutes per request")
ax.set_ylim(-0.13, 0.48); ax.legend(frameon=False, ncol=3, loc="upper left")
fig.savefig(out / "fig_decomposition.pdf")
plt.close(fig)

# ---- 3. Gap against coverage (Table 7, sensitivity; 6 seeds) ----
pts = [("Two robots", 1.12, 0.203), ("Four robots", 1.94, 0.407), ("Eight robots", 3.09, 0.732),
       ("Robot at 72 m/min", 1.61, 0.303), ("Support ×0.5", 1.91, 0.239), ("Support ×1.5", 0.64, 0.129)]
fig, ax = plt.subplots(figsize=(3.4, 2.6))
for lab, c, g in pts:
    col = BLUE if "Support" not in lab else RED
    ax.scatter(c, g, color=col, s=16, zorder=3)
    ax.annotate(lab, (c, g), xytext=(4, -3), textcoords="offset points", fontsize=7)
ax.set_xlim(0, 3.9); ax.set_ylim(0, 0.8)
ax.set_xlabel("Robot coverage of staff rollout (%)")
ax.set_ylabel("Rollout minus human (min per request)")
fig.savefig(out / "fig_gap_coverage.pdf")
plt.close(fig)
print("ok")
