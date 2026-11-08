#!/bin/bash
# Scarcity and unattended receiving phases (run ctl/run_optvol.py first for the optimizer volume control),
# the analyses, and packs the results. Usage: bash pipeline_scarcity.sh [WORKERS]
WORKERS=${1:-10}
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
PY="${PY:-$ROOT/.venv/bin/python}"
# optional CPU pinning, e.g. CPUS=0-9 bash ctl/pipeline_scarcity.sh 10
PIN=""; [ -n "${CPUS:-}" ] && PIN="taskset -c $CPUS"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
exec 9>"$ROOT/pipeline_scarcity.lock"; flock -n 9 || { echo "already running"; exit 1; }
STATUS="$ROOT/pipeline_scarcity.status"; LOG="$ROOT/pipeline_scarcity.log"
step() { echo "$(date '+%F %T') $1" | tee -a "$LOG"; echo "RUNNING $1" > "$STATUS"; }
fail() { echo "$(date '+%F %T') FAIL $1" | tee -a "$LOG"; echo "FAIL $1" > "$STATUS"; exit 1; }
cd "$HERE"
step "scarcity main"
$PIN "$PY" run_scarcity.py --phase main --workers "$WORKERS" >> "$ROOT/scarcity_main.log" 2>&1 || fail "scarcity main"
step "scarcity calibrate"
$PIN "$PY" run_scarcity.py --phase calibrate --workers "$WORKERS" >> "$ROOT/scarcity_calibrate.log" 2>&1 || fail "scarcity calibrate"
step "scarcity random"
$PIN "$PY" run_scarcity.py --phase random --workers "$WORKERS" >> "$ROOT/scarcity_random.log" 2>&1 || fail "scarcity random"
step "analysis"
"$PY" analyze_scarcity.py > "$ROOT/analysis_scarcity.log" 2>&1 || fail "scarcity analysis"
"$PY" analyze_optvol.py > "$ROOT/analysis_optvol.log" 2>&1; echo "EXIT $?" >> "$ROOT/analysis_optvol.log"
cd "$ROOT"
tar czf scarcity_optvol_results.tar.gz results/optvol results/scarcity analysis_optvol analysis_scarcity \
  design_optvol.json design_scarcity.json design_scarcity_random.json optvol_targets.json optvol_calibration.json \
  optvol_verify.json scarcity_calibration.json optvol_main.log scarcity_main.log scarcity_calibrate.log \
  scarcity_random.log analysis_optvol.log analysis_scarcity.log pipeline_scarcity.log \
  ctl/run_optvol.py ctl/analyze_optvol.py ctl/run_scarcity.py ctl/scarcity_simulation.py ctl/analyze_scarcity.py \
  || fail "archive"
sha256sum scarcity_optvol_results.tar.gz > scarcity_optvol_results.sha256
echo "$(date '+%F %T') DONE" | tee -a "$LOG"; echo DONE > "$STATUS"
