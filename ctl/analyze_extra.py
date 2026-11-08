"""Front of J versus released staff time, and sensitivity tables. Outputs go to ../analysis_extra."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_extra"; OUT.mkdir(exist_ok=True)
COLS = ["seed", "mode", "background_fraction", "information_lag", "policy", "created", "robot_completed",
        "late_fraction", "weighted_tardiness_per_request", "robot_coverage", "net_released_minutes",
        "human_transport_minutes"]
COND = ["mode", "background_fraction", "information_lag"]


def load(folder, tag_in_name=False):
    rows = []
    for f in sorted(Path(folder).glob("*.json")):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append({k: r.get(k) for k in COLS if k not in COND + ["seed", "policy"]}
                    | {"mode": w["mode"], "background_fraction": w["background_fraction"],
                       "information_lag": w["information_lag"], "seed": int(f.stem.split("__")[-1]),
                       "policy": r["policy"], "tag": r.get("scenario_tag", ""), "lam": w.get("phi")})
    return pd.DataFrame(rows)


main = pd.read_csv(ROOT / "main_runs_subset.csv")
ctl = load(ROOT / "results" / "controls") if (ROOT / "results" / "controls").exists() else pd.DataFrame()
base = pd.concat([main[COLS], ctl[COLS]], ignore_index=True) if len(ctl) else main[COLS]
base = base.assign(tag="main", lam=np.nan)
base["J"] = base["weighted_tardiness_per_request"]


def tci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x))
    t = stats.t.ppf(.975, len(x) - 1); return m, m - t * se, m + t * se


# ---------------- cost family front -----------------
cm = ROOT / "results" / "phi_main"
if cm.exists() and any(cm.glob("*.json")):
    cost = load(cm); cost["J"] = cost["weighted_tardiness_per_request"]
    seeds = sorted(cost.seed.unique())
    ref = base[base.seed.isin(seeds)]
    pts = []
    for pol, g in ref.groupby("policy"):
        pts.append(dict(label=pol, family="reference", lam=np.nan, J=g.J.mean(), coverage=g.robot_coverage.mean(),
                        released_per_day=g.net_released_minutes.mean() / 7))
    for (pol, lam), g in cost.groupby(["policy", "lam"]):
        fam = "aware" if pol == "staff_phi" else "omitted"
        pts.append(dict(label=f"{fam}_lam{lam}", family=fam, lam=lam, J=g.J.mean(), coverage=g.robot_coverage.mean(),
                        released_per_day=g.net_released_minutes.mean() / 7))
    front = pd.DataFrame(pts).sort_values(["family", "released_per_day"])
    front.to_csv(OUT / "cost_front_pooled.csv", index=False)
    print(front.round(4).to_string(index=False))
    # paired contrast aware vs omitted at the same lambda, seed level
    rows = []
    for lam, g in cost.groupby("lam"):
        p = g.pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()
        d = (p["staff_phi"] - p["omitted_phi"]).dropna()
        m, lo, hi = tci(d)
        rel = g.pivot_table(index=["seed"] + COND, columns="policy", values="net_released_minutes").groupby("seed").mean()
        rows.append(dict(lam=lam, aware_minus_omitted_J=m, lo=lo, hi=hi,
                         released_aware=rel["staff_phi"].mean() / 7, released_omitted=rel["omitted_phi"].mean() / 7))
    pd.DataFrame(rows).to_csv(OUT / "cost_aware_vs_omitted.csv", index=False)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    # figure: J versus released minutes per day, panels by background fraction
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharey=False)
    for ax, b in zip(axes, [0.0, 0.4, 0.8]):
        for fam, marker, color in (("aware", "o", "#1f77b4"), ("omitted", "s", "#d62728")):
            sub = pd.concat([cost[(cost.policy == ("staff_phi" if fam == "aware" else "omitted_phi")) & (cost.background_fraction == b)]
                             .groupby("lam").agg(J=("J", "mean"), r=("net_released_minutes", "mean")).reset_index()])
            sub["r"] /= 7
            r0 = ref[(ref.policy == ("staff_rollout" if fam == "aware" else "no_support_forecast")) & (ref.background_fraction == b)]
            xs = [r0.net_released_minutes.mean() / 7] + list(sub.r); ys = [r0.J.mean()] + list(sub.J)
            o = np.argsort(xs); ax.plot(np.array(xs)[o], np.array(ys)[o], marker + "-", color=color, label=fam)
        for pol, mk in (("human_only", "^"), ("matched_random", "x"), ("idle_pair_rule", "D")):
            r0 = ref[(ref.policy == pol) & (ref.background_fraction == b)]
            if len(r0): ax.plot(r0.net_released_minutes.mean() / 7, r0.J.mean(), mk, color="k", label=pol)
        ax.set_title(f"unavailable fraction {b}"); ax.set_xlabel("net staff minutes released per day")
    axes[0].set_ylabel("weighted tardiness per request"); axes[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(OUT / "cost_front.pdf")

# ---------------- sensitivity -----------------
sm = ROOT / "results" / "sens"
if sm.exists() and any(sm.glob("*.json")):
    sens = load(sm); sens["J"] = sens["weighted_tardiness_per_request"]
    seeds = sorted(sens.seed.unique())
    human = base[(base.policy == "human_only") & base.seed.isin(seeds)]
    rows = []
    for tag, g in sens.groupby("tag"):
        conds = g[COND].drop_duplicates()
        hh = human.merge(conds, on=COND)
        p = pd.concat([g[g.policy.isin(["staff_rollout", "no_support_forecast", "idle_pair_rule"])],
                       hh.assign(tag=tag)]).pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()
        cov = g.groupby("policy").robot_coverage.mean(); rel = g.groupby("policy").net_released_minutes.mean() / 7
        row = dict(scenario=tag, n_seeds=len(seeds), J_human=p["human_only"].mean())
        for pol in ("staff_rollout", "no_support_forecast", "idle_pair_rule"):
            row[f"J_{pol}"] = p[pol].mean(); row[f"cov_{pol}"] = cov[pol]; row[f"released_{pol}"] = rel[pol]
        for a, b in (("staff_rollout", "no_support_forecast"), ("staff_rollout", "idle_pair_rule"), ("staff_rollout", "human_only")):
            m, lo, hi = tci(p[a] - p[b]); row[f"{a}-{b}"] = m; row[f"{a}-{b}_lo"] = lo; row[f"{a}-{b}_hi"] = hi
        rows.append(row)
    S = pd.DataFrame(rows); S.to_csv(OUT / "sensitivity_summary.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    print(S.round(4).T.to_string())
