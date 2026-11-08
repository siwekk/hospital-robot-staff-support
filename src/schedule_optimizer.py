"""Bounded CP-SAT scheduling of known work, without future random information.

Times use hundredths of a minute. Each worker follows a circuit through assigned
operations. Travel starts only after an operation is released. Robot missions
already admitted retain their mode; a new request is evaluated in each mode.
"""
from math import ceil
from time import perf_counter
from ortools.sat.python import cp_model
from forecast import Forecast, Job, rollout
from dataclasses import replace

def solve_with_retries(model,limits,stage):
    attempts=[]
    for limit in limits:
        solver=cp_model.CpSolver()
        solver.parameters.max_time_in_seconds=limit
        solver.parameters.num_search_workers=1
        solver.parameters.random_seed=0
        began=perf_counter()
        status=solver.solve(model)
        attempts.append(dict(stage=stage,limit_seconds=limit,status=solver.status_name(status),
                             wall_seconds=perf_counter()-began))
        if status==cp_model.MODEL_INVALID: raise RuntimeError(model.validate())
        if status!=cp_model.UNKNOWN: return solver,status,attempts
    return solver,status,attempts

def single_chain(workers,job,*,travel,coordination,cleaning,cleaning_types,eligible,preset,support_scale):
    """Exact enumeration for a single chain; no integer solver is needed."""
    t=job.task
    phase=job.phase
    phases=([phase,'receive'] if phase=='load' else [phase])
    if phase in {'load','receive'} and t.task_type in cleaning_types and cleaning>0: phases.append('clean')
    best=None
    def visit(ws,index,release,plan,completion,burden):
        nonlocal best
        if index==len(phases):
            key=(completion if completion is not None else release,burden)
            if best is None or key<best[0]: best=(key,plan,completion,burden)
            return
        ph=phases[index]
        node=t.origin if ph in {'human','load'} else t.destination
        j=Job(t,ph,release,job.order)
        duration=(t.loading_minutes+travel(t.origin,t.destination,False)+t.receiving_minutes if ph=='human'
                  else support_scale*{'load':t.loading_minutes+coordination,'receive':t.receiving_minutes,'clean':cleaning}[ph])
        candidates=[]
        for k,w in enumerate(ws):
            start=max(release,w.available)
            if eligible(w,j) and start<w.shift_end:
                approach=travel(w.location,node,False)
                candidates.append((start+approach+duration,k,start,approach))
        # The final phase has no downstream resource effects.
        if index==len(phases)-1: candidates=sorted(candidates)[:1]
        for end,k,start,approach in candidates:
            if best is not None and ph=='load' and end>best[0][0]: continue
            w=ws[k]
            updated=list(ws)
            updated[k]=replace(w,location=t.destination if ph=='human' else node,available=end)
            next_release=end+(travel(t.origin,t.destination,True) if ph=='load' else 0)
            visit(updated,index+1,next_release,dict(plan,**{}) | {(t.task_id,ph):(w.identity,start)},
                  end if ph in {'human','receive'} else completion,burden+approach+duration)
    visit(workers,0,job.release,{},None,0.)
    if best is None: return None
    completions={i:time for i,(_,time) in (preset or {}).items()}
    tasks={i:task for i,(task,_) in (preset or {}).items()}
    if best[2] is not None: completions[t.task_id]=best[2]; tasks[t.task_id]=t
    out=Forecast(completions,tasks,best[3])
    out.plan=best[1]
    out.diagnostic={'status':'OPTIMAL','method':'exact_single_chain','primary_gap_ticks':0.,'seconds':0.,'operations':len(phases)}
    return out

