"""Equal staff budget variant. Local workers exist only at a chosen node set; robot admission is
considered only for requests whose required local workers exist. The frozen source is not modified."""
from extra_simulation import ExtraSimulation


class BudgetSimulation(ExtraSimulation):
    def _covered(self, task):
        nodes = {str(n) for n in self.workflow["nodes"]}
        mode = self.workflow["mode"]
        if mode == "local":
            return str(task.origin) in nodes and str(task.destination) in nodes
        if mode == "mixed":
            return str(task.destination) in nodes
        return True

    def _robot_eligible(self, task):
        if not self._covered(task):
            self.task_registry[task.task_id] = task
            return False
        return super()._robot_eligible(task)
