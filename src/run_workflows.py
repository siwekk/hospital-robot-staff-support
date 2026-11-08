"""Resumable remote experiments. Pilot and confirmatory seeds never overlap."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from itertools import product
from pathlib import Path
from time import perf_counter
import hashlib,json,sys
import run_study as base
from workflow_simulation import WorkflowSimulation

ROOT=Path(__file__).resolve().parents[1]
POLICIES=['human_only','own_completion','no_support_forecast','staff_rollout','optimizer']

def cases():
    return [dict(name=f'{mode}_b{int(100*load)}_lag{lag}',mode=mode,background_fraction=load,information_lag=lag)
            for mode,load,lag in product(['mobile','local','mixed'],[0.,.4,.8],[0,10])]

def config(case,policy,warmup,days):
    center=next(c for c in base.scenarios() if c['name']=='moderate_balanced_d25')
    cfg=base.configure(center,policy,warmup,days)
    cfg['workflow']=dict(case,nodes=json.loads((ROOT/'locations.json').read_text()),solver_seconds=1.0,
                         solver_retry_seconds=[5.0,20.0])
    return cfg

def job(args):
    case,policy,seed,warmup,days,output=args
    p=dict(base.PARAMETERS,task_mix=dict(specimen=.4,medication=.3,supply=.2,instrument=.1))
    cfg=config(case,policy,warmup,days)
    start=perf_counter()
    sim=WorkflowSimulation(cfg,p,seed=seed)
    result=sim.run()
    result.update(case=case['name'],workflow=case,warmup_days=warmup,measurement_days=days,elapsed_seconds=perf_counter()-start)
    assert result['created']==result['completed']+result['incomplete']
    assert result['human_completed']+result['robot_completed']==result['completed']
    assert result['battery_infeasible_missions']==0
    assert result['total_staff_work_minutes']>=0
    path=Path(output)/f'{case["name"]}__{policy}__{seed}.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(result,indent=2))
    temp.replace(path)
    return path.name,result['elapsed_seconds'],result['incomplete']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=['smoke','pilot','main'],default='smoke')
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--replications',type=int,default=0)
    args=parser.parse_args()
    repetitions,warmup,days,seedbase={'smoke':(1,0,.1,101000),'pilot':(4,1,2,102000),'main':(20,7,7,103000)}[args.phase]
    if args.replications: repetitions=args.replications
    chosen=cases()
    if args.phase=='smoke': chosen=[c for c in chosen if c['background_fraction']==.4 and c['information_lag']==0]
    out=ROOT/'results'/args.phase
    out.mkdir(parents=True,exist_ok=True)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'code').rglob('*.py')}
    design=dict(phase=args.phase,repetitions=repetitions,warmup=warmup,days=days,seeds=list(range(seedbase,seedbase+repetitions)),cases=chosen,policies=POLICIES,code_hashes=hashes,
                optimizer=dict(primary_limits_seconds=[1.,5.,20.],secondary_limit_seconds=1.,retry_only_status='UNKNOWN'))
    designpath=ROOT/f'design_{args.phase}.json'
    if designpath.exists():
        previous=json.loads(designpath.read_text())
        if previous!=design: raise RuntimeError('Design or code changed: use a new output phase directory, never mix runs.')
    else: designpath.write_text(json.dumps(design,indent=2))
    jobs=[(c,p,seed,warmup,days,str(out)) for seed in design['seeds'] for c in chosen for p in POLICIES if not (out/f'{c["name"]}__{p}__{seed}.json').exists()]
    if args.limit: jobs=jobs[:args.limit]
    print(f'{args.phase}: {len(jobs)} pending, {args.workers} workers',flush=True)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=base.initialize) as pool:
        for i,f in enumerate(as_completed([pool.submit(job,j) for j in jobs]),1):
            print(i,*f.result(),flush=True)
    print('COMPLETE',flush=True)

if __name__=='__main__': main()
