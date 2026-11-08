#!/bin/bash
cd "$(dirname "$0")"
python3 run_extra.py --phase phi_main >> ../phi_main.log 2>&1 || { echo FAIL_PHI > ../pipeline.status; exit 1; }
python3 run_extra.py --phase sens > ../sens.log 2>&1 || { echo FAIL_SENS > ../pipeline.status; exit 1; }
python3 run_controls.py --phase main2 > ../main_controls2.log 2>&1 || { echo FAIL2 > ../pipeline.status; exit 1; }
echo DONE > ../pipeline.status
