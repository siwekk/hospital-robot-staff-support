"""Observer and decision layer over an unchanged archived execution model."""
from __future__ import annotations

from math import exp
from time import perf_counter

from hospital_sim.simulation import HospitalSimulation
from hospital_sim.entities import SupportAssignment
from forecast import Worker, Job, rollout


NEW_POLICIES = {"staff_rollout", "no_support_forecast", "own_completion"}


class StaffSimulation(HospitalSimulation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_schedule = {}
        self.busy_forecasts = {}
        self.live_robots = {}
        self.predictions = {}
        self.decision_times = []
        self.decision_count = 0
        self.admitted = 0
        self.queue_truncations = 0
        self.selected_robot = {}
        self.prediction_errors = []

    def _expected_coordination(self):
        r = self.config["robots"]
        return (float(r["coordination_minutes_mean"]) * exp(0.5 * 0.3**2)
                + (1.0 - float(r["reliability"])) * float(r["failure_recovery_minutes_mean"]))

    def _support_expectation(self, assignment):
        scale = float(self.config["robots"].get("support_multiplier", 1.0))
        if assignment.support_kind == "loading_coordination_recovery":
            return scale * (assignment.task.loading_minutes + self._expected_coordination())
        if assignment.support_kind == "receiving":
            return scale * assignment.task.receiving_minutes
        return scale * float(self.config["robots"].get("decontamination_human_minutes", 0))

    def _forecast_travel(self, origin, destination, robot):
        duration = self._deterministic_travel_minutes(origin, destination, robot=robot)
        if self.config["hospital"].get("explicit_elevator_contention", False):
            route = self.router.estimate(origin, destination)
            if route.elevator_rides:
                duration += ((self.elevators.count + len(self.elevators.queue))
                             / self.elevators.capacity
                             * float(self.config["hospital"]["elevator_cycle_minutes"]))
        return duration

    def _location_aware_human_worker(self, start, end, worker_id):
        self.worker_schedule[worker_id] = (start, end)
        yield from super()._location_aware_human_worker(start, end, worker_id)
        self.worker_schedule.pop(worker_id, None)
        self.busy_forecasts.pop(worker_id, None)

    def _dispatch_nearest_human(self):
        # Arrivals can occur at a shift timeout before its worker resumes.
        # Exclude expired workers before removing any assignment from the queue.
        for identity in list(self.available_humans):
            if self.worker_schedule.get(identity, (0, float("inf")))[1] <= self.env.now:
                self.available_humans.pop(identity)
        for identity in self.available_humans:
            self.busy_forecasts.pop(identity, None)
        while self.available_humans and self.human_queue.items:
            _, _, order, assignment = self.human_queue.get().value
            support = isinstance(assignment, SupportAssignment)
            pickup = self._support_node(assignment) if support else assignment.task.origin
            identity = min(self.available_humans, key=lambda i: (
                self._deterministic_travel_minutes(self.available_humans[i][0], pickup, robot=False)
                if self.available_humans[i][0] is not None else 0.0, i))
            location, ready = self.available_humans.pop(identity)
            task = assignment.task
            duration = self._forecast_travel(str(location), pickup, False) if location is not None else 0
            duration += (self._support_expectation(assignment) if support
                         else self._forecast_travel(task.origin, task.destination, False)
                         + task.loading_minutes + task.receiving_minutes)
            self.busy_forecasts[identity] = (self.env.now + duration,
                                           pickup if support else task.destination,
                                           assignment, order)
            self.busy_human_workers += 1
            ready.succeed(assignment)

    def _request_human_support(self, task, duration_minutes, support_kind):
        phase = {"loading_coordination_recovery": "load", "receiving": "receive",
                 "decontamination": "clean"}[support_kind]
        self.live_robots[task.task_id] = (task, "queued_" + phase, self.env.now)
        scale = float(self.config["robots"].get("support_multiplier", 1.0))
        elapsed = yield from super()._request_human_support(task, duration_minutes * scale, support_kind)
        if phase == "load":
            self.live_robots[task.task_id] = (
                task, "receive", self.env.now + self._forecast_travel(task.origin, task.destination, True))
        elif phase == "receive":
            self.live_robots[task.task_id] = (task, "clean", self.env.now)
        else:
            self.live_robots.pop(task.task_id, None)
        return elapsed

    def _serve_robot_acquired(self, task, robot=None):
        pickup = (self._forecast_travel(str(robot["location"]), task.origin, True)
                  if robot and robot.get("location") else 0)
        charge = 0.0
        if robot:
            required = (pickup + self._deterministic_robot_duration(task)) * self.config["robots"]["energy_kwh_per_active_minute"]
            if required > robot["battery_kwh"]:
                r = self.config["robots"]
                charge = (r["battery_capacity_kwh"] - robot["battery_kwh"]) / r["charging_power_kw"] / r["charging_efficiency"] * 60
        self.live_robots[task.task_id] = (task, "load", self.env.now + charge + pickup)
        yield from super()._serve_robot_acquired(task, robot)
        self.live_robots.pop(task.task_id, None)

    def _nearest_idle_robot(self, origin):
        # Selected candidates are acquired synchronously by _serve_robot.
        if self.selected_robot:
            key = next(iter(self.selected_robot))
            selected = self.selected_robot.pop(key)
            for robot in self.robot_units.items:
                if robot["robot_id"] == selected:
                    return robot
        return super()._nearest_idle_robot(origin)

    def _serve_robot(self, task):
        try:
            yield from super()._serve_robot(task)
        finally:
            self.selected_robot.pop(task.task_id, None)

    def _snapshot(self):
        now = self.env.now
        workers, jobs, preset = [], [], {}
        queued = sorted(self.human_queue.items)
        limit = int(self.config.get("forecast", {}).get("queue_limit", 32))
        # All support jobs are retained, even beyond the ordinary delivery cap.
        deliveries = [item for item in queued if not isinstance(item[3], SupportAssignment)]
        if len(deliveries) > limit:
            self.queue_truncations += 1
        included = deliveries[:limit] + [item for item in queued if isinstance(item[3], SupportAssignment)]
        represented = set()
        for _, _, order, assignment in included:
            phase = "human"
            if isinstance(assignment, SupportAssignment):
                phase = {"loading_coordination_recovery": "load", "receiving": "receive",
                         "decontamination": "clean"}[assignment.support_kind]
                represented.add(assignment.task.task_id)
            jobs.append(Job(assignment.task, phase, now, order))
        for identity, (start, end) in self.worker_schedule.items():
            if end <= now or start > now + 120:
                continue
            if identity in self.available_humans:
                location = self.available_humans[identity][0]
                workers.append(Worker(identity, str(location), now, end))
            elif identity in self.busy_forecasts:
                predicted_end, location, assignment, order = self.busy_forecasts[identity]
                release = max(now + 1.0, predicted_end)
                workers.append(Worker(identity, str(location), release, end))
                task = assignment.task
                if isinstance(assignment, SupportAssignment):
                    represented.add(task.task_id)
                    if assignment.support_kind == "loading_coordination_recovery":
                        jobs.append(Job(task, "receive", release + self._forecast_travel(task.origin, task.destination, True), order))
                    elif assignment.support_kind == "receiving":
                        preset[task.task_id] = (task, release)
                        if task.task_type in self._cleaning_types():
                            jobs.append(Job(task, "clean", release, order))
                else:
                    preset[task.task_id] = (task, release)
            elif start > now:
                workers.append(Worker(identity, str(self.config["hospital"]["human_initial_node"]), start, end))
        for task_id, (task, phase, release) in self.live_robots.items():
            if task_id not in represented and not phase.startswith("queued_"):
                if phase != "clean" or task.task_type in self._cleaning_types():
                    jobs.append(Job(task, phase, max(now, release), task.task_id))
        return workers, jobs, preset

    def _cleaning_types(self):
        r = self.config["robots"]
        return set(r.get("decontamination_task_types", [])) if r.get("infection_control_enabled") else set()

    def _evaluate(self, task, robot, snapshot, ignore_support=False):
        workers, jobs, preset = snapshot
        jobs = list(jobs)
        if robot is None:
            jobs.append(Job(task, "human", self.env.now, self.queue_counter + 1))
        else:
            pickup = self._forecast_travel(str(robot["location"]), task.origin, True)
            r = self.config["robots"]
            energy = (pickup + self._deterministic_robot_duration(task)) * r["energy_kwh_per_active_minute"]
            if energy > r["battery_capacity_kwh"]:
                return None
            charge = 0.0
            if energy > robot["battery_kwh"]:
                charge = (r["battery_capacity_kwh"] - robot["battery_kwh"]) / r["charging_power_kw"] / r["charging_efficiency"] * 60
                charge *= 1 + len(self.chargers.queue) / self.chargers.capacity
            jobs.append(Job(task, "load", self.env.now + charge + pickup, self.queue_counter + 1))
        return rollout(workers, jobs, travel=self._forecast_travel,
                       coordination=self._expected_coordination(),
                       cleaning=float(self.config["robots"].get("decontamination_human_minutes", 0)),
                       cleaning_types=self._cleaning_types(), ignore_support=ignore_support, preset=preset,
                       support_scale=float(self.config["robots"].get("support_multiplier", 1.0)))

    def _robot_eligible(self, task):
        policy = self.config["scenario"]["policy"]
        if policy not in NEW_POLICIES:
            return super()._robot_eligible(task)
        start = perf_counter()
        if not self.robot_units.items:
            return False
        snapshot = self._snapshot()
        ignore = policy == "no_support_forecast"
        human = self._evaluate(task, None, snapshot, ignore)
        candidate = task.task_id if policy == "own_completion" else None
        best_score = human.score(candidate)
        best_robot = None
        best_forecast = human
        for robot in sorted(self.robot_units.items, key=lambda r: r["robot_id"]):
            forecast = self._evaluate(task, robot, snapshot, ignore)
            if forecast is None:
                continue
            score = forecast.score(candidate)
            if score < best_score:
                best_score, best_robot, best_forecast = score, robot, forecast
        if best_robot is not None:
            self.selected_robot[task.task_id] = best_robot["robot_id"]
            self.admitted += int(task.created_at >= self.measurement_start)
        self.predictions[task.task_id] = best_forecast.completions[task.task_id]
        if task.created_at >= self.measurement_start:
            self.decision_count += 1
            self.decision_times.append(perf_counter() - start)
        return best_robot is not None

    def _complete(self, task, mode, started, duration, worker_id=None):
        super()._complete(task, mode, started, duration, worker_id)
        if task.task_id in self.predictions and task.created_at >= self.measurement_start:
            self.prediction_errors.append(self.env.now - self.predictions[task.task_id])

    def run(self):
        import numpy as np
        result = super().run()
        measured = [e for e in self.event_log if e["created_at"] >= self.measurement_start]
        result.update(
            weighted_tardiness_per_request=sum((4 if e["priority"] == 1 else 1) * max(0, e["completed_at"] - e["due_at"]) for e in measured) / max(1, result["created"]),
            robot_coverage=result["robot_completed"] / max(1, result["created"]),
            decision_count=self.decision_count, queue_truncations=self.queue_truncations,
            decision_mean_ms=float(np.mean(self.decision_times) * 1000) if self.decision_times else 0,
            decision_p95_ms=float(np.quantile(self.decision_times, .95) * 1000) if self.decision_times else 0,
            prediction_mae=float(np.mean(np.abs(self.prediction_errors))) if self.prediction_errors else 0,
        )
        return result
