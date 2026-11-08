"""Execution and forecasting for mobile, local, and mixed support workflows."""
from dataclasses import replace
from random import Random
from time import perf_counter
import hashlib
import heapq
from bisect import bisect_right
import numpy as np
from forecast import Worker, Job, rollout
from staff_simulation import StaffSimulation
from hospital_sim.entities import SupportAssignment
from schedule_optimizer import optimize

PHASE={'loading_coordination_recovery':'load','receiving':'receive','decontamination':'clean'}

class WorkflowSimulation(StaffSimulation):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.workflow=self.config['workflow']
        self.local_nodes=self.workflow['nodes']
        self.bg_intervals={}
        self.worker_history={}
        self.worker_locations={}
        self.support_log=[]
        self.optimizer_log=[]
        self.optimizer_failures=0
        self.optimizer_failure_reasons={}
        self.optimizer_attempt_counts={}
        self.optimizer_method_counts={}
        self.optimizer_retry_recoveries=0
        self._initialize_execution_records()

    def _record_optimization(self,result):
        attempts=optimize.last_attempts
        for attempt in attempts:
            key=f"{attempt['stage']}:{attempt['limit_seconds']:g}s:{attempt['status']}"
            self.optimizer_attempt_counts[key]=self.optimizer_attempt_counts.get(key,0)+1
        if result is not None:
            method=result.diagnostic.get('method','exact_or_empty')
            self.optimizer_method_counts[method]=self.optimizer_method_counts.get(method,0)+1
            if sum(a['stage']=='primary' for a in attempts)>1:
                self.optimizer_retry_recoveries+=1

    def _initialize_execution_records(self):
        self.scheduler_calls=0
        self.task_registry={}
        self.dispatching=False
        self.pending_wake=None
        self.background_minutes={'mobile':0.,'local':0.}
        self.planned_background_minutes={'mobile':0.,'local':0.}
        self.overtime_minutes={'mobile':0.,'local':0.}
        self.busy_minutes={'mobile':0.,'local':0.}
        self.staff_minutes={'mobile':0.,'local':0.}

    def _local_phase(self,phase):
        mode=self.workflow['mode']
        return phase!='human' and (mode=='local' or (mode=='mixed' and phase=='receive'))

    def _eligible(self,worker,job):
        local=worker.identity.startswith('local:')
        if local!=self._local_phase(job.phase): return False
        node=job.task.origin if job.phase in {'human','load'} else job.task.destination
        return not local or worker.location==node

    def _calendar(self,identity,start,end):
        # Independent exogenous stream. A fixed cycle has a random phase per
        # worker; unavailable fractions are controlled, not policy dependent.
        fraction=self.workflow['background_fraction']
        if fraction==0: return []
        digest=int(hashlib.sha256(f'{self.seed}:{identity}'.encode()).hexdigest()[:12],16)
        phase=Random(digest).uniform(0,30)
        spans=[]
        left=start-phase
        while left<end:
            a,b=max(start,left),min(end,left+30*fraction)
            if b>a: spans.append((a,b))
            left+=30
        return spans

    def _blocked_until(self,identity,now):
        # Only execution uses the calendar. Forecasts see current status and an
        # expected residual, never the next exogenous interval.
        for a,b in self.bg_intervals.get(identity,[]):
            if a<=now<b: return b
            if a>now: break
        return now

    def _record_worker(self,identity):
        now=self.env.now
        start,end=self.worker_schedule[identity]
        if identity in self.available_humans:
            location=self.available_humans[identity][0]
            available=now
        elif identity in self.busy_forecasts:
            available,location,_,_=self.busy_forecasts[identity]
            available=max(now+1,available)
        else:
            location=self.worker_locations.get(identity,self._initial_location(identity))
            available=now
        if self._blocked_until(identity,now)>now:
            available=max(available,now+15*self.workflow['background_fraction'])
        self.worker_history.setdefault(identity,[]).append((now,Worker(identity,str(location),available,end)))

    def _initial_location(self,identity):
        return identity.split(':',1)[1] if identity.startswith('local:') else str(self.config['hospital']['human_initial_node'])

    def _location_aware_human_worker(self,start,end,worker_id):
        self.worker_schedule[worker_id]=(start,end)
        self.bg_intervals[worker_id]=self._calendar(worker_id,start,end)
        if start>self.env.now: yield self.env.timeout(start-self.env.now)
        group='local' if worker_id.startswith('local:') else 'mobile'
        self.planned_background_minutes[group]+=sum(max(0,min(b,self.measurement_end)-max(a,self.measurement_start)) for a,b in self.bg_intervals[worker_id])
        staffed=max(0,min(end,self.measurement_end)-max(start,self.measurement_start))
        self.staff_minutes[group]+=staffed
        if group=='mobile':
            if staffed>0: self.staffed_intervals.append((worker_id,max(start,self.measurement_start),min(end,self.measurement_end)))
            self.active_human_workers+=1
        location=self._initial_location(worker_id)
        while self.env.now<end:
            self.worker_locations[worker_id]=location
            blocked=self._blocked_until(worker_id,self.env.now)
            if blocked>self.env.now:
                self.background_minutes[group]+=max(0,min(blocked,self.measurement_end)-max(self.env.now,self.measurement_start))
                self._record_worker(worker_id)
                yield self.env.timeout(blocked-self.env.now)
                continue
            ready=self.env.event()
            self.available_humans[worker_id]=(location,ready)
            self._record_worker(worker_id)
            self._dispatch_nearest_human()
            next_bg=next((a for a,b in self.bg_intervals[worker_id] if a>self.env.now),end)
            wake=min(end,next_bg)
            events=yield ready | self.env.timeout(max(0,wake-self.env.now))
            if ready not in events:
                self.available_humans.pop(worker_id,None)
                continue
            assignment=ready.value
            t=assignment.task
            started=self.env.now
            if group=='mobile': self.active_human_assignments[worker_id]=started
            support=isinstance(assignment,SupportAssignment)
            node=self._support_node(assignment) if support else t.origin
            travel=0.
            if location!=node:
                planned=self._travel_minutes(location,node,robot=False)
                travel=yield from self._execute_route(location,node,planned,measured=t.created_at>=self.measurement_start)
            location=node
            if support:
                service_start=self.env.now
                yield self.env.timeout(assignment.duration_minutes)
                if t.created_at>=self.measurement_start:
                    self.metrics.human_support_tasks+=1
                    self.metrics.human_support_minutes+=assignment.duration_minutes
                    self.metrics.human_support_travel_minutes+=travel
                    self.metrics.human_support_wait_minutes+=service_start-assignment.queued_at
                    self.metrics.human_empty_travel_minutes+=travel
                    self.support_log.append({'task_id':t.task_id,'phase':PHASE[assignment.support_kind],
                        'group':group,'queue_wait':started-assignment.queued_at,'approach':travel,
                        'service':assignment.duration_minutes})
            else:
                actual=yield from self._execute_transport(t,self._manual_duration(t))
                location=t.destination
                if t.created_at>=self.measurement_start:
                    self.metrics.human_completed+=1
                    self.metrics.human_transport_minutes+=actual+travel
                    self.metrics.human_empty_travel_minutes+=travel
                self._complete(t,'human',started,actual+travel,worker_id)
            busy=max(0,min(self.env.now,self.measurement_end)-max(started,self.measurement_start))
            self.busy_minutes[group]+=busy
            self.overtime_minutes[group]+=max(0,min(self.env.now,self.measurement_end)-max(started,end,self.measurement_start))
            if group=='mobile':
                if busy>0: self.human_busy_intervals.append((worker_id,max(started,self.measurement_start),min(self.env.now,self.measurement_end)))
                self.active_human_assignments.pop(worker_id,None)
                self.busy_human_workers-=1
            self.busy_forecasts.pop(worker_id,None)
            assignment.completed.succeed()
        self.available_humans.pop(worker_id,None)
        self.worker_schedule.pop(worker_id,None)
        self.busy_forecasts.pop(worker_id,None)
        if group=='mobile': self.active_human_workers-=1

    def _start_human_shifts(self,total_minutes):
        super()._start_human_shifts(total_minutes)
        if self.workflow['mode']!='mobile':
            for node in self.local_nodes:
                self.env.process(self._location_aware_human_worker(0,total_minutes+1440,'local:'+str(node)))

    def _snapshot(self):
        workers,jobs,preset=super()._snapshot()
        now=self.env.now
        represented={w.identity for w in workers}
        for identity,(start,end) in self.worker_schedule.items():
            if identity not in represented and start<=now<end:
                workers.append(Worker(identity,self.worker_locations.get(identity,self._initial_location(identity)),now,end))
        lag=self.workflow['information_lag']
        observed=[]
        for w in workers:
            history=self.worker_history.get(w.identity,[])
            if not history:
                observed.append(w)
                continue
            report_index=bisect_right(history,now-lag,key=lambda entry:entry[0]) if lag else 0
            if lag and report_index:
                old=history[report_index-1][1]
                observed.append(replace(old,available=max(now,old.available)))
            elif lag:
                # Before the first report, use the initial location and assume
                # availability, rather than access a more recent report.
                observed.append(replace(w,location=self._initial_location(w.identity),available=now))
            else:
                available=w.available
                if self._blocked_until(w.identity,now)>now:
                    available=max(available,now+15*self.workflow['background_fraction'])
                observed.append(replace(w,available=available))
        return observed,jobs,preset

    def _options(self):
        return dict(travel=self._forecast_travel,coordination=self._expected_coordination(),
            cleaning=float(self.config['robots'].get('decontamination_human_minutes',0)),
            cleaning_types=self._cleaning_types(),eligible=self._eligible,
            support_scale=float(self.config['robots'].get('support_multiplier',1.)))

    def _evaluate(self,task,robot,snapshot,ignore_support=False):
        workers,jobs,preset=snapshot
        jobs=list(jobs)
        release=self.env.now
        if robot is not None:
            pickup=self._forecast_travel(str(robot['location']),task.origin,True)
            r=self.config['robots']
            energy=(pickup+self._deterministic_robot_duration(task))*r['energy_kwh_per_active_minute']
            if energy>r['battery_capacity_kwh']: return None
            charge=0.
            if energy>robot['battery_kwh']:
                charge=(r['battery_capacity_kwh']-robot['battery_kwh'])/r['charging_power_kw']/r['charging_efficiency']*60
                charge*=1+len(self.chargers.queue)/self.chargers.capacity
            release+=pickup+charge
        jobs.append(Job(task,'human' if robot is None else 'load',release,self.queue_counter+1))
        if self.config['scenario']['policy']=='optimizer':
            result=optimize(workers,jobs,preset=preset,now=self.env.now,
                time_limit=self.workflow['solver_seconds'],retry_limits=self.workflow.get('solver_retry_seconds',[5.,20.]),**self._options())
            self._record_optimization(result)
            if result is not None:
                self.optimizer_log.append(result.diagnostic)
                return result
            self.optimizer_failures+=1
            reason=optimize.last_failure or 'UNSPECIFIED'
            self.optimizer_failure_reasons[reason]=self.optimizer_failure_reasons.get(reason,0)+1
        return rollout(workers,jobs,preset=preset,ignore_support=ignore_support,**self._options())

    def _robot_eligible(self,task):
        self.task_registry[task.task_id]=task
        if self.config['scenario']['policy']!='optimizer': return super()._robot_eligible(task)
        if not self.robot_units.items: return False
        start=perf_counter()
        snapshot=self._snapshot()
        best=self._evaluate(task,None,snapshot)
        selected=None
        for robot in sorted(self.robot_units.items,key=lambda r:r['robot_id']):
            result=self._evaluate(task,robot,snapshot)
            if result is not None and result.score()<best.score(): best,selected=result,robot
        if selected is not None:
            self.selected_robot[task.task_id]=selected['robot_id']
            self.admitted+=int(task.created_at>=self.measurement_start)
        self.predictions[task.task_id]=best.completions[task.task_id]
        if task.created_at>=self.measurement_start:
            self.decision_count+=1
            self.decision_times.append(perf_counter()-start)
        return selected is not None

    def _dispatch_nearest_human(self):
        if self.dispatching: return
        self.dispatching=True
        try:
            now=self.env.now
            for identity in list(self.available_humans):
                if self.worker_schedule.get(identity,(0,0))[1]<=now:
                    self.available_humans.pop(identity,None)
            plan={}
            # Reorder ready work only when a genuine scheduling choice exists.
            # Future release reservations are advisory, never block an otherwise
            # eligible worker. Every completion/arrival triggers reconsideration.
            if self.config['scenario']['policy']=='optimizer' and len(self.human_queue.items)>1 and self.available_humans:
                workers,jobs,preset=self._snapshot()
                result=optimize(workers,jobs,preset=preset,now=now,
                    time_limit=self.workflow['solver_seconds'],retry_limits=self.workflow.get('solver_retry_seconds',[5.,20.]),**self._options())
                self._record_optimization(result)
                self.scheduler_calls+=1
                if result is not None:
                    plan=result.plan
                    self.optimizer_log.append(result.diagnostic)
                else:
                    self.optimizer_failures+=1
                    reason=optimize.last_failure or 'UNSPECIFIED'
                    self.optimizer_failure_reasons[reason]=self.optimizer_failure_reasons.get(reason,0)+1
            while self.available_humans and self.human_queue.items:
                candidates=[]
                for item in sorted(self.human_queue.items):
                    _,_,order,a=item
                    phase=PHASE[a.support_kind] if isinstance(a,SupportAssignment) else 'human'
                    job=Job(a.task,phase,now,order)
                    ids=[i for i,(loc,event) in self.available_humans.items()
                         if self._blocked_until(i,now)<=now and self._eligible(Worker(i,str(loc),now,self.worker_schedule[i][1]),job)]
                    if not ids: continue
                    node=a.task.origin if phase in {'human','load'} else a.task.destination
                    planned=plan.get((a.task.task_id,phase))
                    identity=(planned[0] if planned and planned[0] in ids else min(ids,key=lambda i:(self._deterministic_travel_minutes(str(self.available_humans[i][0]),node,robot=False),i)))
                    rank=(planned[1] if planned else float('inf'),item[:3]) if plan else (0,item[:3])
                    candidates.append((rank,item,identity,node))
                if not candidates: break
                _,item,identity,node=min(candidates,key=lambda x:x[0])
                self.human_queue.items.remove(item)
                heapq.heapify(self.human_queue.items)
                _,_,order,a=item
                location,ready=self.available_humans.pop(identity)
                duration=self._forecast_travel(str(location),node,False)
                duration+=(self._support_expectation(a) if isinstance(a,SupportAssignment) else self._forecast_travel(a.task.origin,a.task.destination,False)+a.task.loading_minutes+a.task.receiving_minutes)
                self.busy_forecasts[identity]=(now+duration,node if isinstance(a,SupportAssignment) else a.task.destination,a,order)
                if not identity.startswith('local:'): self.busy_human_workers+=1
                self._record_worker(identity)
                ready.succeed(a)
        finally: self.dispatching=False

    def run(self):
        result=super().run()
        incomplete=[t for i,t in self.task_registry.items() if i in self.measurement_task_ids and i not in self.completed_task_ids]
        result['weighted_tardiness_per_request']+=sum((4 if t.priority==1 else 1)*max(0,self.env.now-t.due_at) for t in incomplete)/max(1,result['created'])
        result['tardiness_is_lower_bound']=bool(incomplete)
        for group in ('mobile','local'):
            result[group+'_staff_minutes']=self.staff_minutes[group]
            result[group+'_background_minutes']=self.background_minutes[group]
            result[group+'_planned_background_minutes']=self.planned_background_minutes[group]
            result[group+'_displaced_background_minutes']=max(0,self.planned_background_minutes[group]-self.background_minutes[group])
            result[group+'_overtime_minutes']=self.overtime_minutes[group]
            result[group+'_transport_and_support_minutes']=self.busy_minutes[group]
            logs=[x for x in self.support_log if x['group']==group]
            for field in ('queue_wait','approach','service'):
                result[group+'_support_'+field]=sum(x[field] for x in logs)
            for phase in ('load','receive','clean'):
                result[group+'_'+phase+'_service']=sum(x['service'] for x in logs if x['phase']==phase)
        result['optimizer_failures']=self.optimizer_failures
        result['optimizer_failure_reasons']=self.optimizer_failure_reasons
        result['optimizer_attempt_counts']=self.optimizer_attempt_counts
        result['optimizer_method_counts']=self.optimizer_method_counts
        result['optimizer_retry_recoveries']=self.optimizer_retry_recoveries
        result['optimizer_time_limits_seconds']=[self.workflow['solver_seconds']]+self.workflow.get('solver_retry_seconds',[])
        result['optimizer_solves']=len(self.optimizer_log)
        result['optimizer_certified_primary_fraction']=sum(x['status']=='OPTIMAL' for x in self.optimizer_log)/max(1,len(self.optimizer_log))
        result['optimizer_max_primary_gap_ticks']=max([x.get('primary_gap_ticks',0) for x in self.optimizer_log] or [0])
        result['optimizer_seconds']=sum(x['seconds'] for x in self.optimizer_log)
        result['scheduler_calls']=self.scheduler_calls
        result['total_staff_work_minutes']=sum(self.busy_minutes.values())
        return result
