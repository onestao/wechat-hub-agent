#!/bin/bash
# RC.14 Agent V5 - post-reopen durability pass over the arm DBs (v2).
#
# The cheap header readout (journal_mode / synchronous / page_count / WAL size)
# is taken for EVERY arm. The expensive full scan (quick_check +
# foreign_key_check) is taken for a bounded subset, because on the degraded
# array a single 815 MB scan can take minutes and the direct path is far slower
# than the FUSE path - which is itself a result, so the scan timings are kept.
set -uo pipefail

ROOT=${1:-}
if [ -z "$ROOT" ]; then ROOT=$(ls -dt /mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-* | head -1); fi
FROOT=/mnt/user/appdata/wechat-hub-f-live/test/$(basename "$ROOT")
DROOT=$ROOT
V4_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:c93007426738733c3bb9c3021e43edfd724c7c5455a2b7cf7a7b9101733f463a
V5_IMAGE=ghcr.io/onestao/wechat-hub-agent@sha256:0eff09ff197b5a27d2687cb5f4a11f23f55ea5c6e0a37cff00bb065beec35492
OUT=$ROOT/verify.log

# SCAN_ARMS: the subset that gets the full scan. One per (image, path) cell,
# taken from the last round so the DB is a fully-written production-size clone.
SCAN_ARMS=${SCAN_ARMS:-"A1-run3 B1-run3 C1-run3"}

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT"; }
: > "$OUT"

run_one() { # $1=dbpath $2=image $3=scan?
  local DB=$1 IMG=$2 SCAN=$3 EXTRA=""
  [ "$SCAN" = scan ] && EXTRA="--scan"
  local DIR
  DIR=$(dirname "$DB")
  say "VERIFY_START db=$DB scan=$SCAN image=$IMG"
  docker run --rm -v "$DIR:/data" -v "$ROOT/work:/work" --entrypoint /usr/local/bin/python "$IMG" \
    /work/db_verify.py /data/db.sqlite $EXTRA 2>&1 | tee -a "$OUT"
  say "VERIFY_RC=$?"
}

mkdir -p "$ROOT/work"
cp -f /root/rc14-v5/repo/bench/db_verify.py "$ROOT/work/db_verify.py"

say "VERIFY_PASS_START root=$ROOT"
say "ARRAY=[$(grep -E 'mdResync(Action|Pos)=' /proc/mdstat | tr '\n' ' ')]"

for ARM in A1-run1 A1-run2 A1-run3 B1-run1 B1-run2 B1-run3 C1-run1 C1-run2 C1-run3 \
           A2-run1 A2-run2 A2-run3 B2-run1 B2-run2 B2-run3 C2-run1 C2-run2 C2-run3; do
  if [ -f "$FROOT/bench/$ARM/db.sqlite" ]; then
    DB=$FROOT/bench/$ARM/db.sqlite
    case "$ARM" in A1-*|A2-*) IMG=$V4_IMAGE ;; *) IMG=$V5_IMAGE ;; esac
    case " $SCAN_ARMS " in *" $ARM "*) SCAN=scan ;; *) SCAN=fast ;; esac
    run_one "$DB" "$IMG" "$SCAN"
  fi
  if [ -f "$DROOT/bench-direct/$ARM/db.sqlite" ]; then
    DB=$DROOT/bench-direct/$ARM/db.sqlite
    case " $SCAN_ARMS " in *" $ARM "*) SCAN=scan ;; *) SCAN=fast ;; esac
    run_one "$DB" "$V5_IMAGE" "$SCAN"
  fi
done

say "VERIFY_PASS_DONE"
