#!/bin/bash
# RC.14 Agent V5 - collect the offline matrix into one compact table + medians.
set -uo pipefail

ROOT=${1:-}
if [ -z "$ROOT" ]; then ROOT=$(ls -dt /mnt/disk3/appdata/wechat-hub-f-live/test/rc14-agent-v5-* | head -1); fi
OUT=$ROOT/collected.tsv
COLLECT=$ROOT/collected.txt

{
echo "=== per-arm key metrics ==="
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  arm core_mode eps batch_p50 local_txn_p50 commit_p50 wal_after_commit dup \
  acct_per_batch c404_per_batch ack_per_batch cp_per_batch identity_fetches
for f in "$ROOT"/work/bench-*.jsonl.summary.json; do
  [ -f "$f" ] || continue
  jq -r '[.variant,.core_mode,.EVENTS_PER_SECOND,.BATCH_P50_MS,.LOCAL_TXN_P50_MS,
          .SQLITE_COMMIT_P50_MS,.WAL_AFTER_COMMIT_MEDIAN,.TOTAL_DUPLICATES,
          .ACCOUNTS_CALLS_PER_BATCH,.COMMIT_404_CALLS_PER_BATCH,
          .ACK_CALLS_PER_BATCH,.CHECKPOINT_CALLS_PER_BATCH] | @tsv' "$f"
done

echo
echo "=== medians per (variant-prefix, core_mode) ==="
printf '%s\t%s\t%s\t%s\t%s\t%s\n' group core_mode n eps_median eps_min eps_max
for G in A1 B1 C1 A2 B2 C2 D4 D5; do
  for CM in sealed faithful; do
    files=$(ls "$ROOT"/work/bench-${G}-*.jsonl.summary.json 2>/dev/null)
    [ -n "$files" ] || continue
    jq -s -r --arg g "$G" --arg cm "$CM" '
      [.[] | select(.core_mode==$cm)] as $rows
      | ($rows | map(.EVENTS_PER_SECOND) | sort) as $e
      | if ($e|length)==0 then empty else
        [$g,$cm,($e|length),($e[((($e|length)-1)/2)|floor]),
         ($e[0]),($e[-1])] | @tsv end' $files 2>/dev/null
  done
done

echo
echo "=== integrity / durability assertions (per arm) ==="
grep -hE '^POST_REOPEN_QUICKCHECK=' "$ROOT/matrix.log" | sort | uniq -c
echo
echo "=== replay arms ==="
grep -hE '^REPLAY=' "$ROOT/matrix.log" | tail -6
echo
echo "=== arm wall times ==="
grep -hE 'ARM_START label=|ARM_RC=' "$ROOT/matrix.log" | tail -50
echo
echo "=== array + prod DB governance ==="
grep -hE 'ARRAY_FULL|PROD_AGENT_DB_SHA256|SNAPSHOT_SHA|WORKLOAD_SHA|HARNESS_SHA' "$ROOT/matrix.log"
} > "$COLLECT" 2>&1

echo "COLLECTED=$COLLECT"
wc -l "$COLLECT"
