"""Night-only robot operation and multi-load robot tours on top of the frozen model. ../src is not modified.

config["robots"]["active_hours"] = [a, b]
    Robots are offered only to requests created between hour a and hour b (wrapping midnight).
    Outside the window every request goes to human transport; inside it the policy decides as before.

config["robots"]["tour_capacity"] = c > 1, config["robots"]["tour_hold_minutes"] = w
    A robot admitted by the policy for a lead request opens a tour at the lead origin. Until it departs,
    a new request created at the same origin joins the tour without a policy decision when the robot
    has room, the forecast arrival of the new request meets its deadline, no request already aboard that
    was forecast on time becomes late, and the battery covers the longer route. Each joined request needs
    its own loading support at the origin (loading minutes, no extra coordination) and its own receiving
    support at its destination. Stops are visited in nearest neighbour order. After the lead is loaded the
    robot waits up to w minutes for further requests while every request aboard stays forecast on time.
    One decontamination follows the tour if any request aboard requires it.

With both keys absent the class behaves exactly as ScarcitySimulation.
"""
from scarcity_simulation import ScarcitySimulation


class LeversSimulation(ScarcitySimulation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        r = self.config["robots"]
        self.active_hours = r.get("active_hours")
        self.capacity = int(r.get("tour_capacity", 1))
        self.hold = float(r.get("tour_hold_minutes", 0.0))
        self.open_tours = {}
        self.gated = 0
        self.tours = 0
        self.tour_items = 0
        self.joined = 0
        self.hold_minutes = 0.0
        if (self.capacity > 1 or self.active_hours) and self.config["scenario"]["policy"] == "optimizer":
            raise ValueError("Levers are not implemented for the optimizer")

    # night window -----------------------------------------------------------------------------
    def _in_window(self):
        a, b = self.active_hours
        h = (self.env.now % 1440.0) / 60.0
        return a <= h < b if a < b else (h >= a or h < b)

    def _robot_eligible(self, task):
        if self.active_hours and not self._in_window():
            self.task_registry[task.task_id] = task
            if task.created_at >= self.measurement_start:
                self.gated += 1
            return False
        return super()._robot_eligible(task)

    # tours --------------------------------------------------------------------------------------
    def _scale(self):
        return float(self.config["robots"].get("support_multiplier", 1.0))

    def _plan(self, origin, items):
        """Nearest neighbour stops: list of (node, [items])."""
        left = {}
        for t in items:
            left.setdefault(t.destination, []).append(t)
        stops, here = [], origin
        while left:
            node = min(left, key=lambda n: (self._deterministic_travel_minutes(here, n, robot=True), n))
            stops.append((node, left.pop(node)))
            here = node
        return stops

    def _etas(self, origin, items, depart):
        etas, here, now, travel = {}, origin, depart, 0.0
        for node, group in self._plan(origin, items):
            leg = self._deterministic_travel_minutes(here, node, robot=True)
            now += leg
            travel += leg
            for t in group:
                now += t.receiving_minutes * self._scale()
                etas[t.task_id] = now
            here = node
        return etas, travel

    def _tour_energy(self, tour, items):
        _, travel = self._etas(tour["origin"], items, 0.0)
        r = self.config["robots"]
        active = tour["reposition"] + travel + sum(t.loading_minutes + t.receiving_minutes for t in items)
        return active * float(r["energy_kwh_per_active_minute"])

    def _joinable(self, task):
        tour = self.open_tours.get(task.origin)
        if tour is None or not tour["accepting"] or len(tour["items"]) >= self.capacity:
            return None
        depart = max(self.env.now, tour["ready"]) + task.loading_minutes * self._scale()
        old, _ = self._etas(tour["origin"], tour["items"], depart)
        new, _ = self._etas(tour["origin"], tour["items"] + [task], depart)
        if new[task.task_id] > task.due_at:
            return None
        if any(old[t.task_id] <= t.due_at < new[t.task_id] for t in tour["items"]):
            return None
        extra = self._tour_energy(tour, tour["items"] + [task]) - self._tour_energy(tour, tour["items"][:1])
        if tour["lead_energy"] + max(0.0, extra) > tour["robot"]["battery_kwh"]:
            return None
        return tour

    def _task_process(self, task):
        if self.capacity > 1:
            tour = self._joinable(task)
            if tour is not None:
                yield from self._join(task, tour)
                return
        yield from super()._task_process(task)

    def _join(self, task, tour):
        self.task_registry[task.task_id] = task
        tour["items"].append(task)
        done = self.env.event()
        tour["done"][task.task_id] = done
        tour["started"][task.task_id] = self.env.now
        if task.created_at >= self.measurement_start:
            self.joined += 1
        self.live_robots[task.task_id] = (task, "load", max(self.env.now, tour["ready"]))
        loaded = self.env.event()
        tour["loaded"].append(loaded)
        if len(tour["items"]) >= self.capacity and not tour["full"].triggered:
            tour["full"].succeed()
        self.env.process(self._load_joined(task, tour, loaded))
        yield done

    def _load_joined(self, task, tour, loaded):
        if not tour["at_origin"].triggered:
            yield tour["at_origin"]
        yield from self._request_human_support(task, task.loading_minutes, "loading_coordination_recovery")
        loaded.succeed()

    def _serve_robot_acquired(self, task, robot=None):
        if self.capacity <= 1 or robot is None:
            return (yield from super()._serve_robot_acquired(task, robot))
        r = self.config["robots"]
        rate = float(r["energy_kwh_per_active_minute"])
        # live state as in StaffSimulation._serve_robot_acquired
        pickup = self._forecast_travel(str(robot["location"]), task.origin, True) if robot.get("location") else 0
        charge = 0.0
        if (pickup + self._deterministic_robot_duration(task)) * rate > robot["battery_kwh"]:
            charge = (r["battery_capacity_kwh"] - robot["battery_kwh"]) / r["charging_power_kw"] / r["charging_efficiency"] * 60
        self.live_robots[task.task_id] = (task, "load", self.env.now + charge + pickup)
        # mission start as in HospitalSimulation._serve_robot_acquired (same random draws for the lead)
        manual = {task.task_id: self._manual_duration(task)}
        planned_duration = self._robot_duration(task)
        location = robot.get("location")
        reposition = 0.0
        if r.get("repositioning_enabled", False) and location and location != task.origin:
            reposition = self._travel_minutes(str(location), task.origin, robot=True)
        lead_energy = (planned_duration + reposition) * rate
        if r.get("enforce_battery_feasibility", False) and robot["battery_kwh"] + 1e-12 < lead_energy:
            if task.created_at >= self.measurement_start:
                self.metrics.battery_forced_charges += 1
            yield from self._charge_robot(robot)
        if robot["battery_kwh"] + 1e-12 < lead_energy:
            raise RuntimeError("Mission energy exceeds full battery capacity under enforced feasibility")
        started = self.env.now
        coordination = max(0.0, self.rng.lognormvariate(0.0, 0.30) * float(r["coordination_minutes_mean"]))
        if self.rng.random() > float(r["reliability"]):
            if task.created_at >= self.measurement_start:
                self.metrics.failures += 1
                self.metrics.human_interventions += 1
            coordination += self.rng.expovariate(1.0 / float(r["failure_recovery_minutes_mean"]))
        tour = dict(origin=task.origin, robot=robot, items=[task], accepting=True, reposition=reposition, lead_energy=lead_energy,
                    ready=self.env.now + reposition + (task.loading_minutes + self._expected_coordination()) * self._scale(),
                    done={}, started={task.task_id: started}, loaded=[], at_origin=self.env.event(), full=self.env.event())
        previous = self.open_tours.get(task.origin)
        self.open_tours[task.origin] = tour
        try:
            if reposition > 0:
                yield from self._execute_route(str(location), task.origin, reposition,
                                               measured=task.created_at >= self.measurement_start)
            tour["at_origin"].succeed()
            yield from self._request_human_support(task, task.loading_minutes + coordination,
                                                   "loading_coordination_recovery")
            tour["ready"] = self.env.now
            for loaded in list(tour["loaded"]):
                yield loaded
            # hold for further requests while everything aboard stays forecast on time
            limit = self.env.now + self.hold
            while self.hold > 0 and len(tour["items"]) < self.capacity:
                etas, _ = self._etas(task.origin, tour["items"], self.env.now)
                slack = min(t.due_at - etas[t.task_id] for t in tour["items"])
                until = min(limit, self.env.now + slack)
                if until <= self.env.now + 1e-9:
                    break
                t0 = self.env.now
                yield self.env.any_of([self.env.timeout(until - self.env.now), tour["full"]])
                self.hold_minutes += (self.env.now - t0) * (task.created_at >= self.measurement_start)
                tour["ready"] = self.env.now
                if tour["full"].triggered or self.env.now >= limit - 1e-9:
                    break
            tour["accepting"] = False
            for loaded in list(tour["loaded"]):
                yield loaded
        finally:
            if self.open_tours.get(task.origin) is tour:
                if previous is not None and previous["accepting"]:
                    self.open_tours[task.origin] = previous
                else:
                    self.open_tours.pop(task.origin, None)
        items = list(tour["items"])
        for t in items[1:]:
            manual[t.task_id] = self._deterministic_human_duration(t)
        here = task.origin
        travel_total = 0.0
        for node, group in self._plan(task.origin, items):
            leg = self._travel_minutes(here, node, robot=True)
            if leg > 0:
                yield from self._execute_route(here, node, leg, measured=any(t.created_at >= self.measurement_start for t in group))
            travel_total += leg
            for t in group:
                yield from self._request_human_support(t, t.receiving_minutes, "receiving")
                measured = t.created_at >= self.measurement_start
                if measured:
                    self.metrics.robot_completed += 1
                    self.metrics.gross_manual_minutes_avoided += manual[t.task_id]
                    burden = t.loading_minutes + t.receiving_minutes + (coordination if t is task else 0.0)
                    self.metrics.robot_human_burden_minutes += burden
                self._complete(t, "robot", tour["started"][t.task_id], self.env.now - tour["started"][t.task_id])
                if t.task_id in tour["done"]:
                    tour["done"][t.task_id].succeed()
            here = node
        # Planned energy, as in the source model: the lead's planned mission plus the forecast extra route
        # of the joined requests (checked against the battery when each joined).
        energy = lead_energy + max(0.0, self._tour_energy(tour, items) - self._tour_energy(tour, [task]))
        robot["battery_kwh"] = max(0.0, robot["battery_kwh"] - energy)
        robot["location"] = here
        if task.created_at >= self.measurement_start:
            self.metrics.robot_busy_minutes += self.env.now - started
            self.metrics.robot_energy_kwh += energy
            self.metrics.robot_empty_travel_minutes += reposition
            self.tours += 1
            self.tour_items += len(items)
            if len(items) > 1:
                self.metrics.robot_batches += 1
                self.metrics.batched_requests += len(items)
        yield from self._decontaminate_if_needed(items)
        for t in items:
            self.live_robots.pop(t.task_id, None)

    def run(self):
        result = super().run()
        result.update(active_hours=self.active_hours, tour_capacity=self.capacity, tour_hold_minutes=self.hold,
                      gated_requests=self.gated, tours=self.tours, tour_items=self.tour_items,
                      joined_requests=self.joined, tour_hold_total_minutes=self.hold_minutes,
                      mean_tour_size=self.tour_items / max(1, self.tours))
        return result
