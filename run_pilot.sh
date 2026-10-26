#!/usr/bin/env bash
# run_pilot.sh -- run probe.py every INTERVAL seconds for CYCLES cycles.
# This is the single-host pilot runner. Honest label via VANTAGE.
# Respects the 5-minute interval ceiling (INTERVAL default 300s). Read-only.
set -u
CYCLES="${CYCLES:-7}"
INTERVAL="${INTERVAL:-300}"
export VANTAGE="${VANTAGE:-sandbox-proof}"
echo "[pilot] start $(date -u +%FT%TZ) vantage=$VANTAGE cycles=$CYCLES interval=${INTERVAL}s"
for i in $(seq 1 "$CYCLES"); do
  echo "[pilot] cycle $i/$CYCLES $(date -u +%FT%TZ)"
  python3 probe.py >/dev/null 2>>pilot_run.log || echo "[pilot] probe.py non-zero on cycle $i"
  if [ "$i" -lt "$CYCLES" ]; then sleep "$INTERVAL"; fi
done
echo "[pilot] done $(date -u +%FT%TZ)"
