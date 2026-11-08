from dataclasses import replace
from itertools import permutations
import pytest
from forecast import Worker,Job,rollout
from hospital_sim.entities import DeliveryTask
from schedule_optimizer import optimize
from workflow_simulation import WorkflowSimulation
import run_study as base
from run_workflows import config

def task(i=1,deadline=20): return DeliveryTask(i,0,'supply','a','b',1,deadline,2,1)
def travel(a,b,robot): return 0 if a==b else 10
def options(): return dict(travel=travel,coordination=1,cleaning=0,cleaning_types=set(),eligible=lambda w,j:True)

def test_optimizer_matches_exhaustive_single_worker():
    jobs=[Job(task(i,d),'human',0,i) for i,d in [(1,14),(2,40),(3,21)]]
    worker=Worker('w','a',0,1000)
    best=float('inf')
    for seq in permutations(jobs):
        now=0; location='a'; loss=0
        for j in seq:
            now+=travel(location,'a',False)+13
            location='b'
            loss+=4*max(0,now-j.task.due_at)
        best=min(best,loss)
    out=optimize([worker],jobs,now=0,time_limit=2,**options())
    assert out is not None
    assert out.score()[0]==pytest.approx(best)
    assert out.diagnostic['primary_gap_ticks']==0

def test_local_support_never_uses_mobile_or_other_location():
    t=task()
    workers=[Worker('mobile','a',0,100),Worker('local:a','a',5,100),Worker('local:b','b',0,100)]
    opts=options()
    opts['eligible']=lambda w,j:w.identity=='local:'+(j.task.origin if j.phase=='load' else j.task.destination)
    f=rollout(workers,[Job(t,'load',0,1)],**opts)
    opt=optimize(workers,[Job(t,'load',0,1)],time_limit=2,**opts)
    assert f.completions[1]==19
    assert opt.completions[1]==19
    assert opt.plan[1,'load'][0]=='local:a'
    assert opt.plan[1,'receive'][0]=='local:b'

def test_optimizer_respects_worker_shift_start_and_end():
    out=optimize([Worker('w','a',30,31)],[Job(task(),'human',0,1)],time_limit=2,**options())
    assert out.completions[1]==43

@pytest.fixture
def model():
    base.initialize()
    case=dict(name='test',mode='local',background_fraction=.4,information_lag=0)
    cfg=config(case,'staff_rollout',0,.1)
    cfg['workflow']['nodes']=['2624']
    return WorkflowSimulation(cfg,base.PARAMETERS,seed=111)

def test_calendar_reproducible_and_not_policy_dependent(model):
    a=model._calendar('local:2624',0,120)
    model.config['scenario']['policy']='optimizer'
    assert a==model._calendar('local:2624',0,120)
    assert all(0<=l<r<=120 for l,r in a)

def test_forecasting_does_not_consume_randomness(model):
    model._start_human_shifts(1440)
    model.env.run(until=1)
    t=DeliveryTask(1,1,'specimen','2624','2624',1,25,1,.8)
    before=(model.rng.getstate(),model.demand_rng.getstate(),list(model.human_queue.items))
    f=model._evaluate(t,model.robot_units.items[0],model._snapshot())
    assert f is not None
    assert before==(model.rng.getstate(),model.demand_rng.getstate(),list(model.human_queue.items))

def test_delayed_report_does_not_use_current_location(model):
    model.workflow['information_lag']=10
    model._start_human_shifts(1440)
    model.env.run(until=20)
    identity=next(i for i in model.worker_schedule if not i.startswith('local:') and i in model.worker_history)
    old=Worker(identity,'2624',0,1000)
    model.worker_history[identity]=[(0,old),(19,replace(old,location='unobserved'))]
    workers,_,_=model._snapshot()
    assert next(w for w in workers if w.identity==identity).location=='2624'
