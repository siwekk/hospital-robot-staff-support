#!/bin/bash
# Usage: bash ctl/pipeline_omitvol.sh WORKERS
# Volume control at omitted-support coverage and mission composition logs (see ctl/run_omitvol.py).
WORKERS=${1:-10}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
cd "$HERE"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
LOG="$ROOT/omitvol.log"; STATUS="$ROOT/pipeline_omitvol.status"
exec 9>"$ROOT/pipeline_omitvol.lock"; flock -n 9 || { echo "another omitvol pipeline is running"; exit 1; }
rm -f "$STATUS"
step() { echo "== $1 $(date '+%F %T')" >> "$LOG"; shift; "$@" >> "$LOG" 2>&1; }
echo RUNNING > "$STATUS"
if step targets   python3 run_omitvol.py --phase targets \
&& step calibrate python3 run_omitvol.py --phase calibrate --workers "$WORKERS" \
&& step verify    python3 run_omitvol.py --phase verify --workers "$WORKERS" \
&& step freeze    python3 run_omitvol.py --phase freeze \
&& step main      python3 run_omitvol.py --phase main --workers "$WORKERS" \
&& step check     python3 run_omitvol.py --phase check \
&& step analyze   python3 analyze_omitvol.py; then
  cd "$ROOT" && tar czf omitvol_results.tar.gz results/omitvol results/missions analysis_omitvol \
     design_omitvol.json omitvol_targets.json omitvol_calibration.json omitvol_verify.json omitvol_identity.json \
     omitvol.log ctl/mission_simulation.py ctl/run_omitvol.py ctl/analyze_omitvol.py ctl/pipeline_omitvol.sh \
  && echo DONE > "$STATUS" || echo FAIL > "$STATUS"
else
  echo FAIL > "$STATUS"
fi
