#!/usr/bin/env python3
"""RC.14 Agent V4 - offline real-workload replay harness (V4 arm).

This is the V4 counterpart of ``replay_harness.py`` (the V3 arm harness). It
drives the SAME mock-Core / SAME workload / SAME base snapshot / SAME receipt
semantics, and differs only in the thing under test:

  * V3 arm  : pinned V3 image (revision 49a863ae...) + ``replay_harness.py``
              batch 200, per-batch connection open/close lifecycle.
  * V4 arm  : V4 candidate image (long-lived writer) + THIS harness
              batch 400, one writer connection for the whole process.

Instrumentation philosophy: nothing is re-implemented. The real
``AgentStorage.session`` is *wrapped* (not replaced) so the measured local
transaction is the shipped code path. ``commit()`` timing is taken from a thin
subclass of the shipped ``WriterConnection`` that delegates to
``sqlite3.Connection.commit`` -- again, the real commit, only timed.

Hard guarantees (identical to the V3 harness):
  * never contacts the production Core (mock server on 127.0.0.1 only)
  * refuses the production consumer id
  * POST /v1/send/text is hard-blocked (HTTP 409) -> zero real sends
  * writes only to the --db target given on the command line
  * never reads the live Core DB/WAL/SHM
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, "/app")

import agent_service.storage as storage_mod                            # noqa: E402
from agent_service.service import AgentService, AgentSettings          # noqa: E402
from agent_service.storage import AgentStorage                         # noqa: E402

ACCOUNTS = [
    {"account_id": "f-live-a", "display_name": "F-Live-A", "enabled": True,
     "instance_uuid": "40667b7e-14e8-448b-941d-66943c659a85",
     "wechat_identity_uuid": "40887bed-6c2b-4248-bf78-3ad12f2bdc9e",
     "identity_binding_state": "bound"},
    {"account_id": "testB", "display_name": "US", "enabled": True,
     "instance_uuid": "16d1d48b-87ea-4b09-9961-0897aaf1cfb9",
     "wechat_identity_uuid": "00000000-0000-4000-8000-000000000001",
     "identity_binding_state": "bound"},
]


def md_state() -> dict:
    """Host array parity-check state (global kernel file, readable in container)."""
    out = {"action": "", "pos": 0, "size": 0, "pct": 0.0, "resync": 0, "dt": 0}
    try:
        with open("/proc/mdstat", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("mdResyncAction="):
                    out["action"] = line.split("=", 1)[1].strip()
                elif line.startswith("mdResyncPos="):
                    out["pos"] = int(line.split("=", 1)[1].strip() or 0)
                elif line.startswith("mdResyncSize="):
                    out["size"] = int(line.split("=", 1)[1].strip() or 0)
                elif line.startswith("mdResync="):
                    out["resync"] = int(line.split("=", 1)[1].strip() or 0)
                elif line.startswith("mdResyncDt="):
                    out["dt"] = int(line.split("=", 1)[1].strip() or 0)
    except Exception as exc:  # pragma: no cover
        out["error"] = str(exc)
    if out["size"]:
        out["pct"] = round(100.0 * out["pos"] / out["size"], 2)
    out["active"] = bool(out["resync"] or out["dt"])
    return out


class MockCore:
    """Cursor-authoritative mock Core. Enforces the frozen 200 cap."""

    HARD_LIMIT = 200

    def __init__(self, events):
        self.events = events
        self.head = int(events[-1]["cursor"]) if events else 0
        self.lock = threading.Lock()
        self.n_poll = 0
        self.n_commit = 0
        self.n_send_blocked = 0
        self.checkpoint_cursor = 0
        self.poll_limits: list[int] = []

    def poll(self, after, limit):
        limit = max(1, min(int(limit), self.HARD_LIMIT))
        out = []
        for e in self.events:
            if int(e["cursor"]) > after:
                out.append(e)
                if len(out) >= limit:
                    break
        nxt = int(out[-1]["cursor"]) if out else after
        return {"events": out, "next_cursor": nxt, "has_more": self.head > nxt}


def make_handler(core):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            return

        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return {}

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/health":
                return self._json({"status": "ok", "contract_version": 1, "service": "mock-core"})
            if u.path == "/v1/accounts":
                return self._json({"accounts": ACCOUNTS})
            if u.path == "/v1/events/poll":
                after = int((q.get("after") or ["0"])[0])
                limit = int((q.get("limit") or ["50"])[0])
                with core.lock:
                    core.n_poll += 1
                    core.poll_limits.append(limit)
                return self._json(core.poll(after, limit))
            if u.path.endswith("/chats"):
                return self._json({"chats": []})
            return self._json({"error": {"code": "not_found", "message": u.path}}, 404)

        def do_POST(self):
            u = urlparse(self.path)
            p = self._body()
            if u.path == "/v1/events/commit":
                with core.lock:
                    core.n_commit += 1
                    core.checkpoint_cursor = int(p.get("processed_through_cursor") or 0)
                return self._json({"consumer_id": p.get("consumer_id"),
                                   "acked_count": len(p.get("event_ids") or []),
                                   "checkpoint": {"consumer_id": p.get("consumer_id"),
                                                  "processed_through_cursor": core.checkpoint_cursor}})
            if u.path == "/v1/events/ack":
                return self._json({"consumer_id": p.get("consumer_id"),
                                   "acked_event_ids": p.get("event_ids") or [],
                                   "acked_count": len(p.get("event_ids") or [])})
            if u.path == "/v1/events/checkpoint":
                with core.lock:
                    core.checkpoint_cursor = int(p.get("processed_through_cursor") or 0)
                return self._json({"consumer_id": p.get("consumer_id"),
                                   "processed_through_cursor": core.checkpoint_cursor})
            if u.path == "/v1/send/text":
                with core.lock:
                    core.n_send_blocked += 1
                return self._json({"error": {"code": "v4_bench_send_blocked",
                                             "message": "sends hard-blocked in bench"}}, 409)
            return self._json({"error": {"code": "not_found", "message": u.path}}, 404)

    return H


REC: dict = {
    "commit_ms": [],
    "rollback_ms": [],
    "local_txn_ms": [],
    "wal_after_commit": [],
    "writer_open_ms": [],
    "writer_close_ms": [],
    "writer_opens": 0,
    "conn_close_ms": [],       # per-batch connection closes: expected 0 in V4
}


def install_instrumentation():
    """Wrap the REAL V4 code path. Nothing is re-implemented."""

    class TimedWriterConnection(storage_mod.WriterConnection):
        """Shipped writer connection, with commit/rollback timed."""

        def commit(self):
            t0 = time.perf_counter()
            try:
                return super().commit()
            finally:
                REC["commit_ms"].append((time.perf_counter() - t0) * 1000.0)

        def rollback(self):
            t0 = time.perf_counter()
            try:
                return super().rollback()
            finally:
                REC["rollback_ms"].append((time.perf_counter() - t0) * 1000.0)

    storage_mod.WriterConnection = TimedWriterConnection

    orig_open_writer = AgentStorage._open_writer

    def counting_open_writer(self):
        REC["writer_opens"] += 1
        t0 = time.perf_counter()
        try:
            return orig_open_writer(self)
        finally:
            REC["writer_open_ms"].append((time.perf_counter() - t0) * 1000.0)

    AgentStorage._open_writer = counting_open_writer

    orig_session = AgentStorage.session

    @contextlib.contextmanager
    def timed_session(self, *a, **kw):
        t0 = time.perf_counter()
        try:
            with orig_session(self, *a, **kw) as conn:
                yield conn
            REC["wal_after_commit"].append(wal_bytes(self.path))
        finally:
            REC["local_txn_ms"].append((time.perf_counter() - t0) * 1000.0)

    AgentStorage.session = timed_session

    orig_close = AgentStorage.close

    def timed_close(self, *a, **kw):
        t0 = time.perf_counter()
        try:
            return orig_close(self, *a, **kw)
        finally:
            REC["writer_close_ms"].append((time.perf_counter() - t0) * 1000.0)

    AgentStorage.close = timed_close


def wal_bytes(p):
    for s in ("-wal", "-journal"):
        q = str(p) + s
        if os.path.exists(q):
            return os.path.getsize(q)
    return 0


def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))]


def receipt_count(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM event_receipts").fetchone()[0]
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--workload", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--consumer-id", required=True)
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--commit-threshold", type=int, default=600)
    ap.add_argument("--commit-interval", type=float, default=20.0)
    ap.add_argument("--events", type=int, default=5000)
    ap.add_argument("--mode", default="current")
    ap.add_argument("--instrument", action="store_true")
    ap.add_argument("--integrity", action="store_true")
    ap.add_argument("--post-reopen-integrity", action="store_true")
    ap.add_argument("--replay-check", action="store_true")
    args = ap.parse_args()

    if args.consumer_id == "wechat-agent":
        print("REFUSING: consumer_id must not be the production consumer id", file=sys.stderr)
        return 2

    events = []
    with open(args.workload, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    if args.events > 0:
        events = events[: args.events]
    md0 = md_state()
    print(f"WORKLOAD_EVENTS={len(events)} FIRST={events[0]['cursor']} LAST={events[-1]['cursor']}", flush=True)
    print(f"ARRAY_STATE_START={json.dumps(md0)}", flush=True)

    core = MockCore(events)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(core))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"MOCK_CORE={base}", flush=True)

    if args.instrument:
        install_instrumentation()

    settings = AgentSettings(
        core_url=base, db_path=pathlib.Path(args.db),
        consumer_id=args.consumer_id, poll_interval_seconds=0.0, poll_timeout_seconds=0,
        poll_batch_size=args.batch, scheduler_interval_seconds=300.0, vector_dim=384,
        core_commit_batch_threshold=args.commit_threshold,
        core_commit_interval_seconds=args.commit_interval)
    svc = AgentService(settings=settings)

    fh = open(args.out, "w", encoding="utf-8")
    t_start = time.perf_counter()
    total_events = total_processed = total_dups = idx = 0
    start_cursor = svc.storage.get_meta("core_cursor", "0") or "0"
    while total_events < len(events) and idx < 500:
        idx += 1
        b0 = time.perf_counter()
        res = svc.process_events_once()
        b1 = time.perf_counter()
        if not res.get("ok"):
            print(f"BATCH_ERROR idx={idx} {res}", flush=True)
            break
        n = int(res.get("events") or 0)
        total_events += n
        total_processed += int(res.get("processed") or 0)
        total_dups += int(res.get("duplicates") or 0)
        row = {"idx": idx, "events": n, "processed": int(res.get("processed") or 0),
               "duplicates": int(res.get("duplicates") or 0),
               "indexed_messages": int(res.get("indexed_messages") or 0),
               "ack_count": int((res.get("ack") or {}).get("acked_count") or 0),
               "has_more": bool(res.get("has_more")),
               "core_polls": res.get("core_polls"),
               "local_batch_target": res.get("local_batch_target"),
               "reported_elapsed_ms": res.get("elapsed_ms"),
               "batch_wall_ms": round((b1 - b0) * 1000.0, 3),
               "db_bytes": os.path.getsize(args.db), "wal_bytes": wal_bytes(args.db),
               "local_cursor": svc.storage.get_meta("core_cursor", "0"),
               "core_checkpoint": core.checkpoint_cursor}
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        print(f"BATCH {idx} events={n} polls={row['core_polls']} wall_ms={row['batch_wall_ms']:.1f} "
              f"wal={row['wal_bytes']} db={row['db_bytes']}", flush=True)
        if n == 0:
            break

    t_end = time.perf_counter()
    wall = t_end - t_start
    fh.close()
    md1 = md_state()

    receipts_after_first = receipt_count(args.db)

    flush_res = svc.flush_core_progress()
    writer_stats = svc.storage.writer_stats()
    print(f"WRITER_STATS={json.dumps(writer_stats)}", flush=True)

    # ---- replay / duplicate-suppression proof -------------------------
    replay = {"performed": False}
    if args.replay_check:
        core.checkpoint_cursor = 0
        svc.storage.set_meta("core_cursor", start_cursor)
        r_events = r_dups = 0
        r_idx = 0
        while r_events < len(events) and r_idx < 500:
            r_idx += 1
            res = svc.process_events_once()
            if not res.get("ok"):
                break
            n = int(res.get("events") or 0)
            r_events += n
            r_dups += int(res.get("duplicates") or 0)
            if n == 0:
                break
        receipts_after_replay = receipt_count(args.db)
        replay = {
            "performed": True,
            "replay_events": r_events,
            "replay_duplicates": r_dups,
            "receipts_before_replay": receipts_after_first,
            "receipts_after_replay": receipts_after_replay,
            "receipts_grew": receipts_after_replay - receipts_after_first,
            "duplicate_receipts_created": receipts_after_replay - receipts_after_first,
        }
        print(f"REPLAY={json.dumps(replay)}", flush=True)

    # ---- explicit shutdown: the ONLY place the writer is closed -------
    close_res = svc.shutdown()
    print(f"SHUTDOWN={json.dumps(close_res)}", flush=True)
    print(f"WRITER_STATS_END={json.dumps(svc.storage.writer_stats())}", flush=True)

    batch_ms = []
    with open(args.out, encoding="utf-8") as f2:
        for line in f2:
            batch_ms.append(json.loads(line)["batch_wall_ms"])

    summary = {
        "harness": "replay_harness_v4",
        "variant": args.variant, "mode": args.mode, "batch": args.batch,
        "instrumented": bool(args.instrument), "workload": os.path.basename(args.workload),
        "consumer_id": args.consumer_id,
        "TOTAL_EVENTS": total_events, "TOTAL_PROCESSED": total_processed,
        "TOTAL_DUPLICATES": total_dups, "TOTAL_BATCHES": idx,
        "TOTAL_SECONDS": round(wall, 3),
        "EVENTS_PER_SECOND": round(total_events / wall, 3) if wall > 0 else 0,
        "BATCH_P50_MS": round(pct(batch_ms, 50), 1),
        "BATCH_P95_MS": round(pct(batch_ms, 95), 1),
        "BATCH_MAX_MS": round(max(batch_ms), 1) if batch_ms else 0,
        "PROJECTED_270K_SECONDS": round(270000 / (total_events / wall), 1) if total_events and wall > 0 else None,
        "PROJECTED_LAG_143K_SECONDS": round(143459 / (total_events / wall), 1) if total_events and wall > 0 else None,
        "SQLITE_COMMIT_P50_MS": round(pct(REC["commit_ms"], 50), 2),
        "SQLITE_COMMIT_P95_MS": round(pct(REC["commit_ms"], 95), 2),
        "SQLITE_COMMIT_MAX_MS": round(max(REC["commit_ms"]), 2) if REC["commit_ms"] else 0,
        "SQLITE_COMMIT_SAMPLES": len(REC["commit_ms"]),
        "SQLITE_ROLLBACK_SAMPLES": len(REC["rollback_ms"]),
        "CONN_CLOSE_P50_MS": round(pct(REC["conn_close_ms"], 50), 2),
        "CONN_CLOSE_P95_MS": round(pct(REC["conn_close_ms"], 95), 2),
        "CONN_CLOSE_SAMPLES": len(REC["conn_close_ms"]),
        "LOCAL_TXN_P50_MS": round(pct(REC["local_txn_ms"], 50), 2),
        "LOCAL_TXN_P95_MS": round(pct(REC["local_txn_ms"], 95), 2),
        "LOCAL_TXN_SAMPLES": len(REC["local_txn_ms"]),
        "WRITER_OPENS": REC["writer_opens"],
        "WRITER_OPEN_MS": round(sum(REC["writer_open_ms"]), 2),
        "WRITER_CLOSE_MS": round(sum(REC["writer_close_ms"]), 2),
        "WRITER_CLOSE_SAMPLES": len(REC["writer_close_ms"]),
        "WRITER_OPENS_PER_BATCH": round(REC["writer_opens"] / idx, 4) if idx else None,
        "WAL_AFTER_COMMIT_MEDIAN": int(pct(REC["wal_after_commit"], 50)),
        "WAL_AFTER_COMMIT_SAMPLES": len(REC["wal_after_commit"]),
        "CORE_POLL_CALLS": core.n_poll, "CORE_COMMIT_CALLS": core.n_commit,
        "CORE_POLL_LIMITS_UNIQUE": sorted(set(core.poll_limits)),
        "CORE_POLL_LIMIT_MAX": max(core.poll_limits) if core.poll_limits else 0,
        "SEND_BLOCKED_CALLS": core.n_send_blocked,
        "FLUSH_RESULT": flush_res, "SHUTDOWN_RESULT": close_res,
        "WRITER_STATS": writer_stats,
        "CORE_CHECKPOINT_CURSOR": core.checkpoint_cursor,
        "ARRAY_STATE_START": md0, "ARRAY_STATE_END": md1,
        "DB_BYTES_END": os.path.getsize(args.db),
        "WAL_BYTES_END": wal_bytes(args.db),
        "RECEIPTS_END": receipts_after_first,
        "REPLAY": replay,
    }
    with open(args.out + ".summary.json", "w", encoding="utf-8") as f3:
        json.dump(summary, f3, indent=2)
    print("SUMMARY=" + json.dumps(summary), flush=True)

    if args.integrity:
        t0 = time.perf_counter()
        conn = sqlite3.connect(args.db)
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        print(f"INTEGRITY={integ} integrity_seconds={round(time.perf_counter()-t0,1)}", flush=True)

    if args.post_reopen_integrity:
        # Cheap post-reopen structural check. The expensive full
        # ``integrity_check`` runs on a disposable /dev/shm copy in the driver
        # script (RC.13 DEV_SHM_DISPOSABLE_SNAPSHOT_LIFECYCLE_POLICY).
        t0 = time.perf_counter()
        conn = sqlite3.connect(args.db)
        qc = conn.execute("PRAGMA quick_check").fetchone()[0]
        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        sy = conn.execute("PRAGMA synchronous").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        conn.close()
        print(f"POST_REOPEN_QUICKCHECK={qc} foreign_key_violations={fk} "
              f"journal_mode={jm} synchronous={sy} page_count={page_count} "
              f"seconds={round(time.perf_counter()-t0,1)}", flush=True)

    srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
