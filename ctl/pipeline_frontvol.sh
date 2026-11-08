#!/bin/bash
# Usage: bash ctl/pipeline_frontvol.sh WORKERS
# Volume control along the staff time front and omitted support at matched coverage (see ctl/run_frontvol.py).
WORKERS=${1:-12}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
cd "$HERE"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
LOG="$ROOT/frontvol.log"; STATUS="$ROOT/pipeline_frontvol.status"
exec 9>"$ROOT/pipeline_frontvol.lock"; flock -n 9 || { echo "another frontvol pipeline is running"; exit 1; }
rm -f "$STATUS"
step() { echo "== $1 $(date '+%F %T')" >> "$LOG"; shift; "$@" >> "$LOG" 2>&1; }
echo RUNNING > "$STATUS"
if step test      python3 run_frontvol.py --phase test --workers 2 \
&& step targets   python3 run_frontvol.py --phase targets \
&& step qpilot    python3 run_frontvol.py --phase qpilot --workers "$WORKERS" \
&& step qcalib    python3 run_frontvol.py --phase qcalib --workers "$WORKERS" \
&& step rcalib    python3 run_frontvol.py --phase rcalib --workers "$WORKERS" \
&& step verify    python3 run_frontvol.py --phase verify --workers "$WORKERS" \
&& step freeze    python3 run_frontvol.py --phase freeze \
&& step main      python3 run_frontvol.py --phase main --workers "$WORKERS"; then
  cd "$ROOT" && tar czf frontvol_results.tar.gz results/frontvol design_frontvol.json frontvol_targets.json \
     frontvol_test.json frontvol_qpilot.json frontvol_qcalibration.json frontvol_rcalibration.json frontvol_verify.json \
     frontvol.log ctl/frontvol_simulation.py ctl/run_frontvol.py ctl/pipeline_frontvol.sh \
  && echo DONE > "$STATUS" || echo FAIL > "$STATUS"
else
  echo FAIL > "$STATUS"
fi
