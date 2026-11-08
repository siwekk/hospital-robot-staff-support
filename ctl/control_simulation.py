"""Control arms for the frozen workflow experiment.

The frozen source in ../src is not modified. This module only adds admission
rules that never consult a completion forecast:

matched_random  Admits a robot with a fixed probability whenever a feasible robot is idle.
                The draw comes from a hash seeded stream per task, so it neither consumes
                nor depends on the simulator random streams.
idle_pair_rule  Admits a robot only if the nearest feasible robot meets the deadline and, in the
                reported worker state, an eligible idle worker exists for loading and for
                receiving. No queue or completion forecast is used.
greedy_robot    Admits a robot whenever a feasible one is idle (calibration only).
"""
from random import Random
from time import perf_counter

from forecast import Job
from workflow_simulation import WorkflowSimulation

CONTROL_POLICIES = {"matched_random", "idle_pair_rule", "greedy_robot", "idle_surplus_rule"}


class ControlSimulation(WorkflowSimulation):
    def _feasible_robots(self, task):
        r = self.config["robots"]
        options = []
        for robot in self.robot_units.items:
            pickup = self._forecast_travel(str(robot["location"]), task.origin, True)
            energy = (pickup + self._deterministic_robot_duration(task)) * r["energy_kwh_per_active_minute"]
            if energy <= r["battery_capacity_kwh"]:
                options.append((pickup, robot["robot_id"], robot))
        options.sort(key=lambda item: (item[0], item[1]))
        return options

    def _idle_pair_ok(self, task, pickup):
        now = self.env.now
        if pickup + self._deterministic_robot_duration(task) > task.due_at - now:
            return False
        workers, _, _ = self._snapshot()
        idle = [w for w in workers if w.available <= now and w.shift_end > now]
        load = Job(task, "load", now, 0)
        receive = Job(task, "receive", now, 0)
        return any(self._eligible(w, load) for w in idle) and any(self._eligible(w, receive) for w in idle)

    def _idle_surplus_ok(self, task, pickup):
        """Conservative rule: deadline fits, human queue empty, surplus idle capacity for both phases.

        Surplus means at least two idle eligible mobile workers, or the one idle local worker."""
        now = self.env.now
        if pickup + self._deterministic_robot_duration(task) > task.due_at - now:
            return False
        if len(self.human_queue.items) > 0:
            return False
        workers, _, _ = self._snapshot()
        idle = [w for w in workers if w.available <= now and w.shift_end > now]
        for phase in ("load", "receive"):
            job = Job(task, phase, now, 0)
            eligible = [w for w in idle if self._eligible(w, job)]
            if not eligible:
                return False
            need = 1 if eligible[0].identity.startswith("local:") else 2
            if len(eligible) < need:
                return False
        return True

    def _robot_eligible(self, task):
        policy = self.config["scenario"]["policy"]
        if policy not in CONTROL_POLICIES:
            return super()._robot_eligible(task)
        self.task_registry[task.task_id] = task
        if not self.robot_units.items:
            return False
        start = perf_counter()
        options = self._feasible_robots(task)
        admit = bool(options)
        if admit and policy == "matched_random":
            draw = Random(f"{self.seed}:{task.task_id}:admit").random()
            admit = draw < float(self.workflow["admit_probability"])
        elif admit and policy == "idle_pair_rule":
            admit = self._idle_pair_ok(task, options[0][0])
        elif admit and policy == "idle_surplus_rule":
            admit = self._idle_surplus_ok(task, options[0][0])
        if admit:
            self.selected_robot[task.task_id] = options[0][1]
            self.admitted += int(task.created_at >= self.measurement_start)
        if task.created_at >= self.measurement_start:
            self.decision_count += 1
            self.decision_times.append(perf_counter() - start)
        return admit
