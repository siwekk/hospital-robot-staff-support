"""Staff-side measures of robot support, computed from stored run files (no new simulation).
Added on 17 November 2026 for the IJSR revision.

For every run: support calls (loading, receiving and cleaning assignments) per day, the time from a call to the
arrival of a worker (queue wait plus approach walk), the robot waiting time per day, other duties displaced by
transport and support work (planned minus realized unavailability minutes), and overtime past shift end.
Differences to human transport are paired by seed and condition, averaged with equal weight over conditions,
with 95% Student t intervals across seeds. Mission records give the state of the workforce when each robot
mission was admitted.

usage: python ctl/analyze_human_side.py <study_root> [<controls_root>]
  study_root     folder that holds results/main (main experiment run files)
  controls_root  folder that holds results/controls, results/frontvol, results/phi_main (default: study_root)
"""
import gzip, json, sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis_human"
DAYS = 7


def tci(x):
    x = np.asarray(x, float); n = len(x); m = x.mean()
    h = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return m, m - h, m + h, n


def row(path, label):
    r = json.loads(path.read_text())
    w = r["workflow"]
    calls = r["human_support_tasks"]
    q = r.get("mobile_support_queue_wait", 0) + r.get("local_support_queue_wait", 0)
    a = r.get("mobile_support_approach", 0) + r.get("local_support_approach", 0)
    return dict(policy=label, seed=r["seed"], mode=w["mode"], b=w["background_fraction"], lag=w["information_lag"],
                J=r["weighted_tardiness_per_request"], coverage=r["robot_coverage"],
                missions_per_day=r["robot_completed"] / DAYS, calls_per_day=calls / DAYS,
                wait_per_call=(r["human_support_wait_minutes"] / calls) if calls else np.nan,
                queue_per_call=(q / calls) if calls else np.nan, approach_per_call=(a / calls) if calls else np.nan,
                robot_wait_per_day=r["human_support_wait_minutes"] / DAYS,
                support_minutes_per_day=r["human_support_minutes"] / DAYS,
                released_per_day=r["net_released_minutes"] / DAYS,
                displaced_per_day=(r.get("mobile_displaced_background_minutes", 0) + r.get("local_displaced_background_minutes", 0)) / DAYS,
                displaced_mobile_per_day=r.get("mobile_displaced_background_minutes", 0) / DAYS,
                displaced_local_per_day=r.get("local_displaced_background_minutes", 0) / DAYS,
                local_support_minutes_per_day=(r.get("local_load_service", 0) + r.get("local_receive_service", 0) + r.get("local_clean_service", 0)) / DAYS,
                overtime_per_day=(r.get("mobile_overtime_minutes", 0) + r.get("local_overtime_minutes", 0)) / DAYS,
                failures_per_day=r.get("failures", 0) / DAYS)


