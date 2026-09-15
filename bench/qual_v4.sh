#!/bin/bash
# RC.14 V4 - isolated qualification: run the V4 test suite INSIDE the built image.
set -uo pipefail

ROOT=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v4
IMG=ghcr.io/onestao/wechat-hub-agent:0.1.0-rc.14-agent-catchup-v4
LOG=$ROOT/qual.log
mkdir -p "$ROOT/qual"
: > "$LOG"

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

say "QUAL_START image=$IMG"
docker inspect "$IMG" --format 'IMAGE_ID={{.Id}}' | tee -a "$LOG"

docker run --rm --entrypoint python "$IMG" -c 'import sys,sqlite3; print("PY",sys.version); print("SQLITE",sqlite3.sqlite_version)' | tee -a "$LOG"

say "UNITTEST_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest discover -s agent_service/tests -t . -v > "$ROOT/qual/unittest.log" 2>&1
say "UNITTEST_RC=$?"
tail -25 "$ROOT/qual/unittest.log" | tee -a "$LOG"
grep -E '^(OK|FAILED|Ran )' "$ROOT/qual/unittest.log" | tail -5 | tee -a "$LOG"

say "CRASH_MATRIX_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest -v agent_service.tests.test_crash_matrix > "$ROOT/qual/crash_matrix.log" 2>&1
say "CRASH_MATRIX_RC=$?"
grep -E '^(test_|OK|FAILED|Ran |skipped)' "$ROOT/qual/crash_matrix.log" | tail -40 | tee -a "$LOG"

say "REGRESSION_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest -v agent_service.tests.test_v4_regression > "$ROOT/qual/regression.log" 2>&1
say "REGRESSION_RC=$?"
grep -E '^(test_|OK|FAILED|Ran )' "$ROOT/qual/regression.log" | tail -40 | tee -a "$LOG"

say "QUAL_DONE"
