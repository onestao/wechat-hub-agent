#!/bin/bash
# RC.14 Agent V5 - offline benchmark matrix.
#
#   Set 1 "sealed"   : mock Core byte-faithful to the Phase-5 harness
#                      (/v1/events/commit -> 200, no injected latency).
#                      Fidelity control: must reproduce the Phase-5 numbers.
#   Set 2 "faithful" : production-shaped mock Core (/v1/events/commit -> 404)
#                      with the Phase-5 measured live Core p50 latency injected
#                      per endpoint. This is the production-representative set.
#
#   A = V4 image + /mnt/user   (FUSE shfs)
#   B = V5 image + /mnt/user   (FUSE shfs)
#   C = V5 image + /mnt/disk3  (direct XFS, same physical disk)
#
# 3 interleaved rounds per set. Same sealed workload, same base clone, same
# batch 400, WAL + synchronous=FULL, mock Core only.
#
# Never touches the production Agent/Core, their DB/WAL/SHM, or the production
# consumer id. Every arm writes to its own throwaway clone.
set -uo pipefail

TS=$(date -u +%Y%m%dT%H%M%SZ)
ROOT=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-$TS
FROOT=/mnt/user/appdata/wechat-hub-f-live/test/rc14-agent-v5-$TS
DROOT=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-$TS
BASE=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-phase5-20260916T094055Z
SNAP=$BASE/clone/base.sqlite
WORKLOAD=$BASE/work/workload-forward.jsonl
H=replay_harness_v5.py

V4_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:c93007426738733c3bb9c3021e43edfd724c7c5455a2b7cf7a7b9101733f463a
V5_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:0eff09ff197b5a27d2687cb5f4a11f23f55ea5c6e0a37cff00bb065beec35492

EVENTS=${EVENTS:-6000}
BATCH=${BATCH:-400}
LOG=$ROOT/matrix.log
DONE=$ROOT/matrix.done

mkdir -p "$ROOT/work" "$ROOT/bench" "$DROOT/bench-direct"
cp -f /root/rc14-v5/repo/bench/$H "$ROOT/work/$H"
: > "$LOG"
rm -f "$DONE"

say() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
arr()  { grep -E 'mdResync(Action|Pos)=' /proc/mdstat | tr '\n' ' '; }

run_arm() { # $1=label $2=image $3=fuse|direct $4=core_mode $5=extra
  local L=$1 IMG=$2 KIND=$3 CM=$4 EXTRA=$5
  local TGT
  if [ "$KIND" = fuse ]; then TGT=$FROOT/bench/$L; else TGT=$DROOT/bench-direct/$L; fi
  mkdir -p "$TGT"
  rm -f "$TGT/db.sqlite" "$TGT/db.sqlite-wal" "$TGT/db.sqlite-shm"
  cp -f "$SNAP" "$TGT/db.sqlite"
  sync
  say "ARM_START label=$L kind=$KIND core_mode=$CM image=$IMG base_sha=$(sha256sum "$TGT/db.sqlite" | cut -d' ' -f1) base_bytes=$(stat -c %s "$TGT/db.sqlite") array=[$(arr)]"
  docker run --rm --name "v5-$L" -v "$ROOT/work:/work" -v "$TGT:/data" \
    --entrypoint /usr/local/bin/python "$IMG" "/work/$H" \
    --db /data/db.sqlite --workload "$WORKLOAD" \
    --out "/work/bench-$L.jsonl" --variant "$L" \
    --consumer-id "v5bench-$L" --batch "$BATCH" --events "$EVENTS" \
    --core-mode "$CM" --instrument --post-reopen-integrity $EXTRA >> "$LOG" 2>&1
  say "ARM_RC=$? label=$L array_after=[$(arr)] final_bytes=$(stat -c %s "$TGT/db.sqlite" 2>/dev/null)"
}

say "MATRIX_START ts=$TS events=$EVENTS batch=$BATCH snapshot=$SNAP"
say "SNAPSHOT_SHA=$(sha256sum "$SNAP" | cut -d' ' -f1) WORKLOAD_SHA=$(sha256sum "$WORKLOAD" | cut -d' ' -f1)"
say "HARNESS_SHA=$(sha256sum "$ROOT/work/$H" | cut -d' ' -f1)"
say "V4_IMAGE=$V4_IMAGE"
say "V5_IMAGE=$V5_IMAGE"
say "ARRAY_FULL=[$(arr)] mdNumDisabled=$(grep -m1 mdNumDisabled= /proc/mdstat) mdNumInvalid=$(grep -m1 mdNumInvalid= /proc/mdstat)"
say "PROD_AGENT_DB_SHA256_BEFORE=$(sha256sum /mnt/disk3/appdata/wechat-hub-f-live/agent-data/wechat-agent.sqlite | cut -d' ' -f1)"

for i in 1 2 3; do
  say "ROUND=$i"
  run_arm "A1-run$i" "$V4_IMAGE" fuse sealed ""
  run_arm "B1-run$i" "$V5_IMAGE" fuse sealed ""
  run_arm "C1-run$i" "$V5_IMAGE" direct sealed ""
  if [ "$i" = 1 ]; then
    run_arm "A2-run$i" "$V4_IMAGE" fuse faithful "--replay-check"
    run_arm "B2-run$i" "$V5_IMAGE" fuse faithful "--replay-check"
    run_arm "C2-run$i" "$V5_IMAGE" direct faithful "--replay-check"
  else
    run_arm "A2-run$i" "$V4_IMAGE" fuse faithful ""
    run_arm "B2-run$i" "$V5_IMAGE" fuse faithful ""
    run_arm "C2-run$i" "$V5_IMAGE" direct faithful ""
  fi
done

# V5-1 defect reproduction: an account absent from /v1/accounts on an event type
# the clone's only enabled monitor matches. V4 forces a Core fetch per event;
# V5 is TTL-bounded. Labelled as a defect probe, not a production measurement.
say "DEFECT_PROBE_START"
run_arm "D4-v4" "$V4_IMAGE" fuse faithful "--synthetic-defect 400 --accounts-omit f-live-a"
run_arm "D5-v5" "$V5_IMAGE" fuse faithful "--synthetic-defect 400 --accounts-omit f-live-a"
say "DEFECT_PROBE_END"

say "PROD_AGENT_DB_SHA256_AFTER=$(sha256sum /mnt/disk3/appdata/wechat-hub-f-live/agent-data/wechat-agent.sqlite | cut -d' ' -f1)"
say "ARRAY_FULL_AFTER=[$(arr)]"
say "MATRIX_DONE"
touch "$DONE"
