#!/bin/bash
cd "$(dirname "$0")"
rm -f ../pipeline_budget.status
python3 run_budget.py --phase main >> ../budget_main.log 2>&1 || { echo FAIL_MAIN > ../pipeline_budget.status; exit 1; }
python3 run_budget.py --phase calibrate >> ../budget_calibrate.log 2>&1 || { echo FAIL_CAL > ../pipeline_budget.status; exit 1; }
python3 run_budget.py --phase random >> ../budget_random.log 2>&1 || { echo FAIL_RANDOM > ../pipeline_budget.status; exit 1; }
echo DONE > ../pipeline_budget.status
