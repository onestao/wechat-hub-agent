"""RC.14 V4 deterministic crash matrix (C1-C5).

Every case is proven by a real process death or a real connection fault, not by
inferring intent from logs:

C1 ``before_commit``
    The whole local atomic batch rolls back and the cursor does not move.
C2 ``after_commit``
    Every event of the batch is durable and the cursor sits exactly on the
    committed boundary.
C3 ``after_local_commit_before_core``
    Local state is kept, the Core checkpoint lags, a redelivery of the same
    window is absorbed by duplicate suppression, and no receipt / memory chunk
    / record / external effect is produced twice.
C4 shutdown during a batch
    The incomplete transaction rolls back, the last complete durable boundary
    is flushed, and the process exits clean.
C5 connection failure
    Fail closed on the uncertain writer, reopen and reconcile, then resume
    without double-writing.

The subprocess cases use ``agent_service.tests.crash_runner``, which drives the
real service against a local mock Core and hard-blocks ``/v1/send/text``.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from agent_service.crashpoint import CRASH_POINT_ENV, PACING_ENV
from agent_service.service import AgentService, AgentSettings
from agent_service.storage import StorageClosedError, StorageUnavailableError

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSUMER_ID = "crash-matrix"


# --------------------------------------------------------------------------
# in-process mock Core (used by the C4 and C5 unit-level cases)
# --------------------------------------------------------------------------
def status_event(index: int) -> dict[str, Any]:
    return {
        "event_id": f"evt-{index}",
        "cursor": str(index),
        "account_id": "account-a",
        "event_type": "status.created",
        "occurred_at": "2026-09-15T00:00:00Z",
        "payload": {"status": "online"},
    }


class LocalCore:
    """Minimal Core stand-in that mirrors the frozen V1 poll semantics."""

    def __init__(self, total: int):
        self.total = int(total)
        self.checkpoint = 0
        self.polls = 0
        self.acked: list[str] = []

    def ensure_contract(self, expected_major: int = 1) -> dict[str, Any]:
        return {"ok": True, "service": "local-core", "contract_version": expected_major}

    def list_accounts(self) -> list[dict[str, Any]]:
        return [
            {
                "account_id": "account-a",
                "instance_uuid": "instance-a",
                "wechat_identity_uuid": "identity-a",
                "identity_binding_state": "bound",
            }
        ]

    def poll_events(self, *, after: str = "0", limit: int = 200, consumer_id: str = "", timeout: int = 0):
        limit = max(1, min(int(limit), 200))
        self.polls += 1
        start = max(int(after or "0"), self.checkpoint) + 1
        events = [status_event(i) for i in range(start, min(start + limit, self.total + 1))]
        nxt = int(events[-1]["cursor"]) if events else max(int(after or "0"), self.checkpoint)
        return {"events": events, "next_cursor": nxt, "has_more": nxt < self.total}

    def commit_events(self, consumer_id: str, cursor: int, event_ids: list[str], *, last_event_id: str = "", **kw):
        self.checkpoint = max(self.checkpoint, int(cursor))
        self.acked.extend(event_ids)
        return {
            "consumer_id": consumer_id,
            "acked_count": len(event_ids),
            "checkpoint": {"consumer_id": consumer_id, "processed_through_cursor": self.checkpoint},
        }


class CrashMatrixUnitTests(unittest.TestCase):
    """C4 and C5 without a subprocess, so they also run on Windows."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"
        self.saved = {k: os.environ.get(k) for k in (CRASH_POINT_ENV, PACING_ENV)}

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tempdir.cleanup()

    def _service(self, total: int = 400, batch: int = 400) -> tuple[AgentService, LocalCore]:
        core = LocalCore(total)
        settings = AgentSettings(
            db_path=self.db_path,
            consumer_id=CONSUMER_ID,
            poll_interval_seconds=0.0,
            poll_batch_size=batch,
            core_commit_batch_threshold=600,
            core_commit_interval_seconds=20.0,
        )
        return AgentService(settings, core=core), core

    def test_c4_shutdown_during_batch_rolls_back_and_exits_clean(self):
        service, core = self._service()
        try:
            os.environ[PACING_ENV] = "5"
            result: dict[str, Any] = {}

            def run_batch():
                result.update(service.process_events_once())

            worker = threading.Thread(target=run_batch, name="c4-batch", daemon=True)
            worker.start()
            time.sleep(0.25)
            service.request_stop()  # exactly what the SIGTERM handler does
            worker.join(timeout=30)

            self.assertFalse(worker.is_alive(), "batch did not observe the stop request")
            self.assertEqual(result.get("error_code"), "shutdown_during_batch")
            self.assertTrue(result.get("rolled_back"))
            # Rolled back: nothing durable, cursor still on the previous boundary.
            self.assertEqual(service.storage.get_meta("core_cursor", "0"), "0")
            counts = service.storage.counts()
            self.assertEqual(counts["event_receipts"], 0)
            self.assertEqual(core.checkpoint, 0)

            # Shutdown must flush the last complete durable boundary and close.
            shutdown = service.shutdown()
            self.assertTrue(shutdown["storage"]["closed"])
            self.assertFalse(shutdown["storage"]["open_transaction_rolled_back"])

            # The events are still intact and processable after the rollback.
            os.environ.pop(PACING_ENV, None)
            service2, core2 = self._service()
            service2._stop.clear()
            res2 = service2.process_events_once()
            self.assertTrue(res2["ok"])
            self.assertEqual(res2["processed"], 400)
            self.assertEqual(res2["duplicates"], 0)
            self.assertEqual(service2.storage.get_meta("core_cursor"), "400")
            service2.shutdown()
        finally:
            try:
                service.shutdown()
            except Exception:
                pass

    def test_c5_connection_failure_fails_closed_then_recovers(self):
        service, core = self._service()
        try:
            os.environ[CRASH_POINT_ENV] = "fail_writer"
            first = service.process_events_once()

            # Fail closed: no cursor movement, no partial writes.
            self.assertFalse(first["ok"])
            self.assertEqual(service.storage.get_meta("core_cursor", "0"), "0")
            self.assertEqual(service.storage.counts()["event_receipts"], 0)
            self.assertEqual(core.checkpoint, 0)
            stats = service.storage.writer_stats()
            self.assertGreaterEqual(stats["writer_invalidations"], 1)
            self.assertGreaterEqual(stats["writer_failures"], 1)

            # Reopen + reconcile before doing anything else.
            reconciled = service.storage.reconcile()
            self.assertTrue(reconciled["ok"])
            self.assertTrue(reconciled["durability_contract_ok"])
            self.assertEqual(reconciled["journal_mode"], "wal")
            self.assertEqual(reconciled["synchronous"], 2)
            self.assertEqual(reconciled["cursor"], "0")

            # Resume on the fresh writer: exactly one copy of every event.
            second = service.process_events_once()
            self.assertTrue(second["ok"])
            self.assertEqual(second["processed"], 400)
            self.assertEqual(second["duplicates"], 0)
            self.assertEqual(service.storage.get_meta("core_cursor"), "400")
            self.assertEqual(service.storage.counts()["event_receipts"], 400)
        finally:
            service.shutdown()

    def test_storage_fails_closed_after_explicit_close(self):
        service, _ = self._service(total=10)
        service.shutdown()
        with self.assertRaises(StorageClosedError):
            service.storage.get_meta("core_cursor")
        with self.assertRaises(StorageClosedError):
            with service.storage.session():
                pass


