#!/usr/bin/env python3
"""RC.14 Agent V5 - post-reopen durability readout for one arm DB.

Runs INSIDE the frozen image (so it uses the image's own SQLite). Splits the
cheap header assertions from the expensive full scan, because on this degraded
array the scan can take minutes:

  fast  - journal_mode / synchronous / page_count / page_size / file sizes
          (header + pragma only, no scan)
  scan  - quick_check + foreign_key_check (full read of the DB)

Usage: python db_verify.py <db path> [--scan]
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time


def main() -> int:
    path = sys.argv[1]
    do_scan = "--scan" in sys.argv
    label = os.path.basename(os.path.dirname(path))

    sizes = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = path + suffix
        sizes[suffix or "db"] = os.path.getsize(p) if os.path.exists(p) else -1

    t0 = time.perf_counter()
    conn = sqlite3.connect(path)
    jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
    sy = conn.execute("PRAGMA synchronous").fetchone()[0]
    pc = conn.execute("PRAGMA page_count").fetchone()[0]
    ps = conn.execute("PRAGMA page_size").fetchone()[0]
    ac = conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
    fast = time.perf_counter() - t0

    out = [f"ARM={label} journal_mode={jm} synchronous={sy} page_count={pc} "
           f"page_size={ps} wal_autocheckpoint={ac} "
           f"db_bytes={sizes['db']} wal_bytes={sizes['-wal']} shm_bytes={sizes['-shm']} "
           f"fast_readout_s={fast:.2f}"]

    if do_scan:
        t1 = time.perf_counter()
        qc = conn.execute("PRAGMA quick_check").fetchone()[0]
        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        scan = time.perf_counter() - t1
        out.append(f"ARM={label} quick_check={qc} foreign_key_violations={fk} scan_s={scan:.1f}")

    conn.close()
    for line in out:
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
