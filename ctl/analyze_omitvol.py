"""Analysis of the omitvol phase: three-term volume split and mission composition.

Inputs: main_runs_subset.csv (staff_rollout, no_support_forecast), results/controls (matched_random),
results/omitvol (r2omit), results/missions (mission logs of staff_rollout, no_support_forecast, matched_random).
Outputs in analysis_omitvol/. Seed is the unit of replication; conditions are weighted equally within a subset.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_omitvol"; OUT.mkdir(exist_ok=True)
COND = ["mode", "background_fraction", "information_lag"]
SUBSETS = {"all": lambda d: d.index == d.index}
for m in ("mobile", "mixed", "local"):
    SUBSETS[m] = (lambda m: lambda d: d["mode"] == m)(m)
for b in (0.0, 0.4, 0.8):
    SUBSETS[f"b={b:g}"] = (lambda b: lambda d: d["background_fraction"] == b)(b)
for lag in (0, 10):
    SUBSETS[f"lag={lag}"] = (lambda lag: lambda d: d["information_lag"] == lag)(lag)


def tci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x))
    h = stats.t.ppf(.975, len(x) - 1) * se
    return m, m - h, m + h, int((x > 0).sum()), len(x)


def load_json(folder, pattern, policy_name=None):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        ml = r.get("mission_log", {})
        rows.append(dict(mode=w["mode"], background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                         seed=int(f.stem.split("__")[-1]), policy=policy_name or r["policy"],
                         J=r["weighted_tardiness_per_request"], cov=r["robot_coverage"],
                         own=ml.get("own_tardiness_per_request"), other=ml.get("other_tardiness_per_request"),
                         missions=ml.get("missions"), propensity=ml.get("propensity"),
                         q_all=ml.get("mean_queue_all"), q_adm=ml.get("mean_queue_admitted")))
    return pd.DataFrame(rows)


main = pd.read_csv(ROOT / "main_runs_subset.csv")
main = main[main.policy.isin(["staff_rollout", "no_support_forecast", "human_only"])]
main = main.rename(columns={"weighted_tardiness_per_request": "J", "robot_coverage": "cov"})[COND + ["seed", "policy", "J", "cov"]]
ctl = load_json(ROOT / "results" / "controls", "*__matched_random__*.json")[COND + ["seed", "policy", "J", "cov"]]
romit = load_json(ROOT / "results" / "omitvol", "r2omit__*.json", "r2omit")
mis = load_json(ROOT / "results" / "missions", "mis__*.json")
base = pd.concat([main, ctl, romit[COND + ["seed", "policy", "J", "cov"]]], ignore_index=True)
J = base.pivot_table(index=["seed"] + COND, columns="policy", values="J").reset_index()
C = base.pivot_table(index=["seed"] + COND, columns="policy", values="cov").reset_index()
assert len(J) == 360 and J[["staff_rollout", "no_support_forecast", "matched_random", "r2omit"]].notna().all().all()

# ---- coverage match ----
cm = C.groupby(COND)[["no_support_forecast", "r2omit", "matched_random", "staff_rollout"]].mean()
cm["ratio_r2omit"] = cm.r2omit / cm.no_support_forecast
cm["ratio_rand"] = cm.matched_random / cm.staff_rollout
cm.to_csv(OUT / "omitvol_coverage.csv")
d_cov = (C.r2omit - C.matched_random).mean() * 100
beta2 = (J.r2omit - J.matched_random).mean() / d_cov
summary = dict(coverage=dict(omit=C.no_support_forecast.mean() * 100, r2omit=C.r2omit.mean() * 100,
                             rand=C.matched_random.mean() * 100, staff=C.staff_rollout.mean() * 100,
                             ratio_r2omit_median=float(cm.ratio_r2omit.median()), ratio_r2omit_min=float(cm.ratio_r2omit.min()),
                             ratio_r2omit_max=float(cm.ratio_r2omit.max())),
               beta_r2omit_vs_rand_per_pp=beta2)

# ---- three-term split, per seed over equally weighted conditions ----
J["B"] = J.no_support_forecast - J.staff_rollout
J["V2"] = J.no_support_forecast - J.matched_random           # two-term volume term
J["S"] = J.matched_random - J.staff_rollout
J["Vstar"] = J.r2omit - J.matched_random
J["S_omit"] = J.r2omit - J.no_support_forecast
J["identity"] = J.B - (-J.S_omit + J.Vstar + J.S)
dcov_omit = (C.r2omit - C.no_support_forecast) * 100
dcov_rand = (C.matched_random - C.staff_rollout) * 100
J["S_omit_adj"] = J.S_omit - beta2 * dcov_omit
J["Vstar_adj"] = J.Vstar - beta2 * dcov_omit + beta2 * dcov_rand
J["S_adj"] = J.S - beta2 * dcov_rand
J["SR_H"] = J.staff_rollout - J.human_only
rows = []
for name, sel in SUBSETS.items():
    sub = J[sel(J)]
    seeds = sub.groupby("seed")[["B", "V2", "S", "Vstar", "S_omit", "S_omit_adj", "Vstar_adj", "S_adj", "identity", "SR_H"]].mean()
    for col in seeds.columns:
        m, lo, hi, pos, n = tci(seeds[col])
        rows.append(dict(subset=name, quantity=col, mean=m, lo=lo, hi=hi, seeds_positive=pos, n_seeds=n))
contr = pd.DataFrame(rows)
contr.to_csv(OUT / "omitvol_contrasts.csv", index=False)
summary["max_abs_identity_error"] = float(J.identity.abs().max())

# ---- own versus other tardiness split ----
mis["policy"] = mis.policy.replace({})
mm = pd.concat([mis[COND + ["seed", "policy", "own", "other", "J"]],
                romit[COND + ["seed", "policy", "own", "other", "J"]]], ignore_index=True)
own = mm.pivot_table(index=["seed"] + COND, columns="policy", values="own").reset_index()
oth = mm.pivot_table(index=["seed"] + COND, columns="policy", values="other").reset_index()
split = pd.DataFrame({c: own[c] for c in ["seed"] + COND})
split["S_own"] = own.matched_random - own.staff_rollout
split["S_other"] = oth.matched_random - oth.staff_rollout
split["Somit_own"] = own.r2omit - own.no_support_forecast
split["Somit_other"] = oth.r2omit - oth.no_support_forecast
split["Vstar_own"] = own.r2omit - own.matched_random
split["Vstar_other"] = oth.r2omit - oth.matched_random
rows = []
for name, sel in SUBSETS.items():
    sub = split[sel(split)]
    seeds = sub.groupby("seed")[[c for c in split.columns if c not in ["seed"] + COND]].mean()
    for col in seeds.columns:
        m, lo, hi, pos, n = tci(seeds[col])
        rows.append(dict(subset=name, quantity=col, mean=m, lo=lo, hi=hi, seeds_positive=pos, n_seeds=n))
pd.DataFrame(rows).to_csv(OUT / "missions_split.csv", index=False)

# ---- mission composition ----
recs = []
for r in pd.concat([mis, romit], ignore_index=True).itertuples():
    for m in (r.missions or []):
        recs.append(dict(mode=r.mode, background_fraction=r.background_fraction, information_lag=r.information_lag,
                         seed=r.seed, policy=r.policy, **m))
M = pd.DataFrame(recs)
M["specimen"] = (M.task_type == "specimen").astype(float)
M["supply"] = (M.task_type == "supply").astype(float)
M["slack"] = M.deadline - M.robot_minutes
M["night"] = (M["shift"] == "night").astype(float)
M.to_csv(OUT / "missions_records.csv.gz", index=False, compression="gzip")
prof = []
for name, sel in SUBSETS.items():
    sub = M[sel(M)]
    for pol, g in sub.groupby("policy"):
        n_runs = len(mm[sel(mm) & (mm.policy == pol)])
        prof.append(dict(subset=name, policy=pol, missions=len(g), missions_per_run=len(g) / max(1, n_runs),
                         specimen_share=g.specimen.mean(), supply_share=g.supply.mean(),
                         medication_share=(g.task_type == "medication").mean(), instrument_share=(g.task_type == "instrument").mean(),
                         deadline=g.deadline.mean(), slack=g.slack.mean(), robot_minutes=g.robot_minutes.mean(),
                         human_minutes=g.human_minutes.mean(), distance_m=g.distance_m.mean(), elevator_rides=g.elevator_rides.mean(),
                         night_share=g.night.mean(), queue_at_decision=g.queue.mean(), idle_mobile=g.idle_mobile.mean(),
                         late_share=(g.weighted_tardiness > 0).mean(), own_wt_per_mission=g.weighted_tardiness.mean()))
pd.DataFrame(prof).to_csv(OUT / "missions_profile.csv", index=False)

# paired seed-level differences in composition, staff rollout minus matched random (equal coverage)
rows = []
for name, sel in SUBSETS.items():
    sub = M[sel(M)]
    g = sub.groupby(["seed", "policy"])[["specimen", "slack", "deadline", "robot_minutes", "queue"]].mean().unstack("policy")
    for var in ["specimen", "slack", "deadline", "robot_minutes", "queue"]:
        for a, b in (("staff_rollout", "matched_random"), ("no_support_forecast", "r2omit")):
            if (var, a) in g and (var, b) in g:
                d = (g[(var, a)] - g[(var, b)]).dropna()
                if len(d) > 2:
                    m, lo, hi, pos, n = tci(d)
                    rows.append(dict(subset=name, variable=var, contrast=f"{a} - {b}", mean=m, lo=lo, hi=hi, n_seeds=n))
pd.DataFrame(rows).to_csv(OUT / "missions_composition_contrasts.csv", index=False)
(OUT / "omitvol_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=1))
print(contr[contr.subset.isin(["all", "mobile", "mixed", "local"]) & contr.quantity.isin(["B", "S", "Vstar", "S_omit", "Vstar_adj", "S_omit_adj"])].round(4).to_string(index=False))
print("ok")
