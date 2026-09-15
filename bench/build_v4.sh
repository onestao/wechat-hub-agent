#!/bin/bash
# RC.14 V4 - build the immutable candidate image from the pushed candidate branch.
#
# The build context is a fresh clone of the exact pushed commit, so the image is
# reproducible from a public ref and carries that commit in its OCI revision
# label. V3 and V4 differ only by the V4 commit series.
set -uo pipefail

ROOT=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v4
REPO=https://github.com/onestao/wechat-hub-agent.git
BRANCH=candidate/rc14-agent-catchup-v4
V4_IMAGE=ghcr.io/onestao/wechat-hub-agent:0.1.0-rc.14-agent-catchup-v4
V3_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:9c70592028bb08901330d0c2f62833de9d30ccdd326deafb1a4b30872c33b411
CTX=$ROOT/ctx
LOG=$ROOT/build.log

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

mkdir -p "$ROOT"
: > "$LOG"
say "BUILD_START branch=$BRANCH"

# --- 1. obtain the source at the pushed candidate commit -------------------
if [ -d "$CTX/.git" ]; then
  say "CTX_REUSE"
  git -C "$CTX" fetch --depth 1 origin "$BRANCH" >>"$LOG" 2>&1
  say "FETCH_RC=$?"
  git -C "$CTX" checkout -f FETCH_HEAD >>"$LOG" 2>&1
  say "CHECKOUT_RC=$?"
else
  git clone --branch "$BRANCH" --depth 1 "$REPO" "$CTX" >>"$LOG" 2>&1
  say "CLONE_RC=$?"
fi

COMMIT=$(git -C "$CTX" rev-parse HEAD)
TREE=$(git -C "$CTX" rev-parse 'HEAD^{tree}')
EXPECTED=$(tr -d '\r\n' < "$ROOT/V4_SOURCE_COMMIT.txt" 2>/dev/null || echo "")
say "CLONE_COMMIT=$COMMIT"
say "CLONE_TREE=$TREE"
say "EXPECTED_COMMIT=$EXPECTED"
say "COMMIT_MATCH=$([ "$COMMIT" = "$EXPECTED" ] && echo YES || echo NO)"
say "REMOTE_BRANCH=$(git -C "$CTX" rev-parse HEAD)"
say "LOG_HEAD=$(git -C "$CTX" log --oneline -3 | tr '\n' ' | ')"

# --- 2. prove the tree carries the V4 markers -----------------------------
cd "$CTX" || exit 9
say "MARKER_WRITER_CONNECTION=$(grep -c 'class WriterConnection' agent_service/storage.py)"
say "MARKER_SYNC_FULL=$(grep -c 'synchronous=FULL' agent_service/storage.py)"
say "MARKER_JOURNAL_WAL=$(grep -c 'journal_mode=WAL' agent_service/storage.py)"
say "MARKER_BATCH_400=$(grep -c 'WECHAT_AGENT_POLL_BATCH\", 400' agent_service/service.py)"
say "MARKER_POLL_CAP=$(grep -c 'CORE_POLL_HARD_LIMIT = 200' agent_service/service.py)"
say "MARKER_CRASH_C1=$(grep -c 'crash_point(\"before_commit\")' agent_service/storage.py)"
say "MARKER_CRASH_C2=$(grep -c 'crash_point(\"after_commit\")' agent_service/storage.py)"
say "MARKER_CRASH_C3=$(grep -c 'after_local_commit_before_core' agent_service/service.py)"
say "MARKER_CRASH_C4=$(grep -c 'shutdown_during_batch' agent_service/service.py)"
say "MARKER_CRASH_C5=$(grep -c 'StorageUnavailableError' agent_service/storage.py)"
say "TEST_FILES=$(ls agent_service/tests | wc -l)"
say "SHA256_STORAGE=$(sha256sum agent_service/storage.py | cut -d' ' -f1)"
say "SHA256_SERVICE=$(sha256sum agent_service/service.py | cut -d' ' -f1)"
say "SHA256_CRASHPOINT=$(sha256sum agent_service/crashpoint.py | cut -d' ' -f1)"

# --- 3. build -------------------------------------------------------------
say "DOCKER_BUILD_START"
docker build \
  --build-arg OCI_REVISION="$COMMIT" \
  --build-arg OCI_VERSION="0.1.0-rc.14-agent-catchup-v4" \
  -t "$V4_IMAGE" "$CTX" >>"$LOG" 2>&1
say "DOCKER_BUILD_RC=$?"

# --- 4. record the immutable identity -------------------------------------
say "IMAGE_ID=$(docker inspect "$V4_IMAGE" --format '{{.Id}}')"
docker inspect "$V4_IMAGE" --format '{{json .Config.Labels}}' \
  | python3 -c 'import json,sys; [print("LABEL %s=%s"%(k,v)) for k,v in json.load(sys.stdin).items()]' >>"$LOG" 2>&1 \
  || docker inspect "$V4_IMAGE" --format '{{json .Config.Labels}}' >>"$LOG" 2>&1
docker inspect "$V4_IMAGE" --format '{{json .RepoDigests}}' >>"$LOG" 2>&1
docker inspect "$V4_IMAGE" --format '{{.Id}} {{.Created}}' | tee -a "$LOG"
docker images --no-trunc --digests | grep -E 'wechat-hub-agent' | tee -a "$LOG"
say "V3_IMAGE_REF=$V3_IMAGE"
say "BUILD_DONE"
