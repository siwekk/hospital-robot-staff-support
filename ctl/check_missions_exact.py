"""Exact (bit for bit) comparison of the mission-log reruns with the original run outputs.

Usage: python ctl/check_missions_exact.py MAIN_RESULTS_DIR
MAIN_RESULTS_DIR holds the original main runs (case__policy__seed.json); matched_random is compared with
results/controls. Writes omitvol_identity_exact.json in the study root.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main_dir = Path(sys.argv[1])
rows, mismatches = 0, []
for f in sorted((ROOT / "results" / "missions").glob("mis__*.json")):
    _, case, policy, seed = f.stem.split("__")
    ref = (ROOT / "results" / "controls" / f"{case}__{policy}__{seed}.json") if policy == "matched_random" \
        else main_dir / f"{case}__{policy}__{seed}.json"
    new, old = json.loads(f.read_text()), json.loads(ref.read_text())
    for key in ("weighted_tardiness_per_request", "robot_coverage", "created", "robot_completed", "late_fraction",
                "net_released_minutes", "prediction_mae"):
        if key in old and new.get(key) != old[key]:
            mismatches.append(dict(file=f.name, key=key, new=new.get(key), old=old[key]))
    rows += 1
rep = dict(runs_compared=rows, keys_compared=["weighted_tardiness_per_request", "robot_coverage", "created",
           "robot_completed", "late_fraction", "net_released_minutes", "prediction_mae"],
           mismatches=len(mismatches), examples=mismatches[:10], identical=not mismatches)
(ROOT / "omitvol_identity_exact.json").write_text(json.dumps(rep, indent=2))
print(json.dumps(rep, indent=1))
