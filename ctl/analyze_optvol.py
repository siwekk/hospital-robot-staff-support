"""Pre-specified analysis of the optimizer volume control (design_optvol.json).

Decomposition, all in weighted minutes per request, seed averages over equally weighted conditions:
  S_opt  = J(random at optimizer coverage) - J(optimizer)        selection value of optimization
  V_opt  = J(random at rollout coverage)   - J(random at optimizer coverage)   volume effect
  S_roll = J(random at rollout coverage)   - J(staff_rollout)    selection value of rollout
  J(staff_rollout) - J(optimizer) = V_opt + S_opt - S_roll       exact identity
Two robots: primary (20 seeds, 18 conditions). Fleets four and eight: exploratory (6 seeds, 8 conditions).
"""
import json
from pathlib import Path

import numpy as np, pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_optvol"; OUT.mkdir(exist_ok=True)
SENS = lambda d: d[d["mode"].isin(["mobile", "local"]) & d.background_fraction.isin([.4, .8])]


def load(folder, pattern, label=None):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append(dict(seed=int(f.stem.split("__")[-1]), policy=label or r["policy"], mode=w["mode"],
                         background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                         J=r["weighted_tardiness_per_request"], coverage=r["robot_coverage"],
                         released=r["net_released_minutes"] / 7))
    return pd.DataFrame(rows)


def ci(x):
    x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x)); t = stats.t.ppf(.975, len(x) - 1)
    p = 2 * stats.t.sf(abs(m / se), len(x) - 1) if se > 0 else float("nan")
    return dict(mean=m, lo=m - t * se, hi=m + t * se, p=p, seeds_positive=int((x > 0).sum()), n_seeds=len(x))


def decompose(df, name, seeds, n_cond):
    df = df[df.seed.isin(seeds)]
    cell = df.pivot_table(index=["seed", "mode", "background_fraction", "information_lag"], columns="policy", values="J")
    need = ["optimizer", "staff_rollout", "rand_opt", "rand_roll", "human_only"]
    missing = [c for c in need if c not in cell]
    if missing:
        raise RuntimeError(f"{name}: missing policies {missing}")
    cell = cell[need].dropna()
    per_seed = cell.groupby("seed").size()
    if (per_seed != n_cond).any() or len(per_seed) != len(seeds):
        raise RuntimeError(f"{name}: incomplete cells {per_seed.to_dict()}")
    P = cell.groupby("seed").mean()
    rows = []
    for label, x in (("S_opt = rand_opt - optimizer", P.rand_opt - P.optimizer),
                     ("V_opt = rand_roll - rand_opt", P.rand_roll - P.rand_opt),
                     ("S_roll = rand_roll - staff_rollout", P.rand_roll - P.staff_rollout),
                     ("staff_rollout - optimizer", P.staff_rollout - P.optimizer),
                     ("rand_opt - human_only", P.rand_opt - P.human_only)):
        rows.append(dict(fleet=name, contrast=label, **ci(x)))
    ident = (P.staff_rollout - P.optimizer) - ((P.rand_roll - P.rand_opt) + (P.rand_opt - P.optimizer) - (P.rand_roll - P.staff_rollout))
    assert np.allclose(ident, 0)
    cov = df.pivot_table(index=["mode", "background_fraction", "information_lag"], columns="policy", values="coverage")
    match = pd.DataFrame({"fleet": name, "ratio_opt": cov.rand_opt / cov.optimizer, "ratio_roll": cov.rand_roll / cov.staff_rollout}).reset_index()
    by_mode = []
    for mode, g in cell.reset_index().groupby("mode"):
        Q = g.groupby("seed")[need].mean()
        by_mode.append(dict(fleet=name, subset=mode, **{f"S_opt_{k}": v for k, v in ci(Q.rand_opt - Q.optimizer).items()}))
    means = df.groupby("policy")[["J", "coverage", "released"]].mean().assign(fleet=name).reset_index()
    return pd.DataFrame(rows), match, pd.DataFrame(by_mode), means


def main():
    design = json.loads((ROOT / "design_optvol.json").read_text())
    main = pd.read_csv(ROOT / "main_runs_subset.csv").rename(columns={"weighted_tardiness_per_request": "J", "robot_coverage": "coverage"})
    main["released"] = main.net_released_minutes / 7
    main = main[main.policy.isin(["optimizer", "staff_rollout", "human_only"])][["seed", "policy", "mode", "background_fraction", "information_lag", "J", "coverage", "released"]]
    two = pd.concat([main, load(ROOT / "results" / "controls", "*__matched_random__*.json", "rand_roll"),
                     load(ROOT / "results" / "optvol", "r2opt__*.json", "rand_opt")], ignore_index=True)
    parts = [decompose(two, "two robots", design["arms"]["r2opt"]["seeds"], 18),
             decompose(SENS(two), "two robots, sensitivity subset", design["arms"]["fleet4opt"]["seeds"], 8)]
    human = SENS(main[main.policy == "human_only"])
    for fleet in ("fleet4", "fleet8"):
        d = pd.concat([load(ROOT / "results" / "sens_opt", f"{fleet}__*__optimizer__*.json"),
                       load(ROOT / "results" / "sens", f"{fleet}__*__staff_rollout__*.json"),
                       load(ROOT / "results" / "optvol", f"{fleet}opt__*.json", "rand_opt"),
                       load(ROOT / "results" / "optvol", f"{fleet}roll__*.json", "rand_roll"), human], ignore_index=True)
        parts.append(decompose(d, fleet, design["arms"][f"{fleet}opt"]["seeds"], 8))
    names = ("optvol_contrasts", "optvol_coverage_match", "optvol_by_mode", "optvol_means")
    pd.set_option("display.width", 240)
    for i, n in enumerate(names):
        T = pd.concat([p[i] for p in parts], ignore_index=True)
        T.to_csv(OUT / f"{n}.csv", index=False)
        print("==", n); print(T.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