class CrashMatrixSubprocessTests(unittest.TestCase):
    """C1-C3 plus the subprocess variants of C4/C5."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.db = self.dir / "agent.sqlite"
        self.state = self.dir / "core-state.json"
        self.out = self.dir / "evidence.json"

    def tearDown(self):
        self.tempdir.cleanup()

    # -- helpers ---------------------------------------------------------
    def _env(self, point: str = "", pacing_ms: int = 0) -> dict[str, str]:
        env = dict(os.environ)
        env.pop(CRASH_POINT_ENV, None)
        if point:
            env[CRASH_POINT_ENV] = point
        if pacing_ms:
            env[PACING_ENV] = str(pacing_ms)
        else:
            env.pop(PACING_ENV, None)
        env["PYTHONPATH"] = str(REPO_ROOT)
        return env

    def _cmd(self, *, mode: str = "once", mix: str = "status", events: int = 400,
             batch: int = 400, recover: bool = False, external: bool = False) -> list[str]:
        cmd = [
            sys.executable, "-m", "agent_service.tests.crash_runner",
            "--db", str(self.db), "--state", str(self.state), "--out", str(self.out),
            "--consumer-id", CONSUMER_ID, "--mode", mode, "--mix", mix,
            "--events", str(events), "--batch", str(batch),
        ]
        if recover:
            cmd.append("--recover-on-failure")
        if external:
            cmd.append("--external-monitor")
        return cmd

    def _run(self, *, timeout: int = 300, pacing_ms: int = 0, **kwargs) -> tuple[int, str, str]:
        point = kwargs.pop("point", "")
        proc = subprocess.Popen(
            self._cmd(**kwargs), env=self._env(point, pacing_ms),
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err

    def _db_state(self) -> dict[str, Any]:
        conn = sqlite3.connect(self.db)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT value FROM agent_meta WHERE key='core_cursor'").fetchone()
            tables = {
                "receipts": "event_receipts",
                "records": "records",
                "monitor_runs": "monitor_runs",
                "scheduler_runs": "scheduler_runs",
            }
            counts = {
                name: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for name, table in tables.items()
            }
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_memory_chunks'"
            ).fetchone()
            counts["memory_chunks"] = (
                int(conn.execute("SELECT COUNT(*) FROM event_memory_chunks").fetchone()[0]) if row else 0
            )
            counts["cursor"] = str(cursor["value"]) if cursor else "0"
            counts["integrity"] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            return counts
        finally:
            conn.close()

    def _core_state(self) -> dict[str, Any]:
        if not self.state.exists():
            return {"cursor": 0, "send_blocked": 0}
        return json.loads(self.state.read_text(encoding="utf-8"))

    def _core_cursor(self) -> int:
        return int(self._core_state().get("cursor") or 0)

    def _set_local_cursor(self, value: str) -> None:
        """Force a redelivery of an already-durable window (C3 replay step)."""
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("UPDATE agent_meta SET value=? WHERE key='core_cursor'", (value,))
            conn.commit()
        finally:
            conn.close()

    # -- C1 ---------------------------------------------------------------
    def test_c1_crash_before_commit_rolls_back_whole_batch(self):
        code, out, err = self._run(point="before_commit")
        self.assertEqual(code, 137, f"stdout={out}\nstderr={err}")
        self.assertIn("CRASH_POINT_FIRED=before_commit", err)
        state = self._db_state()
        self.assertEqual(state["receipts"], 0, "batch must roll back entirely")
        self.assertEqual(state["cursor"], "0", "cursor must not move")
        self.assertEqual(self._core_cursor(), 0)
        self.assertEqual(state["integrity"], "ok")

    # -- C2 ---------------------------------------------------------------
    def test_c2_crash_after_commit_is_fully_durable_on_boundary(self):
        code, out, err = self._run(point="after_commit")
        self.assertEqual(code, 137, f"stdout={out}\nstderr={err}")
        self.assertIn("CRASH_POINT_FIRED=after_commit", err)
        state = self._db_state()
        self.assertEqual(state["receipts"], 400, "every event of the batch is durable")
        self.assertEqual(state["cursor"], "400", "cursor must be exactly the committed boundary")
        self.assertEqual(state["integrity"], "ok")

    # -- C3 ---------------------------------------------------------------
    def test_c3_crash_after_local_commit_before_core_checkpoint(self):
        code, out, err = self._run(
            point="after_local_commit_before_core", mix="mixed", external=True
        )
        self.assertEqual(code, 137, f"stdout={out}\nstderr={err}")
        first = self._db_state()
        self.assertEqual(first["receipts"], 400)
        self.assertEqual(first["cursor"], "400")
        self.assertGreater(first["memory_chunks"], 0)
        self.assertGreater(first["monitor_runs"], 0)
        self.assertEqual(self._core_cursor(), 0, "Core checkpoint must still be behind")

        sends_after_first = int(self._core_state().get("send_blocked") or 0)
        self.assertGreater(sends_after_first, 0, "the external monitor must have fired once")

        # Redeliver the exact same window: Core's checkpoint still lags, so the
        # window is handed out again. Duplicate suppression must absorb it.
        self._set_local_cursor("0")
        code2, out2, err2 = self._run(mix="mixed", external=True)
        self.assertEqual(code2, 0, f"stdout={out2}\nstderr={err2}")
        replay = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(replay["batches"][0]["duplicates"], 400)
        self.assertEqual(replay["batches"][0]["processed"], 0)

        second = self._db_state()
        self.assertEqual(second["receipts"], first["receipts"], "no duplicate receipts")
        self.assertEqual(second["memory_chunks"], first["memory_chunks"], "no duplicate chunks")
        self.assertEqual(second["records"], first["records"], "no duplicate records")
        self.assertEqual(second["monitor_runs"], first["monitor_runs"], "no duplicate runs")
        self.assertEqual(
            int(self._core_state().get("send_blocked") or 0),
            sends_after_first,
            "no duplicate external effect",
        )
        self.assertEqual(second["cursor"], "400")
        self.assertEqual(self._core_cursor(), 400, "checkpoint advances after the replay")
        self.assertEqual(second["integrity"], "ok")

    # -- C4 (POSIX only: Windows cannot deliver a catchable SIGTERM) -------
    @unittest.skipIf(os.name == "nt", "SIGTERM is not catchable on Windows")
    def test_c4_sigterm_during_batch_exits_clean(self):
        out_path = self.dir / "serve.out"
        err_path = self.dir / "serve.err"
        # stdout/stderr go to files, not pipes: readiness has to be observed
        # while the process is still running, and a pipe would only be readable
        # after it exits.
        with out_path.open("w+", encoding="utf-8") as out_f, err_path.open("w+", encoding="utf-8") as err_f:
            proc = subprocess.Popen(
                self._cmd(mode="serve"),
                env=self._env("", pacing_ms=20), cwd=str(REPO_ROOT),
                stdout=out_f, stderr=err_f, text=True,
            )
            try:
                # Readiness barrier: the real entrypoint prints its banner
                # immediately after signal.signal(SIGTERM, ...). Any earlier
                # marker (a pre-main ready file, or an HTTP probe that has to
                # wait for the storage lock) would race that installation and
                # make this test fail with an unexplained -15.
                deadline = time.time() + 60
                while time.time() < deadline:
                    if "WeChat Agent listening" in out_path.read_text(encoding="utf-8", errors="replace"):
                        break
                    time.sleep(0.1)
                else:
                    self.fail("entrypoint never reported listening")
                time.sleep(2.0)  # inside the first paced batch (~8 s at 20 ms/event)
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=60)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=30)
        out = out_path.read_text(encoding="utf-8", errors="replace")
        err = err_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("WeChat Agent listening", out, f"stdout={out}\nstderr={err}")
        self.assertEqual(proc.returncode, 0, f"stdout={out}\nstderr={err}")

        state = self._db_state()
        self.assertEqual(state["receipts"], 0, "incomplete transaction must roll back")
        self.assertEqual(state["cursor"], "0")
        self.assertEqual(self._core_cursor(), 0)
        self.assertEqual(state["integrity"], "ok")
        # No WAL left behind: the explicit shutdown checkpointed and unlinked it.
        self.assertEqual(self._wal_bytes(), 0)

        code, out2, err2 = self._run(events=400, batch=400)
        self.assertEqual(code, 0, f"stdout={out2}\nstderr={err2}")
        final = self._db_state()
        self.assertEqual(final["receipts"], 400)
        self.assertEqual(final["cursor"], "400")

    def _wal_bytes(self) -> int:
        total = 0
        for suffix in ("-wal", "-journal"):
            path = Path(str(self.db) + suffix)
            if path.exists():
                total += path.stat().st_size
        return total

    # -- C5 ---------------------------------------------------------------
    def test_c5_connection_failure_fail_closed_then_recover(self):
        code, out, err = self._run(point="fail_writer", recover=True)
        self.assertEqual(code, 0, f"stdout={out}\nstderr={err}")
        evidence = json.loads(self.out.read_text(encoding="utf-8"))
        first = evidence["batches"][0]
        self.assertFalse(first["ok"], "the injected writer fault must fail the batch")
        self.assertIsNotNone(evidence["reconciled"])
        self.assertTrue(evidence["reconciled"]["durability_contract_ok"])
        self.assertGreaterEqual(evidence["writer_stats"]["writer_invalidations"], 1)

        state = self._db_state()
        self.assertEqual(state["receipts"], 400, "exactly one copy of every event")
        self.assertEqual(state["cursor"], "400")
        self.assertEqual(state["integrity"], "ok")
        self.assertEqual(evidence["send_blocked"], 0)


class StorageDurabilityContractTests(unittest.TestCase):
    """Direct assertions on the long-lived writer contract."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "agent.sqlite"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_single_connection_is_reused_across_sessions(self):
        from agent_service.storage import AgentStorage

        storage = AgentStorage(self.db_path)
        try:
            seen = set()
            for i in range(5):
                with storage.session() as conn:
                    seen.add(id(conn))
                    storage.set_meta("probe", str(i), conn=conn)
            self.assertEqual(len(seen), 1, "one writer connection must serve every session")
            self.assertEqual(storage.writer_stats()["writer_open_count"], 1)
            self.assertEqual(storage.writer_stats()["writer_invalidations"], 0)
            self.assertEqual(storage.get_meta("probe"), "4")
        finally:
            storage.close()

    def test_wal_and_synchronous_full_are_pinned(self):
        from agent_service.storage import AgentStorage

        storage = AgentStorage(self.db_path)
        try:
            with storage.session() as conn:
                self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(), "wal")
                self.assertEqual(int(conn.execute("PRAGMA synchronous").fetchone()[0]), 2)
        finally:
            storage.close()

    def test_nested_session_is_refused(self):
        from agent_service.storage import AgentStorage, StorageTransactionError

        storage = AgentStorage(self.db_path)
        try:
            with storage.session():
                with self.assertRaises(StorageTransactionError):
                    with storage.session():
                        pass
        finally:
            storage.close()

    def test_rollback_leaves_no_partial_write(self):
        from agent_service.storage import AgentStorage

        storage = AgentStorage(self.db_path)
        try:
            with self.assertRaises(RuntimeError):
                with storage.session() as conn:
                    conn.execute(
                        "INSERT INTO agent_meta(key, value, updated_at) VALUES ('rolled','1','now')"
                    )
                    raise RuntimeError("boom")
            self.assertEqual(storage.get_meta("rolled", "absent"), "absent")
        finally:
            storage.close()

    def test_explicit_close_checkpoints_and_unlinks_wal(self):
        from agent_service.storage import AgentStorage

        storage = AgentStorage(self.db_path)
        try:
            with storage.session() as conn:
                storage.set_meta("k", "v", conn=conn)
            info = storage.close()
            self.assertTrue(info["closed"])
            self.assertFalse(info["open_transaction_rolled_back"])
            self.assertIsNotNone(info["wal_checkpoint"])
            self.assertFalse(Path(str(self.db_path) + "-wal").exists())
        finally:
            storage.close()

    def test_fatal_error_invalidates_writer_and_raises_unavailable(self):
        from agent_service.storage import AgentStorage

        storage = AgentStorage(self.db_path)
        try:
            with self.assertRaises(StorageUnavailableError):
                with storage.session() as conn:
                    raise sqlite3.OperationalError("database disk image is malformed")
            stats = storage.writer_stats()
            self.assertEqual(stats["writer_invalidations"], 1)
            self.assertEqual(stats["writer_failures"], 1)
            # The next use reopens instead of reusing the uncertain writer.
            with storage.session() as conn:
                storage.set_meta("after", "ok", conn=conn)
            self.assertEqual(storage.get_meta("after"), "ok")
            self.assertEqual(storage.writer_stats()["writer_open_count"], 2)
        finally:
            storage.close()


if __name__ == "__main__":
    unittest.main()
