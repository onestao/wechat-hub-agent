#!/usr/bin/env python3
"""RC.14 Agent V5 - offline real-workload replay harness (V5 arms).

Derived from the sealed Phase-5 harness ``replay_harness_v4.py``
(sha256 11fa7896839c190187b065d095e0228bfe3fbd048cdeb6339d8227b5b6075728).
The instrumentation, the mock-Core event source, the workload handling, the
replay/dedup proof and the summary shape are unchanged. What is added is the
minimum needed to measure the two V5 changes honestly:

  * per-endpoint Core call counters, including ``commit-404`` probes, so
    "accounts calls / batch" and "commit-404 calls / batch" are measured rather
    than derived;
  * ``--core-mode``:
      ``sealed``   - byte-faithful Phase-5 mock: ``/v1/events/commit`` -> 200,
                     no injected latency. This is the fidelity control arm and
                     must reproduce the Phase-5 numbers.
      ``faithful`` - production-shaped mock: ``/v1/events/commit`` -> 404 (the
                     production Core has no such endpoint) and the measured live
                     p50 latency is injected per endpoint, so the Core consumer
                     control plane costs what it costs in production.
  * ``--accounts-omit`` / ``--synthetic-defect`` to reproduce the V5-1 defect
    (an account absent from ``/v1/accounts``) on demand.

Hard guarantees (identical to the V4 harness):
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

#: Measured live Core p50 latency (ms) from the Phase-5 RCA probes.
#: Only used by ``--core-mode faithful``; the sealed mock injects nothing.
FAITHFUL_LATENCY_MS = {
    "/v1/accounts": 1269.8,
    "/v1/events/ack": 1085.3,
    "/v1/events/checkpoint": 483.2,
    "/v1/events/poll": 67.6,
    "/v1/events/commit": 70.0,   # the wasted 404 probe
}


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

    def __init__(self, events, *, mode: str = "sealed", omit_accounts: list[str] | None = None):
        self.events = events
        self.head = int(events[-1]["cursor"]) if events else 0
        self.mode = str(mode)
        self.omit = {a for a in (omit_accounts or []) if a}
        self.lock = threading.Lock()
        self.n_poll = 0
        self.n_commit = 0
        self.n_commit_404 = 0
        self.n_ack = 0
        self.n_checkpoint = 0
        self.n_accounts = 0
        self.n_health = 0
        self.n_send_blocked = 0
        self.checkpoint_cursor = 0
        self.poll_limits: list[int] = []

    def accounts(self) -> list[dict]:
        return [dict(row) for row in ACCOUNTS if row["account_id"] not in self.omit]

    def latency_ms(self, path: str) -> float:
        if self.mode != "faithful":
            return 0.0
        return float(FAITHFUL_LATENCY_MS.get(path, 0.0))

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
                with core.lock:
                    core.n_health += 1
                return self._json({"status": "ok", "contract_version": 1, "service": "mock-core"})
            if u.path == "/v1/accounts":
                with core.lock:
                    core.n_accounts += 1
                time.sleep(core.latency_ms("/v1/accounts") / 1000.0)
                return self._json({"accounts": core.accounts()})
            if u.path == "/v1/events/poll":
                after = int((q.get("after") or ["0"])[0])
                limit = int((q.get("limit") or ["50"])[0])
                with core.lock:
                    core.n_poll += 1
                    core.poll_limits.append(limit)
                time.sleep(core.latency_ms("/v1/events/poll") / 1000.0)
                return self._json(core.poll(after, limit))
            if u.path.endswith("/chats"):
                return self._json({"chats": []})
            return self._json({"error": {"code": "not_found", "message": u.path}}, 404)

        def do_POST(self):
            u = urlparse(self.path)
            p = self._body()
            if u.path == "/v1/events/commit":
                if core.mode == "faithful":
                    # The production Core does not implement this endpoint.
                    with core.lock:
                        core.n_commit += 1
                        core.n_commit_404 += 1
                    time.sleep(core.latency_ms("/v1/events/commit") / 1000.0)
                    return self._json({"error": {"code": "not_found", "message": u.path}}, 404)
                with core.lock:
                    core.n_commit += 1
                    core.checkpoint_cursor = int(p.get("processed_through_cursor") or 0)
                return self._json({"consumer_id": p.get("consumer_id"),
                                   "acked_count": len(p.get("event_ids") or []),
                                   "checkpoint": {"consumer_id": p.get("consumer_id"),
                                                  "processed_through_cursor": core.checkpoint_cursor}})
            if u.path == "/v1/events/ack":
                with core.lock:
                    core.n_ack += 1
                time.sleep(core.latency_ms("/v1/events/ack") / 1000.0)
                return self._json({"consumer_id": p.get("consumer_id"),
                                   "acked_event_ids": p.get("event_ids") or [],
                                   "acked_count": len(p.get("event_ids") or [])})
            if u.path == "/v1/events/checkpoint":
                with core.lock:
                    core.n_checkpoint += 1
                    core.checkpoint_cursor = int(p.get("processed_through_cursor") or 0)
                time.sleep(core.latency_ms("/v1/events/checkpoint") / 1000.0)
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
    "conn_close_ms": [],
}


def install_instrumentation():
    """Wrap the REAL shipped code path. Nothing is re-implemented."""

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


def synthetic_defect_events(count: int, account_id: str, start_cursor: int) -> list[dict]:
    """Message events for one account, used to exercise the V5-1 defect path.

    ``message.created`` is the event type the production clone's only enabled
    monitor is bound to, so these events reach ``_resolve_identity()``.
    """
    out = []
    for i in range(count):
        cursor = start_cursor + i + 1
        out.append({
            "event_id": f"defect-evt-{cursor}",
            "cursor": str(cursor),
            "account_id": account_id,
            "event_type": "message.created",
            "occurred_at": "2026-09-16T00:00:00Z",
            "payload": {"message": {"account_id": account_id, "chat_id": "chat-defect",
                                    "message_id": f"m-{cursor}", "type": "text",
                                    "text": "defect probe"}},
        })
    return out


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
    ap.add_argument("--core-mode", default="sealed", choices=["sealed", "faithful"])
    ap.add_argument("--accounts-omit", default="", help="comma separated account ids to hide")
    ap.add_argument("--synthetic-defect", type=int, default=0,
                    help="ignore --workload and emit N message.created events for one account")
    ap.add_argument("--defect-account", default="f-live-a")
    args = ap.parse_args()

    if args.consumer_id == "wechat-agent":
        print("REFUSING: consumer_id must not be the production consumer id", file=sys.stderr)
        return 2

    events = []
    if args.synthetic_defect > 0:
        conn = sqlite3.connect(args.db)
        try:
            row = conn.execute("SELECT value FROM agent_meta WHERE key='core_cursor'").fetchone()
        finally:
            conn.close()
        start = int(row[0]) if row and row[0] not in (None, "") else 0
        events = synthetic_defect_events(args.synthetic_defect, args.defect_account, start)
    else:
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
    print(f"CORE_MODE={args.core_mode} ACCOUNTS_OMIT={args.accounts_omit or 'NONE'}", flush=True)

    omit = [a for a in str(args.accounts_omit).split(",") if a]
    core = MockCore(events, mode=args.core_mode, omit_accounts=omit)
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
    prev = {"accounts": 0, "commit": 0, "commit_404": 0, "ack": 0, "checkpoint": 0}
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
        calls = {"accounts": core.n_accounts, "commit": core.n_commit,
                 "commit_404": core.n_commit_404, "ack": core.n_ack,
                 "checkpoint": core.n_checkpoint}
        delta = {k: calls[k] - prev[k] for k in calls}
        prev = calls
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
               "core_checkpoint": core.checkpoint_cursor,
               "core_calls_cumulative": dict(calls), "core_calls_delta": delta,
               "identity_fetches": getattr(svc.monitor, "identity_fetch_count", None),
               "identity_cache_hits": getattr(svc.monitor, "identity_cache_hit_count", None),
               "identity_unresolved": getattr(svc.monitor, "identity_unresolved_count", None)}
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        print(f"BATCH {idx} events={n} polls={row['core_polls']} wall_ms={row['batch_wall_ms']:.1f} "
              f"acct+{delta['accounts']} commit404+{delta['commit_404']} ack+{delta['ack']} "
              f"cp+{delta['checkpoint']} wal={row['wal_bytes']} db={row['db_bytes']}", flush=True)
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

    close_res = svc.shutdown()
    print(f"SHUTDOWN={json.dumps(close_res)}", flush=True)
    print(f"WRITER_STATS_END={json.dumps(svc.storage.writer_stats())}", flush=True)

    batch_ms = []
    per_batch = []
    with open(args.out, encoding="utf-8") as f2:
        for line in f2:
            row = json.loads(line)
            batch_ms.append(row["batch_wall_ms"])
            per_batch.append(row)

    n_batches = idx if idx else 1

    def per_batch_rate(key: str) -> float:
        return round(sum(r["core_calls_delta"][key] for r in per_batch) / n_batches, 4)

    summary = {
        "harness": "replay_harness_v5",
        "variant": args.variant, "mode": args.mode, "batch": args.batch,
        "core_mode": args.core_mode, "accounts_omit": omit,
        "synthetic_defect": args.synthetic_defect,
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
        "SQLITE_COMMIT_P50_MS": round(pct(REC["commit_ms"], 50), 2),
        "SQLITE_COMMIT_P95_MS": round(pct(REC["commit_ms"], 95), 2),
        "SQLITE_COMMIT_SAMPLES": len(REC["commit_ms"]),
        "LOCAL_TXN_P50_MS": round(pct(REC["local_txn_ms"], 50), 2),
        "LOCAL_TXN_P95_MS": round(pct(REC["local_txn_ms"], 95), 2),
        "LOCAL_TXN_SAMPLES": len(REC["local_txn_ms"]),
        "WRITER_OPENS": REC["writer_opens"],
        "WRITER_OPENS_PER_BATCH": round(REC["writer_opens"] / n_batches, 4),
        "WAL_AFTER_COMMIT_MEDIAN": int(pct(REC["wal_after_commit"], 50)),
        "CORE_POLL_CALLS": core.n_poll,
        "CORE_ACCOUNTS_CALLS": core.n_accounts,
        "CORE_COMMIT_CALLS": core.n_commit,
        "CORE_COMMIT_404_CALLS": core.n_commit_404,
        "CORE_ACK_CALLS": core.n_ack,
        "CORE_CHECKPOINT_CALLS": core.n_checkpoint,
        "CORE_HEALTH_CALLS": core.n_health,
        "ACCOUNTS_CALLS_PER_BATCH": per_batch_rate("accounts"),
        "COMMIT_404_CALLS_PER_BATCH": per_batch_rate("commit_404"),
        "COMMIT_CALLS_PER_BATCH": per_batch_rate("commit"),
        "ACK_CALLS_PER_BATCH": per_batch_rate("ack"),
        "CHECKPOINT_CALLS_PER_BATCH": per_batch_rate("checkpoint"),
        "IDENTITY_FETCHES": getattr(svc.monitor, "identity_fetch_count", None),
        "IDENTITY_CACHE_HITS": getattr(svc.monitor, "identity_cache_hit_count", None),
        "IDENTITY_UNRESOLVED": getattr(svc.monitor, "identity_unresolved_count", None),
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
