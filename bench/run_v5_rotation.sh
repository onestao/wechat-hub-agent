#!/bin/bash
# RC.14 Agent V5 - order-effect control for the direct-vs-FUSE anomaly.
#
# Round 1 of the main matrix produced A(V4+FUSE)=95.433, B(V5+FUSE)=92.902,
# C(V5+direct)=53.605 ev/s, i.e. the FUSE arms were ~1.7x FASTER than the
# direct arm. That is the inverse of the Phase-5 result (direct 79.982 vs
# FUSE 43.194) and the ratio magnitude is similar (1.73 vs 1.85), which is
# consistent with either
#   (a) a genuine arm/systematic effect, or
#   (b) host-state drift, because the main matrix runs A,B,C in a fixed order
#       inside every round, so a monotonically degrading host biases C.
#
# This control rotates the order to C,A,B. If C is still slowest, order is not
# the cause. If C becomes fastest, the main matrix's C numbers are order-biased
# and must not be reported as a direct-vs-FUSE measurement.
set -uo pipefail

TS=$(date -u +%Y%m%dT%H%M%SZ)
ROOT=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-rot-$TS
FROOT=/mnt/user/appdata/wechat-hub-f-live/test/rc14-agent-v5-rot-$TS
DROOT=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-rot-$TS
BASE=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-phase5-20260916T094055Z
SNAP=$BASE/clone/base.sqlite
HOSTWORKLOAD=$BASE/work/workload-forward.jsonl
WORKLOAD=/work/workload-forward.jsonl
H=replay_harness_v5.py

V4_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:c93007426738733c3bb9c3021e43edfd724c7c5455a2b7cf7a7b9101733f463a
V5_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:0eff09ff197b5a27d2687cb5f4a11f23f55ea5c6e0a37cff00bb065beec35492

EVENTS=${EVENTS:-6000}
BATCH=${BATCH:-400}
CM=${CM:-sealed}
LOG=$ROOT/rotation.log
DONE=$ROOT/rotation.done

mkdir -p "$ROOT/work" "$ROOT/bench" "$DROOT/bench-direct"
cp -f /root/rc14-v5/repo/bench/$H "$ROOT/work/$H"
cp -f "$HOSTWORKLOAD" "$ROOT/work/workload-forward.jsonl"
: > "$LOG"
rm -f "$DONE"

say() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
arr()  { grep -E 'mdResync(Action|Pos)=' /proc/mdstat | tr '\n' ' '; }

run_arm() { # $1=label $2=image $3=fuse|direct $4=core_mode
  local L=$1 IMG=$2 KIND=$3 CMODE=$4
  local TGT
  if [ "$KIND" = fuse ]; then TGT=$FROOT/bench/$L; else TGT=$DROOT/bench-direct/$L; fi
  mkdir -p "$TGT"
  rm -f "$TGT/db.sqlite" "$TGT/db.sqlite-wal" "$TGT/db.sqlite-shm"
  cp -f "$SNAP" "$TGT/db.sqlite"
  sync
  say "ARM_START label=$L kind=$KIND core_mode=$CMODE image=$IMG base_sha=$(sha256sum "$TGT/db.sqlite" | cut -d' ' -f1) base_bytes=$(stat -c %s "$TGT/db.sqlite") array=[$(arr)]"
  docker run --rm --name "v5rot-$L" -v "$ROOT/work:/work" -v "$TGT:/data" \
    --entrypoint /usr/local/bin/python "$IMG" "/work/$H" \
    --db /data/db.sqlite --workload "$WORKLOAD" \
    --out "/work/bench-$L.jsonl" --variant "$L" \
    --consumer-id "v5rot-$L" --batch "$BATCH" --events "$EVENTS" \
    --core-mode "$CMODE" --instrument --post-reopen-integrity >> "$LOG" 2>&1
  say "ARM_RC=$? label=$L array_after=[$(arr)] final_bytes=$(stat -c %s "$TGT/db.sqlite" 2>/dev/null)"
}

say "ROTATION_START ts=$TS events=$EVENTS batch=$BATCH core_mode=$CM $SNAP"
say "SNAPSHOT_SHA=$(sha256sum "$SNAP" | cut -d' ' -f1)"
say "HARNESS_SHA=$(sha256sum "$ROOT/work/$H" | cut -d' ' -f1)"
say "ARRAY_FULL=[$(arr)]"

# Order C, A, B - the direct arm now runs FIRST in the sequence.
say "ORDER=C,A,B"
run_arm "C1-rot" "$V5_IMAGE" direct "$CM"
run_arm "A1-rot" "$V4_IMAGE" fuse   "$CM"
run_arm "B1-rot" "$V5_IMAGE" fuse   "$CM"

say "ARRAY_FULL_AFTER=[$(arr)]"
say "ROTATION_DONE"
touch "$DONE"
