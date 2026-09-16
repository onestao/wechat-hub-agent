#!/bin/bash
# RC.14 Agent V5 - isolated qualification: run the V5 test suite INSIDE the image.
#
# The crash / durability matrix required by the work package (§8) is
# agent_service.tests.test_crash_matrix (C1 crash before commit, C2 crash after
# commit, C3 crash after local commit before the Core checkpoint, C4 SIGTERM
# during batch, C5 connection failure) plus test_failure_injection. Both run
# here against the frozen image, not against a working tree.
set -uo pipefail

ROOT=${ROOT:-/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-qual}
IMG=${IMG:-ghcr.io/onestao/wechat-hub-agent@sha256:0eff09ff197b5a27d2687cb5f4a11f23f55ea5c6e0a37cff00bb065beec35492}
LOG=$ROOT/qual.log
mkdir -p "$ROOT/qual"
: > "$LOG"

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

say "QUAL_START image=$IMG"
docker inspect "$IMG" --format 'IMAGE_ID={{.Id}} REV={{index .Config.Labels "org.opencontainers.image.revision"}}' | tee -a "$LOG"
docker run --rm --entrypoint python "$IMG" -c 'import sys,sqlite3; print("PY",sys.version); print("SQLITE",sqlite3.sqlite_version)' | tee -a "$LOG"

say "UNITTEST_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest discover -s agent_service/tests -t . -v > "$ROOT/qual/unittest.log" 2>&1
say "UNITTEST_RC=$?"
grep -E '^(OK|FAILED|Ran )' "$ROOT/qual/unittest.log" | tail -5 | tee -a "$LOG"

say "CRASH_MATRIX_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest -v agent_service.tests.test_crash_matrix > "$ROOT/qual/crash_matrix.log" 2>&1
say "CRASH_MATRIX_RC=$?"
grep -E '^(test_|OK|FAILED|Ran |skipped)' "$ROOT/qual/crash_matrix.log" | tail -40 | tee -a "$LOG"

say "FAILURE_INJECTION_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest -v agent_service.tests.test_failure_injection > "$ROOT/qual/failure_injection.log" 2>&1
say "FAILURE_INJECTION_RC=$?"
grep -E '^(test_|OK|FAILED|Ran )' "$ROOT/qual/failure_injection.log" | tail -40 | tee -a "$LOG"

say "V5_REGRESSION_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest -v agent_service.tests.test_v5_optimizations > "$ROOT/qual/v5_regression.log" 2>&1
say "V5_REGRESSION_RC=$?"
grep -E '^(test_|OK|FAILED|Ran )' "$ROOT/qual/v5_regression.log" | tail -40 | tee -a "$LOG"

say "V4_REGRESSION_START"
docker run --rm -w /app -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$IMG" \
  -m unittest -v agent_service.tests.test_v4_regression > "$ROOT/qual/v4_regression.log" 2>&1
say "V4_REGRESSION_RC=$?"
grep -E '^(test_|OK|FAILED|Ran )' "$ROOT/qual/v4_regression.log" | tail -40 | tee -a "$LOG"

say "QUAL_DONE"
