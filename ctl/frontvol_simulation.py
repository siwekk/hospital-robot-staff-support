"""Admission threshold rule for the forecast without support, with mission logs.
Frozen source in ../src is imported unchanged.

omitted_quota  Same continuation and choice as no_support_forecast (omitted support); the best robot must be
               lexicographically better than human delivery in (L, F) and its margin must pass a lexicographic
               threshold t. With dL = L(h) - L(r) and dF = F(h) - F(r):
                 t <  T0: admit if dL > 0, or dL = 0 and dF >= t      (trims flow-only admissions first)
                 t >= T0: admit if dL >= (t - T0) / 100                (no flow-only admissions; trims by dL)
               t = 0 reproduces no_support_forecast. Most admissions of omitted support have dL = 0, so a threshold
               on dL alone cannot reach intermediate coverage. t is calibrated per condition to the coverage of
               staff rollout; the rule keeps the lexicographic order of omitted support and only lowers its volume.

FrontSimulation adds the mission log of MissionLogSimulation to every policy (it only reads state).
"""
from time import perf_counter

from extra_simulation import ExtraSimulation
from mission_simulation import MissionLogSimulation

QUOTA_POLICIES = {"omitted_quota"}
T0 = 1000.0
EPS = 1e-9


class QuotaSimulation(ExtraSimulation):
    @property
    def quota_margins(self):
        return self.__dict__.setdefault("_quota_margins", [])

    def run(self):
        result = super().run()
        m = self.__dict__.get("_quota_margins", [])
        if m:  # margins of measured decisions in which the best robot beat human delivery in (L, F)
            result["quota_margins"] = dict(n=len(m), tardiness_tie_share=sum(1 for dl, _, _ in m if dl <= EPS) / len(m),
                                           admitted_share=sum(1 for *_, ok in m if ok) / len(m))
        return result

    def _robot_eligible(self, task):
        policy = self.config["scenario"]["policy"]
        if policy not in QUOTA_POLICIES:
            return super()._robot_eligible(task)
        self.task_registry[task.task_id] = task
        if not self.robot_units.items:
            return False
        start = perf_counter()
        theta = float(self.workflow["theta"])
        snapshot = self._snapshot()
        human = self._evaluate(task, None, snapshot, True)
        best_score, best_robot, best_forecast = human.score(), None, human
        for robot in sorted(self.robot_units.items, key=lambda r: r["robot_id"]):
            forecast = self._evaluate(task, robot, snapshot, True)
            if forecast is None:
                continue
            s = forecast.score()
            if s < best_score:
                best_score, best_robot, best_forecast = s, robot, forecast
        if best_robot is not None:
            lh, fh = human.score()
            dl, df = lh - best_score[0], fh - best_score[1]
            if theta <= 0:
                ok = True
            elif theta < T0:
                ok = dl > EPS or df >= theta
            else:
                ok = dl > EPS and dl >= (theta - T0) / 100.0
            if not ok:
                best_robot, best_forecast = None, human
            if task.created_at >= self.measurement_start:
                self.quota_margins.append((dl, df, ok))
        if best_robot is not None:
            self.selected_robot[task.task_id] = best_robot["robot_id"]
            self.admitted += int(task.created_at >= self.measurement_start)
        self.predictions[task.task_id] = best_forecast.completions[task.task_id]
        if task.created_at >= self.measurement_start:
            self.decision_count += 1
            self.decision_times.append(perf_counter() - start)
        return best_robot is not None


class FrontSimulation(MissionLogSimulation, QuotaSimulation):
    pass
