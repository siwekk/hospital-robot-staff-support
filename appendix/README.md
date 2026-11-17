# Online appendix

Online appendix to the article *When Hospital Robots Ask Staff for Help: Forecasting Human Support in Robot Dispatch* (K. Siwek, A. Świetlicka), submitted to the *International Journal of Social Robotics*. Section, table, figure, equation, and algorithm numbers without a prefix refer to the article.

- [Appendix A. Additional tables](#appendix-a-additional-tables): Tables A1–A5
- [Appendix B. STRESS-DES checklist](#appendix-b-stress-des-checklist): Table B1

## Appendix A. Additional tables

Weighted tardiness *J* in weighted minutes per request; coverage is the share of requests completed by robots; released time is net staff minutes per day.

### Table A1. Front of tardiness against released staff time

20 seeds and 18 conditions. Random arms are named by the rule whose coverage they were calibrated to; their coverage differs from the target because calibration used short pilot runs. Source: `analysis_frontvol/frontvol_policy_means.csv`.

| Policy | *J* | Coverage (%) | Released (min/day) |
|---|---:|---:|---:|
| Human transport | 0.968 | 0 | 0 |
| Optimization | 1.036 | 0.52 | 8.4 |
| Staff rollout | 1.081 | 0.74 | 11.9 |
| Support aware, φ = 3 | 1.120 | 1.47 | 21.7 |
| Support aware, φ = 10 | 1.421 | 8.69 | 133.9 |
| Threshold rule | 1.170 | 0.73 | 14.3 |
| Omitted support | 1.244 | 1.89 | 31.2 |
| Omitted support, φ = 3 | 1.323 | 3.39 | 52.6 |
| Omitted support, φ = 10 | 1.750 | 11.67 | 181.3 |
| Random, staff rollout | 1.121 | 0.77 | 14.2 |
| Random, support aware φ = 3 | 1.259 | 1.64 | 30.3 |
| Random, omitted support | 1.407 | 2.09 | 39.3 |
| Random, omitted φ = 3 | 1.691 | 3.83 | 71.5 |
| Random, support aware φ = 10 | 2.388 | 9.73 | 187.8 |
| Random, omitted φ = 10 | 2.709 | 12.12 | 235.5 |
| Idle pair rule | 1.804 | 11.85 | 204.7 |

### Table A2. Sensitivity

6 seeds, scenario conditions. Cov.: coverage of staff rollout; last column: staff rollout minus human transport with 95% interval. Seed sets differ from Table A3, so levels are not comparable across the two tables. Source: `analysis_extra/sensitivity_summary.csv`.

| Scenario | Human | Rollout | Omitted | Idle pair | Cov. (%) | Rollout − human |
|---|---:|---:|---:|---:|---:|---|
| Two robots | 1.356 | 1.559 | 1.749 | 2.473 | 1.12 | 0.203 [0.118, 0.288] |
| Four robots | 1.356 | 1.763 | 2.127 | 3.497 | 1.94 | 0.407 [0.290, 0.524] |
| Eight robots | 1.356 | 2.088 | 2.904 | 5.326 | 3.09 | 0.732 [0.604, 0.861] |
| Robot at 72 m/min | 1.356 | 1.659 | 1.896 | 2.605 | 1.61 | 0.303 [0.222, 0.384] |
| Support ×0.5 | 1.356 | 1.595 | 1.797 | 2.313 | 1.91 | 0.239 [0.147, 0.332] |
| Support ×1.5 | 1.356 | 1.484 | 1.709 | 2.700 | 0.64 | 0.129 [0.050, 0.207] |

### Table A3. Operating scenarios

12 seeds, two robots. Unless noted, mobile and local support with *b* ∈ {0.4, 0.8} and both delays; the equal budget rows use local (L) or mixed (X) support with *k* local workers and compare with human transport on the reduced roster. Coverage (Cov., %) and released time (Rel., min/day) refer to staff rollout; matched random equals rollout plus *S*. *S*<sub>adj</sub> corrects *S* for the coverage error of matched random with β = 0.215. Rollout − human with 95% intervals; all contrasts descriptive. Abbreviations: transp., transporters; recv., receiving; 4 night, four transporters on the night shift. Source: `analysis_scarcity/`, `analysis_budget/`, `analysis_levers/`.

| Scenario | Human | Roll. | Omit. | Cov. | Rel. | Rollout − human | *S* | *S*<sub>adj</sub> |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| Baseline, 62 transp. | 1.188 | 1.379 | 1.572 | 1.09 | 18.2 | 0.191 [0.151, 0.230] | 0.081 | 0.060 |
| 53 transporters | 1.340 | 1.613 | 1.869 | 1.46 | 23.9 | 0.274 [0.231, 0.316] | 0.128 | 0.098 |
| 44 transporters | 2.269 | 2.724 | 2.928 | 2.12 | 33.4 | 0.455 [0.355, 0.556] | 0.111 | 0.045 |
| Budget, L, *k* = 3 | 1.340 | 1.375 | 1.394 | 0.30 | 10.7 | 0.035 [−0.026, 0.096] | 0.025 | 0.041 |
| Budget, L, *k* = 6 | 2.269 | 2.065 | 2.160 | 1.50 | 28.4 | −0.204 [−0.470, 0.062] | 0.405 | 0.390 |
| Budget, X, *k* = 3 | 1.340 | 1.420 | 1.652 | 0.28 | 2.5 | 0.081 [0.020, 0.141] | −0.010 | 0.001 |
| Budget, X, *k* = 6 | 2.269 | 2.578 | 2.947 | 0.80 | 9.5 | 0.309 [0.177, 0.442] | −0.072 | −0.054 |
| Unattended recv. | 1.188 | 1.278 | 1.320 | 1.17 | 24.0 | 0.090 [0.053, 0.127] | 0.055 | 0.035 |
| Demand ×1.1 | 2.423 | 2.691 | 2.930 | 1.32 | 23.6 | 0.268 [0.178, 0.359] | 0.169 | 0.138 |
| Demand ×1.2 | 5.776 | 6.373 | 6.635 | 1.68 | 32.5 | 0.597 [0.366, 0.828] | 0.173 | 0.083 |
| Night only | 1.188 | 1.194 | 1.243 | 0.16 | 2.9 | 0.006 [−0.028, 0.040] | 0.018 | 0.021 |
| Night only, 4 night | 1.247 | 1.315 | 1.453 | 0.37 | 6.7 | 0.068 [0.041, 0.096] | 0.026 | 0.029 |
| All hours, 4 night | 1.247 | 1.508 | 1.776 | 1.36 | 22.8 | 0.261 [0.188, 0.335] | 0.127 | 0.097 |
| Tours of up to three | 1.188 | 1.598 | 1.838 | 1.46 | 28.1 | 0.410 [0.367, 0.452] | 0.099 | 0.042 |
| Tours, 10 min wait | 1.188 | 1.619 | 1.905 | 1.47 | 29.4 | 0.431 [0.402, 0.460] | 0.133 | 0.068 |
| Combined, ×1.2 | 5.776 | 6.135 | 6.104 | 2.63 | 76.1 | 0.359 [0.122, 0.596] | 0.315 | 0.089 |

### Table A4. Class mix

Main contrasts with 40% and 20% urgent specimens on the same seeds (103000 to 103009) and 18 conditions; weighted minutes per request, 95% intervals. Last column: 20% minus 40%, paired by seed. *S* is not coverage adjusted. SR, staff rollout; H, human transport; OS, omitted support; Thr, threshold rule. Source: `analysis_specmix/specmix_contrasts.csv`, `analysis_specmix/specmix_means.csv`.

| Quantity | 40% specimens | 20% specimens | Difference |
|---|---|---|---|
| *J*, human transport | 1.059 | 0.529 | |
| *J*, staff rollout | 1.176 | 0.604 | |
| Coverage of staff rollout (%) | 0.74 | 0.75 | |
| SR − H | 0.117 [0.088, 0.146] | 0.075 [0.050, 0.099] | −0.042 [−0.075, −0.010] |
| *B* = *J*<sub>omit</sub> − *J*<sub>staff</sub> | 0.165 [0.142, 0.187] | 0.096 [0.081, 0.112] | −0.068 [−0.091, −0.045] |
| *S* = *J*<sub>rand</sub> − *J*<sub>staff</sub> | 0.039 [0.004, 0.073] | 0.022 [−0.010, 0.054] | −0.017 [−0.041, 0.008] |
| Thr − SR | 0.089 [0.069, 0.109] | 0.099 [0.077, 0.121] | 0.010 [−0.008, 0.028] |
| OS − Thr | 0.076 [0.051, 0.100] | −0.002 [−0.023, 0.019] | |

### Table A5. Robot missions by admission rule and support arrangement

Pooled over 20 seeds and six conditions per arrangement. SR, staff rollout; OS, omitted support; Thr, threshold rule; MR, matched random; Missions, robot missions per run; Spec., specimens; Route, deterministic robot duration from origin to destination including loading and receiving, minutes; Queue and Idle mob., human queue length and idle mobile workers at the admission decision; Own WT, weighted tardiness per robot mission, weighted minutes. Source: `analysis_frontvol/quota_mission_profile.csv`.

| Support | Rule | Missions | Spec. (%) | Route | Queue | Idle mob. | Late (%) | Own WT |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Mobile | SR | 7.4 | 36.1 | 10.62 | 2.74 | 2.5 | 55.6 | 23.5 |
| | Thr | 7.5 | 94.5 | 12.98 | 2.73 | 1.9 | 96.3 | 70.2 |
| | MR (SR cov.) | 7.2 | 35.5 | 11.76 | 1.12 | 6.5 | 45.5 | 20.5 |
| | OS | 45.4 | 40.3 | 10.99 | 1.01 | 6.1 | 38.1 | 12.9 |
| | MR (OS cov.) | 50.4 | 39.0 | 11.84 | 0.60 | 7.5 | 43.4 | 17.6 |
| Mixed | SR | 8.8 | 40.1 | 10.49 | 2.63 | 2.3 | 56.7 | 26.9 |
| | Thr | 8.7 | 92.5 | 12.94 | 2.44 | 2.4 | 92.0 | 61.6 |
| | MR (SR cov.) | 8.5 | 36.3 | 11.78 | 1.08 | 6.6 | 47.0 | 20.2 |
| | OS | 46.2 | 40.4 | 10.94 | 1.01 | 6.4 | 37.7 | 14.2 |
| | MR (OS cov.) | 51.0 | 39.1 | 11.82 | 0.63 | 7.6 | 45.3 | 19.3 |
| Local | SR | 38.3 | 39.6 | 10.88 | 1.23 | 6.9 | 33.3 | 14.4 |
| | Thr | 37.9 | 42.8 | 11.09 | 1.20 | 6.8 | 36.1 | 16.6 |
| | MR (SR cov.) | 40.9 | 39.5 | 11.73 | 0.77 | 8.2 | 44.3 | 21.1 |
| | OS | 47.0 | 41.5 | 10.90 | 1.04 | 6.5 | 35.0 | 15.3 |
| | MR (OS cov.) | 51.6 | 39.1 | 11.78 | 0.66 | 7.8 | 45.7 | 21.7 |

## Appendix B. STRESS-DES checklist

### Table B1. STRESS-DES checklist

Maps the STRESS-DES reporting items (Monks et al., 2019, *Journal of Simulation* 13(1):55–67, https://doi.org/10.1080/17477778.2018.1442155) to the sections of the article.

| Item | Topic | Where and how it is reported |
|---|---|---|
| 1.1 | Purpose | Robot-versus-human dispatch when robot missions need staff support; RQ1–RQ4 (Section 1) |
| 1.2 | Outputs | *J*, late share, robot coverage, released staff time, prediction error, mission logs, staff-side measures (Section 5) |
| 1.3 | Experimentation aims | Policy comparison in 18 conditions, volume and selection decomposition, front, scenarios, class mix, availability gate (Table 3) |
| 2.1 | Overview diagram | Figs. 1 and 2 |
| 2.2 | Base model logic | Recorded arrivals; human or robot decision; human jobs served by priority, due time and arrival by the nearest eligible idle worker (Section 3) |
| 2.3 | Scenario logic | Arrangements, unavailability, reporting delay (Section 3.2); scenario phases (Table 3) |
| 2.4 | Algorithms | Algorithm 1, Eq. (1), rule variants, availability gate, random arms and their calibration, CP-SAT model (Section 4) |
| 2.5 | Components | Entities: requests with class, priority, weight, deadline (Table 1). Activities: approach, loading, carrying, coordination, driving, elevator rides, receiving, cleaning, charging. Resources: transporters, local workers, two robots, four elevator cars, two cleaning stations, two chargers. Queues: priority queue of human jobs; first come first served at elevators, stations and chargers. Entry at recorded times; exit on delivery or after receiving and cleaning |
| 3.1 | Data sources | Public Freiburg dataset (Hess and Stampa, 2026, https://doi.org/10.5281/zenodo.19085901) |
| 3.2 | Pre-processing | Observed routes or graph estimates for 95 locations; days resampled with replacement (`data_preparation/`) |
| 3.3 | Input parameters | Table 1 and Sections 3–3.2 (`parameters.json`, `base_config.json`) |
| 3.4 | Assumptions | Task classes, deadlines, service times, staffing and unavailability are assumed (Sections 3 and 7) |
| 4.1 | Initialisation | Seven warm-up days; check with fourteen days (Section 3; `warmup_check.json`) |
| 4.2 | Run length | Seven measured days and one clearance day; all measured requests completed |
| 4.3 | Estimation | 20 paired seeds (6 to 12 in exploratory phases); seed as unit of replication; Student *t* intervals; Holm adjustment (Section 5) |
| 5.1 | Software | Python 3.12, SimPy 4.1.2, OR-Tools 9.15 (`requirements_server.lock`) |
| 5.2 | Random sampling | Separate seeded streams for demand, unavailability and service variation shared across policies; forecasts draw no random numbers; random arms use a per-request hash stream |
| 5.3 | Model execution | Discrete event simulation; decisions at request arrival; CP-SAT with one search worker and a fixed seed |
| 5.4 | System | Linux server, AMD Ryzen 9 7900X, parallel single-threaded processes; class mix and availability gate phases as stated in Section 5 |
| 6.1 | Code access | Code at https://github.com/siwekk/hospital-robot-staff-support; raw outputs at https://doi.org/10.5281/zenodo.24322157 |
