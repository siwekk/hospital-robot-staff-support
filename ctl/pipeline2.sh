#!/bin/bash
cd "$(dirname "$0")"
until [ -f ../pipeline.status ]; do sleep 60; done
python3 run_controls.py --phase main2 > ../main_controls2.log 2>&1 && echo DONE2 > ../pipeline2.status || echo FAIL2 > ../pipeline2.status
