#!/bin/bash
# Demand, night-only and multi-load phases: main runs, calibration, matched random, analysis, archive.
# Usage: bash pipeline_levers.sh [WORKERS]
WORKERS=${1:-10}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
PY="${PY:-$ROOT/.venv/bin/python}"
# optional CPU pinning, e.g. CPUS=0-9 bash ctl/pipeline_levers.sh 10
PIN=""; [ -n "${CPUS:-}" ] && PIN="taskset -c $CPUS"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
exec 9>"$ROOT/pipeline_levers.lock"; flock -n 9 || { echo "already running"; exit 1; }
STATUS="$ROOT/pipeline_levers.status"; LOG="$ROOT/pipeline_levers.log"
step() { echo "$(date '+%F %T') $1" | tee -a "$LOG"; echo "RUNNING $1" > "$STATUS"; }
fail() { echo "$(date '+%F %T') FAIL $1" | tee -a "$LOG"; echo "FAIL $1" > "$STATUS"; exit 1; }
cd "$HERE"
step "levers main"
$PIN "$PY" run_levers.py --phase main --workers "$WORKERS" >> "$ROOT/levers_main.log" 2>&1 || fail "levers main"
step "levers calibrate"
$PIN "$PY" run_levers.py --phase calibrate --workers "$WORKERS" >> "$ROOT/levers_calibrate.log" 2>&1 || fail "levers calibrate"
step "levers random"
$PIN "$PY" run_levers.py --phase random --workers "$WORKERS" >> "$ROOT/levers_random.log" 2>&1 || fail "levers random"
step "analysis"
"$PY" analyze_levers.py > "$ROOT/analysis_levers.log" 2>&1 || fail "levers analysis"
cd "$ROOT"
tar czf levers_results.tar.gz results/levers analysis_levers design_levers.json design_levers_random.json \
  levers_calibration.json levers_main.log levers_calibrate.log levers_random.log analysis_levers.log \
  pipeline_levers.log levers_smoke.log ctl/levers_simulation.py ctl/run_levers.py ctl/analyze_levers.py \
  || fail "archive"
sha256sum levers_results.tar.gz > levers_results.sha256
echo "$(date '+%F %T') DONE" | tee -a "$LOG"; echo DONE > "$STATUS"