def main():
    study = Path(sys.argv[1]); ctl = Path(sys.argv[2]) if len(sys.argv) > 2 else study
    rows = []
    for p in sorted((study / "results" / "main").glob("*.json")):
        pol = p.name.split("__")[1]
        rows.append(row(p, pol))
    for pol in ("matched_random", "idle_pair_rule"):
        rows += [row(p, pol) for p in sorted((ctl / "results" / "controls").glob(f"*__{pol}__*.json"))]
    rows += [row(p, "threshold_rule") for p in sorted((ctl / "results" / "frontvol").glob("quota__*__omitted_quota__*.json"))]
    for pol in ("staff_phi", "omitted_phi"):
        files = list((ctl / "results" / "phi_main").glob(f"phi10.0__*__{pol}__*.json")) + \
                list((ctl / "results" / "frontvol").glob(f"phi10.0__*__{pol}__*.json"))
        rows += [row(p, pol + "10") for p in sorted(files)]
    gate_files = sorted((ROOT / "results" / "gate").glob("gate__*__staff_gate__*.json"))
    rows += [row(p, "staff_gate") for p in gate_files]
    D = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    D.to_csv(OUT / "human_side_runs.csv.gz", index=False)
    counts = D.groupby("policy").size()
    print(counts.to_string())

    metrics = ["J", "coverage", "missions_per_day", "calls_per_day", "wait_per_call", "queue_per_call", "approach_per_call",
               "robot_wait_per_day", "support_minutes_per_day", "released_per_day", "displaced_per_day", "displaced_mobile_per_day", "displaced_local_per_day", "local_support_minutes_per_day", "overtime_per_day"]
    subsets = [("all", D.index == D.index), ("mobile", D["mode"] == "mobile"), ("mixed", D["mode"] == "mixed"),
               ("local", D["mode"] == "local"), ("b=0", D.b == 0), ("b=0.4", D.b == 0.4), ("b=0.8", D.b == 0.8)]
    means = []
    for sub, mask in subsets:
        g = D[mask].groupby("policy")
        # condition means first, then equal weight over conditions (as in the article)
        cm = D[mask].groupby(["policy", "mode", "b", "lag"])[metrics].mean().groupby("policy").mean()
        for pol, r in cm.iterrows():
            means.append(dict(subset=sub, policy=pol, **r.to_dict()))
    M = pd.DataFrame(means)
    M.to_csv(OUT / "human_side_means.csv", index=False)

    key = ["seed", "mode", "b", "lag"]
    base = D[D.policy == "human_only"].set_index(key)
    contr = []
    for pol in sorted(set(D.policy) - {"human_only"}):
        x = D[D.policy == pol].set_index(key)
        joint = x.join(base, rsuffix="_h", how="inner")
        for sub, sel in [("all", None), ("mobile", "mobile"), ("mixed", "mixed"), ("local", "local")]:
            j = joint if sel is None else joint[joint.index.get_level_values("mode") == sel]
            for var in ("displaced_per_day", "displaced_mobile_per_day", "displaced_local_per_day", "overtime_per_day", "calls_per_day", "robot_wait_per_day", "J"):
                dd = (j[var] - j[var + "_h"]).groupby(level="seed").mean()
                m, lo, hi, n = tci(dd)
                contr.append(dict(subset=sub, policy=pol, variable=var + " - human", mean=m, lo=lo, hi=hi, n_seeds=n))
    C = pd.DataFrame(contr)
    C.to_csv(OUT / "human_side_contrasts.csv", index=False)

    # workforce state at admission (mission records of the omitvol and frontvol phases)
    rec = pd.read_csv(ROOT / "analysis_omitvol" / "missions_records.csv.gz")
    q = []
    for label, files in (("quota", sorted((ctl / "results" / "frontvol").glob("quota__*__omitted_quota__*.json"))),
                         ("staff_gate", gate_files)):
        for p in files:
            r = json.loads(p.read_text())
            for m in r["mission_log"]["missions"]:
                q.append(dict(m, policy=label, mode=r["workflow"]["mode"], seed=r["seed"]))
    rec = pd.concat([rec, pd.DataFrame(q)], ignore_index=True)
    rec["no_idle"] = (rec.idle_mobile == 0).astype(float)
    st = []
    for (mode, pol), g in list(rec.groupby(["mode", "policy"])) + [(("transporters", p), g) for p, g in
                                                                  rec[rec["mode"] != "local"].groupby("policy")]:
        st.append(dict(mode=mode, policy=pol, missions=len(g), no_idle_mobile=g.no_idle.mean(),
                       at_most_one_idle_mobile=(g.idle_mobile <= 1).mean(), queue_ge3=(g.queue >= 3).mean(),
                       night=(g["shift"] == "night").mean() if "shift" in g else np.nan,
                       late=(g.weighted_tardiness > 0).mean()))
    S = pd.DataFrame(st)
    S.to_csv(OUT / "human_side_admission_state.csv", index=False)
    # paired by seed: share of missions admitted with no idle transporter, mobile and mixed support pooled
    sh = rec[rec["mode"] != "local"].groupby(["seed", "policy"]).no_idle.mean().unstack("policy")
    pc = []
    for a, b in [("staff_rollout", "matched_random"), ("quota", "staff_rollout"), ("staff_gate", "staff_rollout"),
                 ("no_support_forecast", "r2omit")]:
        if a in sh and b in sh:
            m, lo, hi, n = tci((sh[a] - sh[b]).dropna())
            pc.append(dict(contrast=f"{a} - {b}", mean=m, lo=lo, hi=hi, n_seeds=n))
    pd.DataFrame(pc).to_csv(OUT / "human_side_no_idle_contrasts.csv", index=False)
    print(pd.DataFrame(pc).round(3).to_string(index=False))

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(M[M.subset == "all"].round(3).to_string(index=False))
    print(M[M.subset.isin(["mobile", "local", "mixed"])][["subset", "policy", "calls_per_day", "wait_per_call", "queue_per_call",
                                                          "robot_wait_per_day", "released_per_day", "displaced_per_day"]].round(2).to_string(index=False))
    print(C.round(3).to_string(index=False))
    print(S.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
