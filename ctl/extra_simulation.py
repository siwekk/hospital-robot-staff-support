"""Staff time cost family on top of the frozen forecast.

Policies staff_cost (support aware) and omitted_cost (support omitted from the forecast) choose by
(L(a) + lambda * H(a), F(a)), where H is the predicted staff minutes of all represented jobs.
With lambda = 0 they reproduce staff_rollout and no_support_forecast exactly.
"""
from time import perf_counter

from control_simulation import ControlSimulation

COST_POLICIES = {"staff_cost", "omitted_cost"}
PHI_POLICIES = {"staff_phi", "omitted_phi"}


class ExtraSimulation(ControlSimulation):
    def _robot_eligible(self, task):
        policy = self.config["scenario"]["policy"]
        if policy in PHI_POLICIES:
            return self._phi_admit(task, policy)
        if policy not in COST_POLICIES:
            return super()._robot_eligible(task)
        self.task_registry[task.task_id] = task
        if not self.robot_units.items:
            return False
        start = perf_counter()
        lam = float(self.workflow["staff_cost"])
        ignore = policy == "omitted_cost"
        snapshot = self._snapshot()

        def score(forecast):
            loss, flow = forecast.score(None)
            return (loss + lam * forecast.human_minutes, flow)

        human = self._evaluate(task, None, snapshot, ignore)
        best_score, best_robot, best_forecast = score(human), None, human
        for robot in sorted(self.robot_units.items, key=lambda r: r["robot_id"]):
            forecast = self._evaluate(task, robot, snapshot, ignore)
            if forecast is None:
                continue
            s = score(forecast)
            if s < best_score:
                best_score, best_robot, best_forecast = s, robot, forecast
        if best_robot is not None:
            self.selected_robot[task.task_id] = best_robot["robot_id"]
            self.admitted += int(task.created_at >= self.measurement_start)
        self.predictions[task.task_id] = best_forecast.completions[task.task_id]
        if task.created_at >= self.measurement_start:
            self.decision_count += 1
            self.decision_times.append(perf_counter() - start)
        return best_robot is not None

    def _phi_admit(self, task, policy):
        """Admit a robot if it strictly lowers predicted weighted tardiness, or leaves it unchanged,
        saves predicted staff minutes and raises predicted total flow time by at most phi minutes."""
        self.task_registry[task.task_id] = task
        if not self.robot_units.items:
            return False
        start = perf_counter()
        phi = float(self.workflow["phi"])
        ignore = policy == "omitted_phi"
        snapshot = self._snapshot()
        human = self._evaluate(task, None, snapshot, ignore)
        lh, fh = human.score(None)
        best, best_robot, best_forecast = None, None, human
        for robot in sorted(self.robot_units.items, key=lambda r: r["robot_id"]):
            forecast = self._evaluate(task, robot, snapshot, ignore)
            if forecast is None:
                continue
            lr, fr = forecast.score(None)
            ok = lr < lh - 1e-9 or (lr <= lh + 1e-9 and fr - fh <= phi and forecast.human_minutes < human.human_minutes)
            if ok and (best is None or (lr, fr) < best):
                best, best_robot, best_forecast = (lr, fr), robot, forecast
        if best_robot is not None:
            self.selected_robot[task.task_id] = best_robot["robot_id"]
            self.admitted += int(task.created_at >= self.measurement_start)
        self.predictions[task.task_id] = best_forecast.completions[task.task_id]
        if task.created_at >= self.measurement_start:
            self.decision_count += 1
            self.decision_times.append(perf_counter() - start)
        return best_robot is not None
