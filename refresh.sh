#!/usr/bin/env bash
# Re-pull all live dashboard data from FRED and rebuild the single-file export.
# Safe for cron / scheduled routines. Log: logs/refresh.log
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p logs
{
  echo "=== refresh $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  python3 fetch_data.py "$@"; rc=$?
  python3 build_export.py
  echo "fetch exit=$rc (0 = all series ok, 1 = some stale/failed)"
} 2>&1 | tee -a logs/refresh.log
exit "${PIPESTATUS[0]}"
