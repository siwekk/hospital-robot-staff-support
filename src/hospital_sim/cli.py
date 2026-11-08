from __future__ import annotations

import argparse
import json

from .config import load_config, scenario_config
from .experiment import load_parameters
from .simulation import run_simulation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/hospital_reference.yaml")
    parser.add_argument("--parameters", default="data/processed/mimic_parameters.json")
    parser.add_argument("--policy", default="robot_first")
    parser.add_argument("--fleet-size", type=int, default=2)
    parser.add_argument("--demand-multiplier", type=float, default=1.0)
    parser.add_argument("--reliability", type=float, default=0.98)
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()

    base = load_config(args.config)
    config = scenario_config(
        base,
        policy=args.policy,
        fleet_size=args.fleet_size,
        demand_multiplier=args.demand_multiplier,
        reliability=args.reliability,
    )
    parameters = load_parameters(args.parameters)
    print(json.dumps(run_simulation(config, parameters, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()

