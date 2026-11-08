"""Analysis of the frontvol phase (see ctl/run_frontvol.py). Outputs in analysis_frontvol/.

Random admission curve. In every condition the random arms (p = 0, i.e. human transport; matched random at the
coverage of staff rollout; r2omit; rf_staff3, rf_omit3, rf_staff10, rf_omit10) give points (mean coverage, J per
seed). R_cs(x) interpolates linearly in coverage between neighbouring arms (extrapolates the last segment beyond
the largest arm). The selection value of policy P is S_P = R_cs(cov_P,c) - J_P,cs with cov_P,c the condition mean.
This replaces the single slope beta by a per condition curve and gives curve-adjusted S, S_omit and V*.
Seed is the unit of replication; conditions are weighted equally within a subset.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_frontvol"; OUT.mkdir(exist_ok=True)
COND = ["mode", "background_fraction", "information_lag"]
MAIN_SEEDS_ALL = list(range(103000, 103020))
ARMS = ["human_only", "rand", "r2omit", "rf_staff3", "rf_omit3", "rf_staff10", "rf_omit10"]


def tci(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x))
    h = stats.t.ppf(.975, len(x) - 1) * se
    return m, m - h, m + h, int((x > 0).sum()), len(x)


def load(folder, pattern, name=None, keep_missions=False):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        tag = r.get("scenario_tag", "")
        pol = name or r["policy"]
        if pol in ("staff_phi", "omitted_phi"):
            pol = f'{pol}{int(float(w["phi"]))}'
        if pol == "matched_random" and tag.startswith("rf_"):
            pol = tag
        ml = r.get("mission_log", {})
        row = dict(mode=w["mode"], background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                   seed=int(f.stem.split("__")[-1]), policy=pol, J=r["weighted_tardiness_per_request"],
                   cov=r["robot_coverage"], released=r["net_released_minutes"] / 7, late=r["late_fraction"],
                   theta=w.get("theta"), own=ml.get("own_tardiness_per_request"), other=ml.get("other_tardiness_per_request"))
        if keep_missions:
            row["missions"] = ml.get("missions")
        rows.append(row)
    return pd.DataFrame(rows)


main = pd.read_csv(ROOT / "main_runs_subset.csv")
main = main.rename(columns={"weighted_tardiness_per_request": "J", "robot_coverage": "cov", "late_fraction": "late"})
main["released"] = main.net_released_minutes / 7
main = main[COND + ["seed", "policy", "J", "cov", "released", "late"]]
front = load(ROOT / "results" / "frontvol", "*.json", keep_missions=True)
phi8 = load(ROOT / "results" / "phi_main", "*.json")
d = pd.concat([main, load(ROOT / "results" / "controls", "*__matched_random__*.json", "rand"),
               load(ROOT / "results" / "omitvol", "r2omit__*.json", "r2omit"),
               front.drop(columns=["missions"]), phi8], ignore_index=True)
d["policy"] = d.policy.replace({"omitted_quota": "quota"})
counts = d.groupby("policy").size()
print(counts.to_string())
J = d.pivot_table(index=["seed"] + COND, columns="policy", values="J")
CV = d.groupby(COND + ["policy"])["cov"].mean().unstack() * 100   # percent, condition means
REL = d.pivot_table(index=["seed"] + COND, columns="policy", values="released")
CV["human_only"] = 0.0
pols = [p for p in J.columns if p not in ("optimizer", "own_completion")]


def curve(seed_row, cond_key, x):
    """Random admission curve in one condition and seed, evaluated at coverage x (percent)."""
    pts = sorted((CV.loc[cond_key, a], seed_row[a]) for a in ARMS)
    groups = []  # merge arms whose coverage differs by less than 0.02 percentage points
    for xa, ya in pts:
        if groups and xa - groups[-1][-1][0] < 0.02:
            groups[-1].append((xa, ya))
        else:
            groups.append([(xa, ya)])
    xs = np.array([np.mean([p[0] for p in g]) for g in groups])
    ys = np.array([np.mean([p[1] for p in g]) for g in groups])
    if x <= xs[-1]:
        return float(np.interp(x, xs, ys))
    return float(ys[-1] + (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) * (x - xs[-1]))


rows = []
for (seed, *ck), r in J.iterrows():
    ck = tuple(ck)
    rec = dict(zip(["seed"] + COND, (seed, *ck)))
    for p in pols:
        if np.isnan(r.get(p, np.nan)):
            continue
        rec[f"R_{p}"] = curve(r, ck, CV.loc[ck, p])
        rec[f"S_{p}"] = rec[f"R_{p}"] - r[p]
        rec[f"J_{p}"] = r[p]
    rows.append(rec)
S = pd.DataFrame(rows)
S["B"] = S.J_no_support_forecast - S.J_staff_rollout
S["Vstar_curve"] = S.R_no_support_forecast - S.R_staff_rollout
S["SR_minus_H"] = S.J_staff_rollout - S.J_human_only
S["quota_minus_SR"] = S.J_quota - S.J_staff_rollout          # >0: staff rollout selects better at equal coverage
S["OS_minus_quota"] = S.J_no_support_forecast - S.J_quota     # volume holding the ranking of omitted support
S["quota_minus_H"] = S.J_quota - S.J_human_only
S["SR_minus_quota_sel"] = S.S_staff_rollout - S.S_quota       # equal-coverage comparison adjusted by the random curve

# equal coverage comparison of the two allowance families: omitted family interpolated at the coverage of
# each staff family point (omitted family: quota, omitted support, phi 3, phi 10)
fam_o = ["quota", "no_support_forecast", "omitted_phi3", "omitted_phi10"]
for p in ("staff_rollout", "staff_phi3", "staff_phi10"):
    vals, extrap = [], 0
    for _, r in S.iterrows():
        ck = tuple(r[c] for c in COND)
        xs = np.array([CV.loc[ck, q] for q in fam_o]); ys = np.array([r[f"J_{q}"] for q in fam_o])
        o = np.argsort(xs); xs, ys = xs[o], ys[o]
        x = CV.loc[ck, p]
        if x > xs[-1] or x < xs[0]:
            extrap += 1
        vals.append(float(np.interp(x, xs, ys)) if xs[0] <= x <= xs[-1] else
                    float(ys[-1] + (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) * (x - xs[-1])) if x > xs[-1] else
                    float(ys[0] + (ys[1] - ys[0]) / (xs[1] - xs[0]) * (x - xs[0])))
    S[f"eqcov_{p}"] = np.array(vals) - S[f"J_{p}"]   # >0: staff family better at equal coverage
    print(p, "equal coverage extrapolated in", extrap, "of", len(S))
S.to_csv(OUT / "frontvol_seed_condition.csv", index=False)

subsets = {"all": S.index == S.index}
for m in ("mobile", "mixed", "local"):
    subsets[m] = S["mode"] == m
for b in (0.0, 0.4, 0.8):
    subsets[f"b={b:g}"] = S.background_fraction == b
for lag in (0, 10):
    subsets[f"lag={lag}"] = S.information_lag == lag
metrics = ["B", "SR_minus_H", "S_staff_rollout", "S_no_support_forecast", "Vstar_curve", "S_quota", "quota_minus_SR",
           "SR_minus_quota_sel",
           "OS_minus_quota", "quota_minus_H", "S_staff_phi3", "S_staff_phi10", "S_omitted_phi3", "S_omitted_phi10",
           "eqcov_staff_rollout", "eqcov_staff_phi3", "eqcov_staff_phi10"]
out = []
for name, mask in subsets.items():
    g = S[mask].groupby("seed")[metrics].mean()
    for mtr in metrics:
        m, lo, hi, pos, n = tci(g[mtr])
        out.append(dict(subset=name, metric=mtr, mean=m, lo=lo, hi=hi, positive_seeds=pos, n=n))
summary = pd.DataFrame(out)
summary.to_csv(OUT / "frontvol_contrasts.csv", index=False)

# coverage and released time by policy
cov_tab = pd.DataFrame(dict(coverage=CV.mean(), J=J.mean(), released=REL.mean().reindex(CV.columns)))
cov_tab.to_csv(OUT / "frontvol_policy_means.csv")
cov_tab_cond = CV.copy(); cov_tab_cond.to_csv(OUT / "frontvol_coverage_by_condition.csv")
byb = d[d.seed.isin(MAIN_SEEDS_ALL)].groupby(["background_fraction", "policy"]).agg(
    J=("J", "mean"), cov=("cov", "mean"), released=("released", "mean"), late=("late", "mean"), n=("J", "size")).reset_index()
byb.to_csv(OUT / "frontvol_means_by_b.csv", index=False)
bymode = d.groupby(["mode", "policy"]).agg(J=("J", "mean"), cov=("cov", "mean"), released=("released", "mean")).reset_index()
bymode.to_csv(OUT / "frontvol_means_by_mode.csv", index=False)

# equal released time (as in the earlier front analysis): per seed, condition means of J and released for the
# three points of each family, linear interpolation in released time
eqr = []
fam = {"aware": ["staff_rollout", "staff_phi3", "staff_phi10"], "omitted": ["no_support_forecast", "omitted_phi3", "omitted_phi10"]}
Jm, Rm = J.groupby("seed").mean(), REL.groupby("seed").mean()
for target in (30, 60, 100, 120):
    diffs = []
    for s in Jm.index:
        v = {}
        for f, ps in fam.items():
            xs = np.array([Rm.loc[s, p] for p in ps]); ys = np.array([Jm.loc[s, p] for p in ps]); o = np.argsort(xs)
            v[f] = np.interp(target, xs[o], ys[o]) if xs.min() <= target <= xs.max() else np.nan
        diffs.append(v["omitted"] - v["aware"])
    m, lo, hi, pos, n = tci(diffs)
    eqr.append(dict(released=target, omitted_minus_aware=m, lo=lo, hi=hi, n=n))
pd.DataFrame(eqr).to_csv(OUT / "frontvol_equal_released.csv", index=False)

# mission profile of the threshold rule next to staff rollout and matched random (same definitions as omitvol)
q = front[front.policy == "omitted_quota"]
recs = []
for r in q.itertuples():
    for m in (r.missions or []):
        recs.append(dict(mode=r.mode, seed=r.seed, policy="quota", **m))
M = pd.DataFrame(recs)
old = pd.read_csv(ROOT / "analysis_omitvol" / "missions_records.csv.gz")
M = pd.concat([old[old.policy.isin(["staff_rollout", "matched_random", "no_support_forecast"])], M], ignore_index=True)
M["specimen"] = (M.task_type == "specimen").astype(float)
prof = []
for sub, g0 in list(M.groupby("mode")) + [("all", M)]:
    for pol, g in g0.groupby("policy"):
        runs = 120 if sub != "all" else 360
        prof.append(dict(subset=sub, policy=pol, missions_per_run=len(g) / runs, specimen_share=g.specimen.mean(),
                         robot_minutes=g.robot_minutes.mean(), distance_m=g.distance_m.mean(), queue_at_decision=g.queue.mean(),
                         idle_mobile=g.idle_mobile.mean(), late_share=(g.weighted_tardiness > 0).mean(),
                         own_wt_per_mission=g.weighted_tardiness.mean()))
pd.DataFrame(prof).to_csv(OUT / "quota_mission_profile.csv", index=False)
# paired composition contrast quota - staff rollout (equal coverage)
rows = []
for sub, g0 in list(M.groupby("mode")) + [("all", M)]:
    g = g0.groupby(["seed", "policy"])[["specimen", "robot_minutes", "queue"]].mean().unstack("policy")
    for var in ["specimen", "robot_minutes", "queue"]:
        dd = (g[(var, "quota")] - g[(var, "staff_rollout")]).dropna()
        m, lo, hi, pos, n = tci(dd)
        rows.append(dict(subset=sub, variable=var, contrast="quota - staff_rollout", mean=m, lo=lo, hi=hi, n=n))
pd.DataFrame(rows).to_csv(OUT / "quota_composition_contrasts.csv", index=False)
# own/other split of the equal-coverage comparison
mis = load(ROOT / "results" / "missions", "mis__*staff_rollout*.json")
qq = q.copy()
oo = pd.concat([mis, qq], ignore_index=True)
own = oo.pivot_table(index=["seed"] + COND, columns="policy", values="own")
oth = oo.pivot_table(index=["seed"] + COND, columns="policy", values="other")
sp = pd.DataFrame({"own": own.omitted_quota - own.staff_rollout, "other": oth.omitted_quota - oth.staff_rollout}).reset_index()
rows = []
for sub, mask in [("all", sp.index == sp.index)] + [(m, sp["mode"] == m) for m in ("mobile", "mixed", "local")]:
    g = sp[mask].groupby("seed")[["own", "other"]].mean()
    for col in ("own", "other"):
        m, lo, hi, pos, n = tci(g[col]); rows.append(dict(subset=sub, part=col, mean=m, lo=lo, hi=hi))
pd.DataFrame(rows).to_csv(OUT / "quota_own_other.csv", index=False)

pd.set_option("display.width", 220)
print(pd.DataFrame(prof).round(3).to_string(index=False))
print(pd.DataFrame(rows).round(3).to_string(index=False))
print(summary[summary.subset == "all"].round(3).to_string(index=False))
print(summary[summary.metric.isin(["quota_minus_SR", "S_quota", "S_staff_rollout", "S_no_support_forecast", "Vstar_curve",
                                   "eqcov_staff_phi10", "S_staff_phi10", "S_omitted_phi10"])]
      .pivot(index="subset", columns="metric", values="mean").round(3).to_string())
print(cov_tab.round(3).to_string())
print(pd.DataFrame(eqr).round(3).to_string(index=False))
