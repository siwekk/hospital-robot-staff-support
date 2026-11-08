"""Mission composition log on top of the frozen simulator. Frozen source in ../src is imported unchanged.

MissionLogSimulation only reads state. At each measured admission decision it records the length of the
human queue and the numbers of idle mobile workers, idle local workers, and idle robots, then calls the
unchanged decision rule. After the run it summarises the simulator's own event log (task class, mode,
due time, completion) and adds deterministic route attributes. It draws no random numbers and changes no
state, so J and coverage must equal the stored runs bit for bit; run_omitvol.py --phase check verifies this.
"""
from extra_simulation import ExtraSimulation

SHIFTS = (("night", 22, 6), ("day", 6, 14), ("evening", 14, 22))


def shift_of(minute):
    hour = (minute % 1440) / 60.0
    for name, a, b in SHIFTS:
        if (a < b and a <= hour < b) or (a > b and (hour >= a or hour < b)):
            return name
    return "night"


class MissionLogSimulation(ExtraSimulation):
    def _robot_eligible(self, task):
        measured = task.created_at >= self.measurement_start
        if measured:
            idle = list(getattr(self, "available_humans", {}) or {})
            idle_local = sum(1 for i in idle if str(i).startswith("local:"))
            state = (len(self.human_queue.items), len(idle) - idle_local, idle_local, len(self.robot_units.items))
        admitted = super()._robot_eligible(task)
        if measured:
            log = self.__dict__.setdefault("mission_decisions", {})
            log[task.task_id] = state + (bool(admitted),)
        return admitted

    def _route(self, origin, destination):
        r = self.router.estimate(origin, destination)
        return r.distance_m, r.elevator_rides, r.elevator_floors

    def run(self):
        result = super().run()
        decisions = self.__dict__.get("mission_decisions", {})
        measured = [e for e in self.event_log if e["created_at"] >= self.measurement_start]
        by_mode = {}
        missions = []
        for e in measured:
            w = 4 if e["priority"] == 1 else 1
            tard = max(0.0, e["completed_at"] - e["due_at"])
            key = f'{e["mode"]}|{e["task_type"]}'
            agg = by_mode.setdefault(key, [0, 0.0, 0.0])
            agg[0] += 1; agg[1] += w * tard; agg[2] += e["completed_at"] - e["created_at"]
            if e["mode"] == "robot":
                dist, rides, floors = self._route(e["origin"], e["destination"])
                q, im, il, ir, _ = decisions.get(e["task_id"], (None, None, None, None, None))
                task = getattr(self, "task_registry", {}).get(e["task_id"])
                missions.append(dict(
                    task_type=e["task_type"], priority=e["priority"], shift=shift_of(e["created_at"]),
                    minute_of_day=round(e["created_at"] % 1440, 2), deadline=round(e["due_at"] - e["created_at"], 3),
                    robot_minutes=round(self._deterministic_robot_duration(task), 3) if task else None,
                    human_minutes=round(self._deterministic_human_duration(task), 3) if task else None,
                    distance_m=round(dist, 1), elevator_rides=rides, elevator_floors=floors,
                    cycle=round(e["completed_at"] - e["created_at"], 3), weighted_tardiness=round(w * tard, 4),
                    queue=q, idle_mobile=im, idle_local=il, idle_robots=ir))
        # admission propensity by class and shift among all measured decisions
        types = {e["task_id"]: (e["task_type"], shift_of(e["created_at"])) for e in measured}
        prop = {}
        queue_all, queue_adm = [], []
        for tid, (q, im, il, ir, adm) in decisions.items():
            if tid not in types:
                continue
            for key in (f"type|{types[tid][0]}", f"shift|{types[tid][1]}"):
                p = prop.setdefault(key, [0, 0]); p[0] += 1; p[1] += int(adm)
            queue_all.append(q)
            if adm:
                queue_adm.append(q)
        created = max(1, result["created"])
        own = sum(v[1] for k, v in by_mode.items() if k.startswith("robot|"))
        other = sum(v[1] for k, v in by_mode.items() if k.startswith("human|"))
        result["mission_log"] = dict(
            missions=missions,
            by_mode_type={k: dict(n=v[0], weighted_tardiness=v[1], cycle=v[2]) for k, v in sorted(by_mode.items())},
            propensity={k: dict(decisions=v[0], admitted=v[1]) for k, v in sorted(prop.items())},
            mean_queue_all=sum(queue_all) / len(queue_all) if queue_all else None,
            mean_queue_admitted=sum(queue_adm) / len(queue_adm) if queue_adm else None,
            own_tardiness_per_request=own / created, other_tardiness_per_request=other / created,
            reconstruction_error=(own + other) / created - result["weighted_tardiness_per_request"],
        )
        return result

