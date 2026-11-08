import sys, json, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT/'src'))
import run_study as base, run_workflows as rw
base.initialize()
out=ROOT/'repro'; out.mkdir(exist_ok=True)
cases={c['name']:c for c in rw.cases()}
bad=0
for name,pol in [('mobile_b40_lag0','staff_rollout'),('local_b80_lag10','staff_rollout'),('mixed_b80_lag0','human_only')]:
    t=time.time()
    rw.job((cases[name],pol,103000,7,7,str(out)))
    new=json.loads((out/f'{name}__{pol}__103000.json').read_text())
    old=json.loads((ROOT/'ref'/f'{name}__{pol}__103000.json').read_text())
    diffs=[k for k in old if k not in('elapsed_seconds','decision_times','optimizer_seconds') and new.get(k)!=old[k]]
    print(name,pol,round(time.time()-t,1),'s; differing keys:',diffs[:10], 'J new/old', new['weighted_tardiness_per_request'], old['weighted_tardiness_per_request'])
