# Forecasting Human Support Improves the Choice, Not Only the Number, of Hospital Robot Missions

**Krzysztof Siwek**<sup>1</sup> and **Aleksandra Hanna Świetlicka**<sup>2</sup>

<sup>1</sup> Faculty of Electrical Engineering, Warsaw University of Technology, Warsaw, Poland
<sup>2</sup> Faculty of Control, Robotics and Electrical Engineering, Poznań University of Technology, Poznań, Poland

Simulation code, experiment designs, calibration logs, and summary results for the article submitted to the *Journal of Intelligent & Robotic Systems*.

## Summary

Hospital delivery robots need staff to load, receive, and clean them, so every robot mission also consumes staff time. This study asks whether a dispatcher that forecasts this support makes better robot-versus-human decisions, and why. A discrete event simulation replays 33,079 recorded transport requests of the University Medical Center Freiburg, with robot support given by mobile transporters, stationary local workers, or both.

Compared with a rollout forecast that ignores support, a forecast that represents staff occupation lowers priority-weighted tardiness by 0.163 min per request. Random admission at matched robot coverage attributes this gain to dispatching fewer robots. When the forecast without support is restricted to the same coverage, however, it selects worse than chance and is 0.090 min per request worse than the support-aware forecast: it sends urgent requests to robots while the transporters needed to support them are busy. When robots are used more to release staff time, support-aware rules stay better at equal coverage. A CP-SAT scheduler adds no selection value beyond random admission at its coverage, and human-only transport has the lowest average tardiness. In exploratory scenarios, only unattended receiving and local support narrow or reverse the robots' disadvantage. Representing human support improves the choice of robot missions, but the staff time consumed per mission determines whether robots help.

All results are conditional on one hospital pathway network and assumed task classes, service times, and staffing. They do not estimate clinical benefit or staffing needs at Freiburg.

## Repository structure

```
.
├── src/                 Simulator (frozen during all experiments; do not edit)
│   ├── hospital_sim/    Discrete event core: demand, routing, entities, simulation
│   ├── staff_simulation.py, workflow_simulation.py   Staff, support arrangements, unavailability
│   ├── forecast.py      Deterministic rollout continuation (Algorithm 1 of the article)
│   ├── schedule_optimizer.py   CP-SAT scheduler
│   ├── run_study.py, run_workflows.py   Main experiment runner
│   └── test_*.py        Model and optimizer tests (9 of the 14 tests)
├── ctl/                 Experiment phases added after the main experiment
│   ├── control_simulation.py    Matched random, idle pair and idle surplus rules
│   ├── extra_simulation.py      Staff time allowance rules (front)
│   ├── mission_simulation.py    Read-only mission logger
│   ├── frontvol_simulation.py   Threshold rule (omitted support at matched coverage)
│   ├── run_*.py, pipeline_*.sh  Phase runners (calibrate, verify, freeze, main)
│   └── analyze_*.py             Analyses that produce the analysis_* folders
├── data_preparation/    Download and preprocessing of the public Freiburg data
├── figures/             Scripts for the figures of the article
├── validation/          Execution tests (5 of the 14 tests)
├── ref/                 Stored runs for the reproducibility check
├── analysis_*/          Summary results of each phase (CSV, JSON)
├── design_*.json        Frozen designs (seeds, conditions, probabilities, code hashes)
├── *calibration*.json, *targets*.json, *verify*.json   Calibration logs of the random arms
├── main_runs_subset.csv Per-run outcomes of the main experiment (1,800 runs)
└── parameters.json, routes.json, locations.json, base_config.json   Model inputs
```

The runners resolve all paths relative to the repository root, so the flat layout of the root directory is intentional.

## Data

The request and pathway data come from the public dataset

> Hess, A., Stampa, D.: Healthcare Logistics Dataset: GraphML Pathway Network and Transport Requests (University Medical Center Freiburg). Zenodo (2026). https://doi.org/10.5281/zenodo.19085901

`parameters.json`, `routes.json`, and `locations.json` were derived from it with `data_preparation/prepare_freiburg.py`; the raw files are not needed to rerun the experiments. To rebuild the inputs:

```bash
python data_preparation/download_demo_data.py
python data_preparation/prepare_freiburg.py
```

Task contents, deadlines, service times, and staffing are assumptions of the model, not observations.

## Requirements

Python 3.12 and the packages in `requirements.txt` (exact versions used on the server are in `requirements_server.lock`). The CP-SAT optimizer uses one search worker with wall-clock limits, so its runs are not bit-for-bit reproducible on other hardware; all other policies are deterministic given the seed.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest src validation      # 14 tests
python repro_check_server.py       # reruns stored reference runs; J must be identical
```

## Reproducing the experiments

Each phase writes one JSON file per run to `results/<phase>/`, skips runs that already exist, and refuses to mix runs if its frozen design or the simulator source changed. The last argument of a pipeline is the number of parallel processes. Raw run outputs are not included in this repository; they are archived at https://doi.org/10.5281/zenodo.24056430 (unpack the archives into the repository root).

| Phase | Article | Command |
|---|---|---|
| Main experiment (5 policies, 18 conditions, 20 seeds) | Table 4 | `python src/run_workflows.py --phase main --workers 12` |
| Controls (matched random, idle rules) | Tables 4–5 | `python ctl/run_controls.py --phase main --workers 12` |
| Staff time front, sensitivity | Fig. 6, Table A2 | `bash ctl/pipeline.sh` |
| Optimizer at matched volume | Table 6 | `python ctl/run_optvol.py --phase P --workers 12` for P = targets, calibrate, verify, freeze, main |
| Random arm at omitted-support coverage, mission logs | Table 5, Fig. 5 | `bash ctl/pipeline_omitvol.sh 12` |
| Front volume and threshold rule at equal coverage | Table 5, Figs. 3, 5, 6 | `bash ctl/pipeline_frontvol.sh 12` |
| Scarcity, unattended receiving | Fig. 8, Table A3 | `bash ctl/pipeline_scarcity.sh 12` |
| Equal budget | Fig. 8, Table A3 | `bash ctl/pipeline_budget.sh` |
| Demand, night only, tours, combined | Fig. 8, Table A3 | `bash ctl/pipeline_levers.sh 12` |
| Warm-up check | Section 3.4 | `python ctl/check_warmup.py 8` |

The main experiment was originally run from a directory layout with a separate `code/` folder; its frozen design is kept as `design_main_original.json` and its outcomes as `main_runs_subset.csv`. A new run of `src/run_workflows.py --phase main` writes a fresh `design_main.json` and reproduces the heuristic policies exactly.

Analyses read `main_runs_subset.csv` and `results/`, and write the `analysis_*` folders, for example:

```bash
python ctl/analyze_omitvol.py
python ctl/analyze_frontvol.py
python figures/make_round2_figures.py . figures/out
```

## Related work by the authors

Siwek, K., Świetlicka, A.: A State Based Dispatch Controller for Hospital Delivery Robots with Shared Human and Infrastructure Resources. arXiv:2610.05971 (2026). https://doi.org/10.48550/arXiv.2610.05971

## Citation

If you use this code, please cite the article (citation details will be added on publication) and the Freiburg dataset above. See `CITATION.cff`.

## License

Code: MIT License (see `LICENSE`). The Freiburg dataset is distributed under its own license on Zenodo.
