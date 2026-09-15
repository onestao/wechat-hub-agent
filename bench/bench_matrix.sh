#!/bin/bash
# RC.14 V4 - offline performance matrix.
#
#   arm V3 : pinned V3 image            + replay_harness.py    batch 200
#            (per-batch SQLite connection open/close lifecycle)
#   arm V4 : V4 candidate image          + replay_harness_v4.py batch 400
#            (one long-lived writer connection for the whole process)
#
# Same source workload, same base snapshot, same WAL + synchronous=FULL, same
# indexes, same receipt semantics. Runs are INTERLEAVED so both arms see the
# same array state. 3 runs per arm.
#
# Never touches the production Core or its DB/WAL/SHM.
set -uo pipefail

D=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-phase3
R=/mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v4
V3_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:9c70592028bb08901330d0c2f62833de9d30ccdd326deafb1a4b30872c33b411
V4_IMAGE=ghcr.io/onestao/wechat-hub-agent:0.1.0-rc.14-agent-catchup-v4
SNAP=$D/snapshot/agent-prod-snapshot.sqlite
WORKLOAD=/work/workload/workload-forward.jsonl
EVENTS=${EVENTS:-5000}
LOG=$R/bench-matrix.log
DONE=$R/bench-matrix.done
mkdir -p "$R/bench"
: > "$LOG"
rm -f "$DONE"

say() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
arr()  { grep -E 'mdResync(Action|Pos|Size)=' /proc/mdstat | tr '\n' ' '; }

ram_check() { # $1=label $2=db
  local S=/dev/shm/v4int
  mkdir -p "$S"
  rm -f "$S/db.sqlite"
  cp -f "$2" "$S/db.sqlite"
  local A B INT FK RC SY REC
  A=$(sha256sum "$2" | cut -d' ' -f1)
  B=$(sha256sum "$S/db.sqlite" | cut -d' ' -f1)
  INT=$(sqlite3 "$S/db.sqlite" 'PRAGMA integrity_check;' 2>&1 | head -3 | tr '\n' ';')
  FK=$(sqlite3 "$S/db.sqlite" 'PRAGMA foreign_key_check;' 2>&1 | wc -l)
  RC=$(sqlite3 "$S/db.sqlite" 'PRAGMA journal_mode;' 2>&1)
  SY=$(sqlite3 "$S/db.sqlite" 'PRAGMA synchronous;' 2>&1)
  REC=$(sqlite3 "$S/db.sqlite" 'SELECT COUNT(*) FROM event_receipts;' 2>&1)
  say "INTEGRITY label=$1 src_sha=$A ram_sha=$B sha_match=$([ "$A" = "$B" ] && echo YES || echo NO) integrity=$INT fk_violations=$FK journal_mode=$RC synchronous=$SY receipts=$REC"
  rm -f "$S/db.sqlite"
  rmdir "$S" 2>/dev/null
  say "DEV_SHM_AFTER_CLEANUP=[$(ls -A /dev/shm | tr '\n' ' ')]"
}

run_arm() { # $1=label $2=batch $3=image $4=harness $5=extra
  local L=$1 B=$2 IMG=$3 H=$4 EXTRA=$5
  local TGT=$R/bench/$L
  mkdir -p "$TGT"
  rm -f "$TGT/db.sqlite" "$TGT/db.sqlite-wal" "$TGT/db.sqlite-shm"
  cp -f "$SNAP" "$TGT/db.sqlite"
  sync
  say "ARM_START label=$L batch=$B harness=$H array_before=[$(arr)] base_sha=$(sha256sum "$TGT/db.sqlite" | cut -d' ' -f1) base_bytes=$(stat -c %s "$TGT/db.sqlite")"
  docker run --rm --name "v4-$L" -v "$D:/work" -v "$TGT:/data" \
    --entrypoint /usr/local/bin/python "$IMG" "/work/$H" \
    --db /data/db.sqlite --workload "$WORKLOAD" \
    --out "/work/bench-$L.jsonl" --variant "$L" \
    --consumer-id "v4bench-$L" --batch "$B" --events "$EVENTS" \
    --instrument $EXTRA >> "$LOG" 2>&1
  say "ARM_RC=$? label=$L array_after=[$(arr)] final_bytes=$(stat -c %s "$TGT/db.sqlite" 2>/dev/null)"
  ls -la "$TGT" >> "$LOG" 2>&1
}

say "MATRIX_START events=$EVENTS snapshot=$SNAP workload=$WORKLOAD"
say "ARRAY_FULL_BEFORE=[$(arr)] mdNumDisabled=$(grep -m1 mdNumDisabled= /proc/mdstat) mdNumInvalid=$(grep -m1 mdNumInvalid= /proc/mdstat)"
say "V3_IMAGE=$V3_IMAGE"
say "V4_IMAGE=$V4_IMAGE v4_commit=$(tr -d '\r\n' < "$R/V4_SOURCE_COMMIT.txt" 2>/dev/null)"

for i in 1 2 3; do
  say "ROUND=$i"
  run_arm "V3-run$i" 200 "$V3_IMAGE" replay_harness.py    "--mode current"
  ram_check "V3-run$i" "$R/bench/V3-run$i/db.sqlite"
  run_arm "V4-run$i" 400 "$V4_IMAGE" replay_harness_v4.py "--post-reopen-integrity --replay-check"
  ram_check "V4-run$i" "$R/bench/V4-run$i/db.sqlite"
done

say "ARRAY_FULL_AFTER=[$(arr)]"

# --- collect the metric set ------------------------------------------------
say "COLLECT_START"
for f in "$D"/bench-V3-run*.jsonl.summary.json "$D"/bench-V4-run*.jsonl.summary.json; do
  [ -f "$f" ] || continue
  echo "### $(basename "$f")" >> "$LOG"
  jq -c '{variant,batch,TOTAL_EVENTS,TOTAL_SECONDS,EVENTS_PER_SECOND,PROJECTED_270K_SECONDS,BATCH_P50_MS,BATCH_P95_MS,SQLITE_COMMIT_P50_MS,SQLITE_COMMIT_P95_MS,CONN_CLOSE_P50_MS,CONN_CLOSE_P95_MS,CONN_CLOSE_SAMPLES,LOCAL_TXN_P50_MS,LOCAL_TXN_P95_MS,WRITER_OPENS,WRITER_OPENS_PER_BATCH,WRITER_CLOSE_SAMPLES,CORE_POLL_CALLS,CORE_POLL_LIMIT_MAX,TOTAL_DUPLICATES,DB_BYTES_END,WAL_BYTES_END,RECEIPTS_END,REPLAY,SHUTDOWN_RESULT,WRITER_STATS,ARRAY_STATE_START,ARRAY_STATE_END}' "$f" >> "$LOG" 2>&1
done
say "COLLECT_DONE"
say "MATRIX_DONE"
touch "$DONE"
