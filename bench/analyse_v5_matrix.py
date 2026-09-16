#!/usr/bin/env python3
"""RC.14 Agent V5 - parse a matrix.log into the §6 tables.

Reads the ``SUMMARY=<json>`` lines (plus ``ARM_RC``/``POST_REOPEN_QUICKCHECK``
lines) from a run_v5_matrix.sh log and emits the tables the work package asks
for, including the paired A/B/C medians and the V5-attributable ratios.

Usage:  python analyse_v5_matrix.py <matrix.log> [--json out.json]
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict

GROUPS = ("A1", "B1", "C1", "A2", "B2", "C2", "D4", "D5")


def parse(path: str):
    summaries, quickchecks, arms = [], [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("SUMMARY="):
                try:
                    summaries.append(json.loads(line[len("SUMMARY="):]))
                except json.JSONDecodeError:
                    pass
            elif line.startswith("POST_REOPEN_QUICKCHECK="):
                quickchecks.append(line.split("=", 1)[1])
            elif line.startswith("ARM_RC=") or line.startswith("ARM_START "):
                arms.append(line)
    return summaries, quickchecks, arms


def group_of(variant: str) -> str:
    m = re.match(r"^([A-Z]\d)-", variant or "")
    return m.group(1) if m else (variant or "?")


def median(xs):
    return statistics.median(xs) if xs else None


def mn(xs):
    return min(xs) if xs else None


def mx(xs):
    return max(xs) if xs else None


def main() -> int:
    log = sys.argv[1]
    out_json = None
    if "--json" in sys.argv:
        out_json = sys.argv[sys.argv.index("--json") + 1]

    summaries, quickchecks, arms = parse(log)

    by = defaultdict(list)
    for s in summaries:
        by[(group_of(s.get("variant")), s.get("core_mode"))].append(s)

    print("=" * 100)
    print("PER-ARM")
    print("=" * 100)
    hdr = ("arm", "cm", "eps", "bat_p50", "txn_p50", "commit_p50", "wal", "dup",
           "acct/b", "c404/b", "ack/b", "cp/b", "ifetch", "ihit")
    print("{:<9}{:<10}{:>9}{:>10}{:>10}{:>11}{:>10}{:>5}{:>9}{:>8}{:>7}{:>7}{:>8}{:>6}".format(*hdr))
    for g in GROUPS:
        for cm in ("sealed", "faithful"):
            for s in sorted(by.get((g, cm), []), key=lambda r: r.get("variant", "")):
                print("{:<9}{:<10}{:>9.3f}{:>10.1f}{:>10.2f}{:>11.2f}{:>10}{:>5}{:>9.4f}{:>8.4f}{:>7.4f}{:>7.4f}{:>8}{:>6}".format(
                    s.get("variant"), cm, s.get("EVENTS_PER_SECOND") or 0,
                    s.get("BATCH_P50_MS") or 0, s.get("LOCAL_TXN_P50_MS") or 0,
                    s.get("SQLITE_COMMIT_P50_MS") or 0, s.get("WAL_AFTER_COMMIT_MEDIAN") or 0,
                    s.get("TOTAL_DUPLICATES"), s.get("ACCOUNTS_CALLS_PER_BATCH") or 0,
                    s.get("COMMIT_404_CALLS_PER_BATCH") or 0, s.get("ACK_CALLS_PER_BATCH") or 0,
                    s.get("CHECKPOINT_CALLS_PER_BATCH") or 0,
                    s.get("IDENTITY_FETCHES"), s.get("IDENTITY_CACHE_HITS")))

    print()
    print("=" * 100)
    print("MEDIANS PER GROUP  (n = runs)")
    print("=" * 100)
    print("{:<6}{:<10}{:>3}{:>11}{:>11}{:>11}{:>8}".format("grp", "cm", "n", "eps_med", "eps_min", "eps_max", "spread%"))
    med = {}
    for g in GROUPS:
        for cm in ("sealed", "faithful"):
            rows = by.get((g, cm), [])
            if not rows:
                continue
            e = sorted(r.get("EVENTS_PER_SECOND") or 0 for r in rows)
            m = median(e)
            spread = (100.0 * (e[-1] - e[0]) / m) if m else 0.0
            med[(g, cm)] = {"n": len(e), "median": m, "min": e[0], "max": e[-1], "spread_pct": round(spread, 2)}
            print("{:<6}{:<10}{:>3}{:>11.3f}{:>11.3f}{:>11.3f}{:>8.1f}".format(g, cm, len(e), m, e[0], e[-1], spread))

    print()
    print("=" * 100)
    print("PAIRED RATIOS (V5-attributable; A/B/C interleaved so host drift cancels)")
    print("=" * 100)
    ratios = {}
    for cm in ("sealed", "faithful"):
        a = med.get(("A1" if cm == "sealed" else "A2", cm))
        b = med.get(("B1" if cm == "sealed" else "B2", cm))
        c = med.get(("C1" if cm == "sealed" else "C2", cm))
        if a and b:
            r = b["median"] / a["median"]
            ratios[f"V5_GAIN_VS_V4_FUSE_{cm}"] = round(r, 4)
            print(f"  {cm:<9} B/A  (V5 vs V4, both /mnt/user) = {r:.4f}  ({100*(r-1):+.2f} %)")
        if a and c:
            r = c["median"] / a["median"]
            ratios[f"V5_DIRECT_GAIN_VS_V4_FUSE_{cm}"] = round(r, 4)
            print(f"  {cm:<9} C/A  (V5 direct vs V4 fuse)     = {r:.4f}  ({100*(r-1):+.2f} %)")
        if b and c:
            r = c["median"] / b["median"]
            ratios[f"FUSE_OVER_DIRECT_{cm}"] = round(r, 4)
            print(f"  {cm:<9} C/B  (fuse penalty, V5)         = {r:.4f}")

    print()
    print("=" * 100)
    print("DURABILITY / GOVERNANCE")
    print("=" * 100)
    qc = defaultdict(int)
    for q in quickchecks:
        qc[q.split(" seconds=")[0]] += 1
    for k, v in sorted(qc.items()):
        print(f"  [{v:>2}x] {k}")
    print()
    print("  ARM_RC lines:")
    for a in arms:
        if a.startswith("ARM_RC="):
            print("   ", a)

    if out_json:
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump({"medians": {f"{k[0]}|{k[1]}": v for k, v in med.items()},
                       "ratios": ratios,
                       "quickchecks": dict(qc)}, fh, indent=2)
        print(f"\nWROTE {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