def optimize(workers, jobs, *, travel, coordination, cleaning, cleaning_types,
             eligible, preset=None, support_scale=1., now=0., time_limit=1., retry_limits=(5.,20.)):
    started = perf_counter()
    optimize.last_failure=None
    optimize.last_attempts=[]
    # At most three operations exist per input job. Workers with the same
    # location, shift end, and eligibility are interchangeable; retaining that
    # many earliest releases removes only dominated duplicate capacity.
    signatures=[]
    for j in jobs:
        signatures.extend(Job(j.task,p,j.release,j.order) for p in ('human','load','receive','clean'))
    groups={}
    for w in workers:
        key=(w.location,w.shift_end,tuple(eligible(w,j) for j in signatures))
        groups.setdefault(key,[]).append(w)
    workers=[w for group in groups.values() for w in sorted(group,key=lambda w:(w.available,w.identity))[:max(1,3*len(jobs))]]
    if len(jobs)==1:
        out=single_chain(workers,jobs[0],travel=travel,coordination=coordination,cleaning=cleaning,
            cleaning_types=cleaning_types,eligible=eligible,preset=preset,support_scale=support_scale)
        if out is not None: out.diagnostic['seconds']=perf_counter()-started
        else: optimize.last_failure='NO_ELIGIBLE_CHAIN'
        return out
    ops = []
    links = []
    for job in jobs:
        first = len(ops)
        ops.append(job)
        if job.phase == 'load':
            ops.append(Job(job.task, 'receive', now, job.order))
            links.append((first, first+1, travel(job.task.origin, job.task.destination, True)))
        if job.phase in {'load', 'receive'} and job.task.task_type in cleaning_types and cleaning > 0:
            previous = len(ops)-1
            ops.append(Job(job.task, 'clean', now, job.order))
            links.append((previous, len(ops)-1, 0.))
    completed = {i: t for i, (_, t) in (preset or {}).items()}
    tasks = {i: t for i, (t, _) in (preset or {}).items()}
    if not ops:
        out = Forecast(completed, tasks, 0.)
        out.plan, out.diagnostic = {}, {'status':'EMPTY', 'seconds':0., 'primary_gap_ticks':0.}
        return out
    tick = lambda x: int(ceil(max(0., x)*100-1e-8))
    release = [tick(j.release-now) for j in ops]
    duration, pickup, endpoint = [], [], []
    for j in ops:
        t = j.task
        pickup.append(t.origin if j.phase in {'human','load'} else t.destination)
        endpoint.append(t.destination if j.phase == 'human' else pickup[-1])
        d = (t.loading_minutes + travel(t.origin,t.destination,False) + t.receiving_minutes
             if j.phase == 'human' else support_scale * {'load':t.loading_minutes+coordination,
                 'receive':t.receiving_minutes, 'clean':cleaning}[j.phase])
        duration.append(tick(d))
        tasks[t.task_id] = t
    horizon = tick(max([1440.] + [w.available-now for w in workers])) + sum(duration) + tick(1440.)
    model = cp_model.CpModel()
    starts = [model.new_int_var(release[i],horizon,f's{i}') for i in range(len(ops))]
    ends = [model.new_int_var(0,horizon,f'e{i}') for i in range(len(ops))]
    for a,b,lag in links:
        model.add(starts[b] >= ends[a]+tick(lag))
    choices = [[] for _ in ops]
    assignment = {}
    incumbent=rollout(workers,jobs,travel=travel,coordination=coordination,cleaning=cleaning,
        cleaning_types=cleaning_types,eligible=eligible,preset=preset,support_scale=support_scale)
    incumbent_plan=incumbent.plan
    for k,w in enumerate(workers):
        candidates = [i for i,j in enumerate(ops) if eligible(w,j) and max(j.release,w.available)<w.shift_end]
        if not candidates:
            continue
        arcs = []
        empty = model.new_bool_var(f'empty{k}')
        arcs.append((0,0,empty))
        sequence=sorted([i for i in candidates if incumbent_plan.get((ops[i].task.task_id,ops[i].phase),('',0))[0]==w.identity],
            key=lambda i:incumbent_plan[ops[i].task.task_id,ops[i].phase][1])
        model.add_hint(empty,int(not sequence))
        for position,i in enumerate(candidates,1):
            x = model.new_bool_var(f'x{k}_{i}')
            assignment[k,i] = x
            model.add_hint(x,int(i in sequence))
            choices[i].append(x)
            arcs.append((position,position,x.Not()))
            first = model.new_bool_var(f'first{k}_{i}')
            last = model.new_bool_var(f'last{k}_{i}')
            model.add_hint(first,int(bool(sequence) and i==sequence[0]))
            model.add_hint(last,int(bool(sequence) and i==sequence[-1]))
            arcs.extend([(0,position,first),(position,0,last)])
            model.add_implication(first,x)
            model.add_implication(last,x)
            model.add(starts[i]>=tick(w.available-now)).only_enforce_if(x)
            model.add(starts[i]<=tick(w.shift_end-now)-1).only_enforce_if(x)
            approach = tick(travel(w.location,pickup[i],False))
            model.add(ends[i]==starts[i]+approach+duration[i]).only_enforce_if(first)
        for a,i in enumerate(candidates,1):
            for b,j in enumerate(candidates,1):
                if i==j: continue
                arc=model.new_bool_var(f'a{k}_{i}_{j}')
                model.add_hint(arc,int(any(a==i and b==j for a,b in zip(sequence,sequence[1:]))))
                arcs.append((a,b,arc))
                model.add_implication(arc,assignment[k,i])
                model.add_implication(arc,assignment[k,j])
                model.add(starts[j]>=ends[i]).only_enforce_if(arc)
                approach=tick(travel(endpoint[i],pickup[j],False))
                model.add(ends[j]==starts[j]+approach+duration[j]).only_enforce_if(arc)
        model.add_circuit(arcs)
    if any(not c for c in choices):
        optimize.last_failure='NO_ELIGIBLE_OPERATION'
        return None
    for c in choices: model.add_exactly_one(c)
    tardiness, flow, final_ops = [], [], {}
    for i,j in enumerate(ops):
        if j.phase not in {'human','receive'}: continue
        late=model.new_int_var(0,horizon+tick(now),f't{i}')
        # Due times may precede the current decision.
        due=int(round((j.task.due_at-now)*100))
        model.add_max_equality(late,[0,ends[i]-due])
        tardiness.append((4 if j.task.priority==1 else 1)*late)
        flow.append(ends[i])
        final_ops[j.task.task_id]=i
    primary=sum(tardiness)
    model.minimize(primary)
    limits=sorted(set([float(time_limit)]+[float(x) for x in retry_limits if x>time_limit]))
    solver,status,attempts=solve_with_retries(model,limits,'primary')
    optimize.last_attempts=list(attempts)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        optimize.last_failure=solver.status_name(status)
        return None
    value=solver.objective_value
    bound=solver.best_objective_bound
    primary_status=solver.status_name(status)
    # Second objective is solved only after the first is certified optimal.
    if status==cp_model.OPTIMAL and flow:
        saved_solver=solver
        model.add(primary==int(round(value)))
        model.minimize(sum(flow))
        solver,status,secondary_attempts=solve_with_retries(model,[time_limit],'secondary')
        attempts.extend(secondary_attempts)
        optimize.last_attempts=list(attempts)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE): solver=saved_solver
    plan={}
    for (k,i),x in assignment.items():
        if solver.value(x):
            j=ops[i]
            plan[j.task.task_id,j.phase]=(workers[k].identity,now+solver.value(starts[i])/100)
    for task_id,i in final_ops.items(): completed[task_id]=now+solver.value(ends[i])/100
    out=Forecast(completed,tasks,0.)
    out.plan=plan
    out.diagnostic={'status':primary_status,'method':'cp_sat','attempts':attempts,'primary_objective_ticks':value,
                    'primary_bound_ticks':bound,'primary_gap_ticks':value-bound,
                    'seconds':perf_counter()-started,'operations':len(ops)}
    return out
