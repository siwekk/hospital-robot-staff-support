#!/bin/bash
# Usage: bash pipeline_opt_server.sh PHASE WORKERS     (PHASE = sens_opt for four robots, sens_opt8 for eight robots)
# Run from any directory. The study root is the parent of the folder containing this script.
PHASE=${1:-sens_opt}; WORKERS=${2:-10}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
cd "$HERE"
rm -f "$ROOT/pipeline_${PHASE}.status"
python3 run_extra.py --phase "$PHASE" --workers "$WORKERS" >> "$ROOT/${PHASE}.log" 2>&1 \
  && echo DONE > "$ROOT/pipeline_${PHASE}.status" || echo FAIL > "$ROOT/pipeline_${PHASE}.status"
