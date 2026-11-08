"""Optimizer on a fleet of four robots, paired with the heuristics of results/sens on identical seeds and conditions."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
FLEET = sys.argv[1] if len(sys.argv) > 1 else "fleet4"  # fleet4 or fleet8
if FLEET not in ("fleet4", "fleet8"):
    raise ValueError("Expected fleet4 or fleet8")
FLEET_LABEL = "four" if FLEET == "fleet4" else "eight"
WORD = "four robots" if FLEET == "fleet4" else "eight robots"
OUT = ROOT / "analysis_extra"; OUT.mkdir(exist_ok=True)
COND = ["mode", "background_fraction", "information_lag"]


def load(folder, pattern="*.json"):
    rows = []
    for f in sorted(Path(folder).glob(pattern)):
        r = json.loads(f.read_text()); w = r["workflow"]
        rows.append(dict(seed=int(f.stem.split("__")[-1]), policy=r["policy"], mode=w["mode"],
                         background_fraction=w["background_fraction"], information_lag=w["information_lag"],
                         J=r["weighted_tardiness_per_request"], coverage=r["robot_coverage"],
                         released=r["net_released_minutes"], late=r["late_fraction"],
                         elapsed=r["elapsed_seconds"], decision_ms=r.get("decision_mean_ms"),
                         fallback=r.get("optimizer_failures")))
    return pd.DataFrame(rows)


opt = load(ROOT / "results" / "sens_opt", f"{FLEET}__*.json")
heu = load(ROOT / "results" / "sens", f"{FLEET}__*.json")
main = pd.read_csv(ROOT / "main_runs_subset.csv").rename(columns={"weighted_tardiness_per_request": "J", "robot_coverage": "coverage",
                                                                    "net_released_minutes": "released", "late_fraction": "late"})
done = opt.groupby("seed").size(); full_seeds = sorted(done[done == 8].index)
print("seeds with all eight conditions:", full_seeds, "runs:", len(opt))
if len(full_seeds) >= 3:
    sub = lambda d: d[d.seed.isin(full_seeds)]
    opt, heu = sub(opt), sub(heu)
    human = sub(main[(main.policy == "human_only") & main["mode"].isin(["mobile", "local"]) & main.background_fraction.isin([.4, .8])])
    base2 = sub(main[main["mode"].isin(["mobile", "local"]) & main.background_fraction.isin([.4, .8])])
    allf4 = pd.concat([opt, heu, human.assign(coverage=0.0)], ignore_index=True)
    piv = allf4.pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()
    piv2 = base2.pivot_table(index=["seed"] + COND, columns="policy", values="J").groupby("seed").mean()

    def ci(x):
        x = np.asarray(x, float); m = x.mean(); se = x.std(ddof=1) / np.sqrt(len(x)); t = stats.t.ppf(.975, len(x) - 1)
        return m, m - t * se, m + t * se, int((x < 0).sum()), len(x)
    rows = []
    for fleet, P in ((WORD, piv), ("two robots", piv2)):
        for a, b in (("optimizer", "staff_rollout"), ("optimizer", "no_support_forecast"), ("optimizer", "human_only"), ("staff_rollout", "human_only")):
            m, lo, hi, fav, n = ci(P[a] - P[b])
            rows.append(dict(fleet=fleet, contrast=f"{a} - {b}", mean=m, lo=lo, hi=hi, seeds_favoring_first=fav, n_seeds=n))
    T = pd.DataFrame(rows); T.to_csv(OUT / f"optimizer_{FLEET}_contrasts.csv", index=False)
    summ = pd.concat([opt.assign(fleet=FLEET_LABEL), heu.assign(fleet=FLEET_LABEL),
                      human.assign(fleet=FLEET_LABEL, coverage=0.0),
                      base2[base2.policy.isin(["optimizer", "staff_rollout", "no_support_forecast", "human_only"])].assign(fleet="two")]).groupby(["fleet", "policy"]).agg(
        J=("J", "mean"), late=("late", "mean"), coverage=("coverage", "mean"), released=("released", "mean"),
        decision_ms=("decision_ms", "mean"), elapsed_s=("elapsed", "mean")).reset_index()
    summ["released"] /= 7
    summ.to_csv(OUT / f"optimizer_{FLEET}_means.csv", index=False)
    pd.set_option("display.width", 220)
    print(T.round(3).to_string(index=False)); print(summ.round(4).to_string(index=False))
