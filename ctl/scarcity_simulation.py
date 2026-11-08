"""Unattended receiving on top of the frozen workflow model. ../src is not modified.

With config["robots"]["unattended_receiving"] = True a robot completes a delivery by depositing the
load in a secure receptacle at the destination: the receiving phase takes receiving_minutes of robot
dwell (times support_multiplier) and needs no worker. Loading and cleaning still require staff.
The forecast treats receiving the same way (no worker occupation, no approach travel). The source
metric robot_human_burden_minutes counts receiving_minutes for every robot mission; the minutes that
no person spent are subtracted again and net_released_minutes is corrected accordingly.

With the flag absent or False the class behaves exactly as ExtraSimulation.
"""
from dataclasses import replace

from forecast import Forecast, Job, rollout
from extra_simulation import ExtraSimulation


def rollout_unattended(workers, jobs, *, travel, coordination, cleaning, cleaning_types, ignore_support=False,
                       preset=None, support_scale=1.0, eligible=None):
    """Copy of forecast.rollout in which receiving is autonomous; with ignore_support all support is."""
    eligible = eligible or (lambda worker, job: True)
    auto = {"load", "receive", "clean"} if ignore_support else {"receive"}
    workers = list(workers)
    pending = list(jobs)
    completed = {i: time for i, (_, time) in (preset or {}).items()}
    tasks = {i: task for i, (task, _) in (preset or {}).items()}
    human_minutes = 0.0
    plan = {}

    def finish(job, when):
        task = job.task
        tasks[task.task_id] = task
        if job.phase == "load":
            pending.append(Job(task, "receive", when + travel(task.origin, task.destination, True), job.order))
        elif job.phase in {"human", "receive"}:
            completed[task.task_id] = when
            if job.phase == "receive" and task.task_type in cleaning_types and cleaning > 0:
                pending.append(Job(task, "clean", when, job.order))

    while pending:
        times = [max(job.release, worker.available)
                 for job in pending for worker in workers
                 if job.phase not in auto and eligible(worker, job) and max(job.release, worker.available) < worker.shift_end]
        times.extend(job.release for job in pending if job.phase in auto)
        if not times:
            for job in pending:
                if job.phase != "clean":
                    completed[job.task.task_id] = max(job.release, job.task.due_at) + 1440.0
                    tasks[job.task.task_id] = job.task
            break
        now = min(times)
        ready = [job for job in pending if job.release <= now + 1e-9
                 and (job.phase in auto or any(eligible(w, job) and w.available <= now + 1e-9 and now < w.shift_end for w in workers))]
        job = min(ready, key=lambda j: (j.task.priority, j.task.due_at, j.order,
                                       {"human": 0, "load": 1, "receive": 2, "clean": 3}[j.phase]))
        task = job.task
        node = task.origin if job.phase in {"human", "load"} else task.destination
        duration = {"load": task.loading_minutes + coordination,
                    "receive": task.receiving_minutes, "clean": cleaning}.get(job.phase)
        if job.phase == "human":
            duration = task.loading_minutes + travel(task.origin, task.destination, False) + task.receiving_minutes
        else:
            duration *= support_scale
        if job.phase in auto:
            pending.remove(job)
            finish(job, now + duration)
            continue
        idle = [k for k, w in enumerate(workers) if eligible(w, job) and w.available <= now + 1e-9 and now < w.shift_end]
        if not idle:
            raise RuntimeError("Forecast reached a release without a worker")
        k = min(idle, key=lambda k: (travel(workers[k].location, node, False), workers[k].identity))
        worker = workers[k]
        plan[task.task_id, job.phase] = (worker.identity, now)
        pickup = travel(worker.location, node, False)
        end = now + pickup + duration
        end_node = task.destination if job.phase == "human" else node
        workers[k] = replace(worker, location=end_node, available=end)
        human_minutes += pickup + duration
        pending.remove(job)
        finish(job, end)
    result = Forecast(completed, tasks, human_minutes)
    result.plan = plan
    return result


class ScarcitySimulation(ExtraSimulation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unattended = bool(self.config["robots"].get("unattended_receiving", False))
        self.unattended_receive_minutes = 0.0
        self.unattended_receive_count = 0
        if self.unattended and self.config["scenario"]["policy"] == "optimizer":
            raise ValueError("Unattended receiving is not implemented for the optimizer")

    def _request_human_support(self, task, duration_minutes, support_kind):
        if not (self.unattended and support_kind == "receiving"):
            return (yield from super()._request_human_support(task, duration_minutes, support_kind))
        dwell = duration_minutes * float(self.config["robots"].get("support_multiplier", 1.0))
        if dwell > 0:
            yield self.env.timeout(dwell)
        if task.created_at >= self.measurement_start:
            self.unattended_receive_minutes += duration_minutes  # the source burden adds unscaled minutes
            self.unattended_receive_count += 1
        self.live_robots[task.task_id] = (task, "clean", self.env.now)
        return dwell

    def _evaluate(self, task, robot, snapshot, ignore_support=False):
        if not self.unattended:
            return super()._evaluate(task, robot, snapshot, ignore_support)
        workers, jobs, preset = snapshot
        jobs = list(jobs)
        release = self.env.now
        if robot is not None:
            pickup = self._forecast_travel(str(robot["location"]), task.origin, True)
            r = self.config["robots"]
            energy = (pickup + self._deterministic_robot_duration(task)) * r["energy_kwh_per_active_minute"]
            if energy > r["battery_capacity_kwh"]:
                return None
            charge = 0.
            if energy > robot["battery_kwh"]:
                charge = (r["battery_capacity_kwh"] - robot["battery_kwh"]) / r["charging_power_kw"] / r["charging_efficiency"] * 60
                charge *= 1 + len(self.chargers.queue) / self.chargers.capacity
            release += pickup + charge
        jobs.append(Job(task, "human" if robot is None else "load", release, self.queue_counter + 1))
        return rollout_unattended(workers, jobs, preset=preset, ignore_support=ignore_support, **self._options())

    def run(self):
        result = super().run()
        result["unattended_receiving"] = self.unattended
        if self.unattended:
            result["unattended_receive_minutes"] = self.unattended_receive_minutes
            result["unattended_receive_count"] = self.unattended_receive_count
            result["robot_human_burden_minutes"] -= self.unattended_receive_minutes
            result["net_released_minutes"] += self.unattended_receive_minutes
        return result
