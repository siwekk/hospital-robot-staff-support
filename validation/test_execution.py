import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from copy import deepcopy
import pytest
import run_study as base
from run_workflows import config
from staff_simulation import StaffSimulation
from workflow_simulation import WorkflowSimulation
from hospital_sim.entities import DeliveryTask,SupportAssignment

@pytest.fixture(autouse=True)
def initialize(): base.initialize()

def case(mode='mobile',load=0,lag=0):
    return dict(name='test',mode=mode,background_fraction=load,information_lag=lag)

def test_zero_background_preserves_mobile_baseline():
    cfg=config(case(),'human_only',1,2)
    original=StaffSimulation(deepcopy(cfg),base.PARAMETERS,seed=104001).run()
    extended=WorkflowSimulation(deepcopy(cfg),base.PARAMETERS,seed=104001).run()
    for key in ['created','completed','late','total_cycle_minutes','human_transport_minutes','human_utilization']:
        assert extended[key]==pytest.approx(original[key]),key

@pytest.mark.parametrize('mode',['mobile','local','mixed'])
def test_human_baseline_conserves_requests_and_staff_time(mode):
    cfg=config(case(mode,.8),'human_only',1,2)
    sim=WorkflowSimulation(cfg,base.PARAMETERS,seed=104002)
    out=sim.run()
    assert out['created']>0
    assert out['incomplete']==0
    assert out['robot_completed']==0
    assert 0<=out['human_utilization']<=1
    assert out['mobile_staff_minutes']==pytest.approx((8+30+24)*8*60*2)
    assert out['local_transport_and_support_minutes']==0
    assert out['local_staff_minutes']==(0 if mode=='mobile' else 95*2*1440)

def test_busy_local_staff_causes_wait_and_does_not_use_mobile_staff():
    cfg=config(case('local'),'human_only',0,1)
    cfg['workflow']['nodes']=['2624']
    sim=WorkflowSimulation(cfg,base.PARAMETERS,seed=104003)
    sim._start_human_shifts(1440)
    sim.env.run(until=.1)
    # Two simultaneous local operations require serial service by one worker.
    task1=DeliveryTask(1,.1,'supply','2624','2624',1,20,2,1)
    task2=DeliveryTask(2,.1,'supply','2624','2624',1,20,2,1)
    sim.env.process(sim._request_human_support(task1,2,'receiving'))
    sim.env.process(sim._request_human_support(task2,2,'receiving'))
    sim.env.run(until=5)
    assert len(sim.support_log)==2
    assert all(e['group']=='local' for e in sim.support_log)
    assert sorted(e['queue_wait'] for e in sim.support_log)==pytest.approx([0,2])
    assert sim.busy_minutes['mobile']==0
