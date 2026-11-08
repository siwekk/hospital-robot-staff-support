"""Deterministic, observable-state forecasts; no simulator RNG or future demand."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from hospital_sim.entities import DeliveryTask


@dataclass(frozen=True)
class Worker:
    identity: str
    location: str
    available: float
    shift_end: float


@dataclass(frozen=True)
class Job:
    task: DeliveryTask
    phase: str
    release: float
    order: int


@dataclass
class Forecast:
    completions: dict[int, float]
    tasks: dict[int, DeliveryTask]
    human_minutes: float

    def score(self, candidate: int | None = None) -> tuple[float, float]:
        ids = [candidate] if candidate is not None else list(self.completions)
        # Lexicographic loss: priority weighted tardiness, then total flow time.
        return (
            sum((4.0 if self.tasks[i].priority == 1 else 1.0)
                * max(0.0, self.completions[i] - self.tasks[i].due_at) for i in ids),
            sum(self.completions[i] - self.tasks[i].created_at for i in ids),
        )


def rollout(workers: list[Worker], jobs: list[Job], *,
            travel: Callable[[str, str, bool], float], coordination: float,
            cleaning: float, cleaning_types: set[str], ignore_support: bool = False,
            preset: dict[int, tuple[DeliveryTask, float]] | None = None,
            support_scale: float = 1.0, eligible=None) -> Forecast:
    """Drain known jobs with nonpreemptive priority and nearest idle worker.

    Load completion releases receiving after robot travel; receiving releases
    cleaning. Released jobs cannot reserve workers ahead of higher priority work.
    Autonomous support in the ablation keeps handling duration but removes staff
    occupation and staff travel. Execution is not changed by this ablation.
    """
    eligible = eligible or (lambda worker, job: True)
    workers = list(workers)
    pending = list(jobs)
    completed = {i: time for i, (_, time) in (preset or {}).items()}
    tasks = {i: task for i, (task, _) in (preset or {}).items()}
    human_minutes = 0.0
    plan = {}

    def finish(job: Job, when: float) -> None:
        task = job.task
        tasks[task.task_id] = task
        if job.phase == "load":
            pending.append(Job(task, "receive", when + travel(task.origin, task.destination, True), job.order))
        elif job.phase in {"human", "receive"}:
            completed[task.task_id] = when
            if job.phase == "receive" and task.task_type in cleaning_types and cleaning > 0:
                pending.append(Job(task, "clean", when, job.order))

    while pending:
        # Earliest instant at which any waiting job can acquire a worker.
        times = [max(job.release, worker.available)
                 for job in pending for worker in workers
                 if eligible(worker, job) and max(job.release, worker.available) < worker.shift_end]
        if ignore_support:
            times.extend(job.release for job in pending if job.phase != "human")
        if not times:
            for job in pending:
                if job.phase != "clean":
                    completed[job.task.task_id] = max(job.release, job.task.due_at) + 1440.0
                    tasks[job.task.task_id] = job.task
            break
        now = min(times)
        ready = [job for job in pending if job.release <= now + 1e-9
                 and (any(eligible(w, job) and w.available <= now + 1e-9 and now < w.shift_end for w in workers)
                      or (ignore_support and job.phase != "human"))]
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
        if ignore_support and job.phase != "human":
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
