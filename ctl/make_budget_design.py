"""Chooses local node sets and mobile rosters for the equal budget variant (total 496 staffed hours per day)."""
import itertools, json, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = json.loads((ROOT / "parameters.json").read_text())
pairs = collections.Counter()
for d in p["empirical_daily_requests"]:
    for _, o, t in d["requests"]: pairs[(str(o), str(t))] += 1
n = sum(pairs.values()); nodes = sorted({x for pr in pairs for x in pr})

def both(C): return sum(c for (o, t), c in pairs.items() if o in C and t in C) / n
def dest(C): return sum(c for (o, t), c in pairs.items() if t in C) / n

def local_set(k):
    best = max(itertools.combinations(nodes, 2), key=lambda pr: both(set(pr)))
    C = list(best)
    while len(C) < k:
        C.append(max((x for x in nodes if x not in C), key=lambda x: both(set(C) | {x})))
    return C

def mixed_set(k):
    c = collections.Counter()
    for (o, t), v in pairs.items(): c[t] += v
    return [x for x, _ in c.most_common(k)]

def roster(total_people, base=(8, 30, 24)):
    f = total_people / sum(base); raw = [b * f for b in base]; cnt = [int(x) for x in raw]
    for i in sorted(range(3), key=lambda i: -(raw[i] - cnt[i]))[:total_people - sum(cnt)]: cnt[i] += 1
    return cnt

design = {}
for k in (3, 6):
    people = (496 - 24 * k) // 8
    assert 24 * k + 8 * people == 496
    design[f"k{k}"] = dict(k=k, mobile_people=people, roster=roster(people),
                           local_set=local_set(k), mixed_set=mixed_set(k),
                           local_coverage=both(set(local_set(k))), mixed_coverage=dest(set(mixed_set(k))),
                           staffed_hours=dict(local=24 * k, mobile=8 * people, total=24 * k + 8 * people))
(ROOT / "budget_nodes.json").write_text(json.dumps(design, indent=1))
print(json.dumps(design, indent=1))
