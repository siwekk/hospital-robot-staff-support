#!/bin/bash
cd "$(dirname "$0")"
python3 run_extra.py --phase phi_pilot > ../phi_pilot.log 2>&1 || { echo FAIL_PILOT > ../pipeline.status; exit 1; }
python3 make_phi_grid.py > ../make_phi_grid.log 2>&1 || { echo FAIL_GRID > ../pipeline.status; exit 1; }
python3 run_extra.py --phase phi_main > ../phi_main.log 2>&1 || { echo FAIL_PHI > ../pipeline.status; exit 1; }
python3 run_extra.py --phase sens > ../sens.log 2>&1 || { echo FAIL_SENS > ../pipeline.status; exit 1; }
echo DONE > ../pipeline.status
