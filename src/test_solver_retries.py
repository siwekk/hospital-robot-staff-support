from types import SimpleNamespace
import pytest
import schedule_optimizer as scheduling
from ortools.sat.python import cp_model

def fake_solver_factory(statuses,limits):
    class Solver:
        def __init__(self): self.parameters=SimpleNamespace()
        def solve(self,model):
            limits.append(self.parameters.max_time_in_seconds)
            return statuses.pop(0)
        def status_name(self,status): return {cp_model.UNKNOWN:'UNKNOWN',cp_model.FEASIBLE:'FEASIBLE',cp_model.INFEASIBLE:'INFEASIBLE',cp_model.MODEL_INVALID:'MODEL_INVALID'}[status]
    return Solver

def test_unknown_retries_until_a_feasible_schedule_is_found(monkeypatch):
    limits=[]
    monkeypatch.setattr(scheduling.cp_model,'CpSolver',fake_solver_factory([cp_model.UNKNOWN,cp_model.UNKNOWN,cp_model.FEASIBLE],limits))
    solver,status,attempts=scheduling.solve_with_retries(object(),[1.,5.,20.],'primary')
    assert status==cp_model.FEASIBLE
    assert limits==[1.,5.,20.]
    assert len(attempts)==3

def test_infeasibility_does_not_waste_time_on_longer_retries(monkeypatch):
    limits=[]
    monkeypatch.setattr(scheduling.cp_model,'CpSolver',fake_solver_factory([cp_model.INFEASIBLE],limits))
    _,status,attempts=scheduling.solve_with_retries(object(),[1.,5.,20.],'primary')
    assert status==cp_model.INFEASIBLE
    assert limits==[1.]

def test_model_errors_are_reported_instead_of_becoming_heuristic_fallbacks(monkeypatch):
    limits=[]
    monkeypatch.setattr(scheduling.cp_model,'CpSolver',fake_solver_factory([cp_model.MODEL_INVALID],limits))
    with pytest.raises(RuntimeError,match='bad model'):
        scheduling.solve_with_retries(SimpleNamespace(validate=lambda:'bad model'),[1.,5.,20.],'primary')
