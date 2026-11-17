"""Staff availability gate for the support-aware rollout. Frozen source in ../src is imported unchanged.
Added on 17 November 2026 for the IJSR revision, after the staff-side analysis (ctl/analyze_human_side.py)
showed that the tardiness objective places robot calls mostly in periods in which no transporter is idle.

staff_gate  Same continuation and lexicographic choice as staff_rollout; the best robot is admitted only if,
            in the reported worker state at the decision, an idle eligible worker exists for loading and an idle
            eligible worker exists for receiving (the worker condition of the idle pair rule, without its
            deadline test). With the gate disabled (workflow["gate"] = False) the rule is staff_rollout, and
            GateSimulation reproduces stored staff_rollout runs bit for bit (run_gate.py --phase test).

HriSimulation adds the read-only mission log of MissionLogSimulation.
"""
from time import perf_counter

from forecast import Job
from frontvol_simulation import QuotaSimulation
from mission_simulation import MissionLogSimulation

GATE_POLICIES = {"staff_gate"}


class GateSimulation(QuotaSimulation):
    def _gate_ok(self, task, snapshot):
        now = self.env.now
        workers, _, _ = snapshot
        idle = [w for w in workers if w.available <= now and w.shift_end > now]
        load = Job(task, "load", now, 0)
        receive = Job(task, "receive", now, 0)
        return any(self._eligible(w, load) for w in idle) and any(self._eligible(w, receive) for w in idle)

    def _robot_eligible(self, task):
        policy = self.config["scenario"]["policy"]
        if policy not in GATE_POLICIES:
            return super()._robot_eligible(task)
        self.task_registry[task.task_id] = task
        if not self.robot_units.items:
            return False
        start = perf_counter()
        snapshot = self._snapshot()
        human = self._evaluate(task, None, snapshot, False)
        best_score, best_robot, best_forecast = human.score(), None, human
        for robot in sorted(self.robot_units.items, key=lambda r: r["robot_id"]):
            forecast = self._evaluate(task, robot, snapshot, False)
            if forecast is None:
                continue
            s = forecast.score()
            if s < best_score:
                best_score, best_robot, best_forecast = s, robot, forecast
        if best_robot is not None and self.workflow.get("gate", True) and not self._gate_ok(task, snapshot):
            best_robot, best_forecast = None, human
            if task.created_at >= self.measurement_start:
                self.__dict__["gate_blocked"] = self.__dict__.get("gate_blocked", 0) + 1
        if best_robot is not None:
            self.selected_robot[task.task_id] = best_robot["robot_id"]
            self.admitted += int(task.created_at >= self.measurement_start)
        self.predictions[task.task_id] = best_forecast.completions[task.task_id]
        if task.created_at >= self.measurement_start:
            self.decision_count += 1
            self.decision_times.append(perf_counter() - start)
        return best_robot is not None

    def run(self):
        result = super().run()
        result["gate_blocked"] = self.__dict__.get("gate_blocked", 0)
        return result


class HriSimulation(MissionLogSimulation, GateSimulation):
    pass
