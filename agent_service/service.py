from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core_client import CoreApiError, CoreClient
from .legacy_ai import LegacyAIAdapter
from .memory_index import EventMemoryIndex
from .monitor import MonitorEngine
from .scheduler import SchedulerEngine
from .storage import AgentStorage, utc_now_iso


ROOT = Path(__file__).resolve().parents[1]


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class AgentSettings:
    core_url: str = "http://127.0.0.1:8080"
    db_path: Path = ROOT / "runtime" / "agent-service" / "agent.sqlite"
    consumer_id: str = "wechat-agent"
    poll_interval_seconds: float = 2.0
    poll_timeout_seconds: int = 0
    poll_batch_size: int = 100
    scheduler_interval_seconds: float = 5.0
    vector_dim: int = 384

    @classmethod
    def from_env(cls) -> "AgentSettings":
        return cls(
            core_url=os.environ.get("WECHAT_CORE_URL", "http://127.0.0.1:8080"),
            db_path=Path(
                os.environ.get(
                    "WECHAT_AGENT_DB",
                    str(ROOT / "runtime" / "agent-service" / "agent.sqlite"),
                )
            ),
            consumer_id=os.environ.get("WECHAT_AGENT_CONSUMER_ID", "wechat-agent"),
            poll_interval_seconds=env_float("WECHAT_AGENT_POLL_INTERVAL", 2.0, 0.25, 300.0),
            poll_timeout_seconds=env_int("WECHAT_AGENT_POLL_TIMEOUT", 0, 0, 30),
            poll_batch_size=env_int("WECHAT_AGENT_POLL_BATCH", 100, 1, 200),
            scheduler_interval_seconds=env_float("WECHAT_AGENT_SCHEDULER_INTERVAL", 5.0, 0.5, 300.0),
            vector_dim=env_int("WECHAT_AGENT_VECTOR_DIM", 384, 64, 4096),
        )


class AgentService:
    def __init__(
        self,
        settings: AgentSettings | None = None,
        *,
        core: CoreClient | None = None,
        ai: Any | None = None,
    ):
        self.settings = settings or AgentSettings.from_env()
        self.storage = AgentStorage(self.settings.db_path)
        self.core = core or CoreClient(self.settings.core_url)
        self.ai = ai or LegacyAIAdapter()
        self.memory = EventMemoryIndex(self.storage, self.settings.vector_dim)
        self.monitor = MonitorEngine(self.storage, self.core, self.memory, self.ai)
        self.scheduler = SchedulerEngine(self.storage, self.core, self.memory, self.ai)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._poll_lock = threading.Lock()
        self._scheduler_lock = threading.Lock()
        self._last_poll: dict[str, Any] = {}
        self._last_scheduler: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        core_status: dict[str, Any]
        try:
            health = self.core.ensure_contract(1)
            core_status = {"ok": True, "health": health}
        except Exception as exc:
            core_status = {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "service": "wechat-agent",
            "contract_version": 1,
            "time": utc_now_iso(),
            "core": core_status,
            "consumer_id": self.settings.consumer_id,
            "cursor": self.storage.get_meta("core_cursor", "0"),
            "memory_chunks": self.memory.count(),
            "counts": self.storage.counts(),
            "workers": {
                "running": any(thread.is_alive() for thread in self._threads),
                "last_poll": self._last_poll,
                "last_scheduler": self._last_scheduler,
            },
        }

    def _partition_events(
        self,
        events: list[dict[str, Any]],
        monitors: list[dict[str, Any]],
    ) -> list[tuple[bool, list[dict[str, Any]]]]:
        segments: list[tuple[bool, list[dict[str, Any]]]] = []
        for raw_event in events:
            event = raw_event if isinstance(raw_event, dict) else {}
            if self.monitor.event_has_external_side_effect(event, monitors=monitors):
                segments.append((False, [event]))
            else:
                if segments and segments[-1][0]:
                    segments[-1][1].append(event)
                else:
                    segments.append((True, [event]))
        return segments

    def _process_single_event(
        self,
        event: dict[str, Any],
        last_cursor: str,
        identity_view: dict[str, dict[str, Any]] | None,
        monitors: list[dict[str, Any]],
        conn: sqlite3.Connection | None = None,
    ) -> tuple[bool, str, dict[str, Any], list[dict[str, Any]], str]:
        event_id = str(event.get("event_id") or "")
        event_cursor = str(event.get("cursor") or last_cursor)
        if not event_id:
            raise RuntimeError("Core returned event without event_id")
        if self.storage.event_seen(event_id, conn=conn):
            self.storage.set_meta("core_cursor", event_cursor, conn=conn)
            return True, event_cursor, {}, [], event_id
        message = None
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("event_type") in {"message.created", "message.updated"}:
            candidate = payload.get("message")
            if isinstance(candidate, dict):
                message = candidate
        memory_result: dict[str, Any] = {}
        if message is not None:
            memory_result = self.memory.ingest_message(event, message, conn=conn)
        action_runs = self.monitor.process_event(
            event,
            identity_view=identity_view,
            monitors=monitors,
            conn=conn,
        )
        self.storage.store_event(event, conn=conn)
        self.storage.set_meta("core_cursor", event_cursor, conn=conn)
        return False, event_cursor, memory_result, action_runs, event_id

    def process_events_once(self) -> dict[str, Any]:
        if not self._poll_lock.acquire(blocking=False):
            return {"ok": False, "busy": True, "error": "event poll already running"}
        started = time.monotonic()
        try:
            health = self.core.ensure_contract(1)
            cursor = self.storage.get_meta("core_cursor", "0") or "0"
            page = self.core.poll_events(
                after=cursor,
                limit=self.settings.poll_batch_size,
                consumer_id=self.settings.consumer_id,
                timeout=self.settings.poll_timeout_seconds,
            )
            events = list(page.get("events") or [])
            processed = 0
            duplicates = 0
            indexed = 0
            monitor_runs = 0
            ack_ids: list[str] = []
            last_cursor = cursor
            details: list[dict[str, Any]] = []

            enabled_monitors = self.storage.list_monitors(enabled_only=True)
            identity_view = self.monitor.identity_view() if events else None
            segments = self._partition_events(events, enabled_monitors)
            next_cursor = str(page.get("next_cursor") or "")

            for seg_idx, (is_local, seg_events) in enumerate(segments):
                is_last = (seg_idx == len(segments) - 1)
                if is_local:
                    with self.storage.session() as session:
                        for evt in seg_events:
                            is_dup, cur, mem, acts, eid = self._process_single_event(
                                evt, last_cursor, identity_view, enabled_monitors, conn=session
                            )
                            last_cursor = cur
                            ack_ids.append(eid)
                            if is_dup:
                                duplicates += 1
                            else:
                                processed += 1
                                if mem.get("changed"):
                                    indexed += 1
                                monitor_runs += len(acts)
                                details.append(
                                    {
                                        "event_id": eid,
                                        "event_type": evt.get("event_type"),
                                        "memory": mem,
                                        "monitor_runs": acts,
                                    }
                                )
                        if is_last and next_cursor:
                            self.storage.set_meta("core_cursor", next_cursor, conn=session)
                            last_cursor = next_cursor
                else:
                    evt = seg_events[0]
                    is_dup, cur, mem, acts, eid = self._process_single_event(
                        evt, last_cursor, identity_view, enabled_monitors, conn=None
                    )
                    last_cursor = cur
                    ack_ids.append(eid)
                    if is_dup:
                        duplicates += 1
                    else:
                        processed += 1
                        if mem.get("changed"):
                            indexed += 1
                        monitor_runs += len(acts)
                        details.append(
                            {
                                "event_id": eid,
                                "event_type": evt.get("event_type"),
                                "memory": mem,
                                "monitor_runs": acts,
                            }
                        )
                    if is_last and next_cursor:
                        self.storage.set_meta("core_cursor", next_cursor)
                        last_cursor = next_cursor

            ack = self.core.ack_events(self.settings.consumer_id, ack_ids) if ack_ids else {
                "consumer_id": self.settings.consumer_id,
                "acked_event_ids": [],
                "acked_count": 0,
            }
            has_more = bool(page.get("has_more"))
            checkpoint_cursor = int(last_cursor)
            checkpoint_res = {}
            try:
                last_id = ack_ids[-1] if ack_ids else ""
                checkpoint_res = self.core.checkpoint_events(
                    self.settings.consumer_id,
                    checkpoint_cursor,
                    last_event_id=last_id,
                )
            except Exception:
                pass
            result = {
                "ok": True,
                "core_health": health,
                "from_cursor": cursor,
                "cursor": last_cursor,
                "events": len(events),
                "processed": processed,
                "duplicates": duplicates,
                "indexed_messages": indexed,
                "monitor_runs": monitor_runs,
                "ack": ack,
                "checkpoint": checkpoint_res,
                "has_more": has_more,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "details": details,
            }
            self._last_poll = result
            return result
        except Exception as exc:
            result = {
                "ok": False,
                "error": str(exc),
                "error_code": exc.code if isinstance(exc, CoreApiError) else "agent_poll_failed",
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            }
            self._last_poll = result
            return result
        finally:
            self._poll_lock.release()

    def run_scheduler_once(self) -> dict[str, Any]:
        if not self._scheduler_lock.acquire(blocking=False):
            return {"ok": False, "busy": True, "error": "scheduler already running"}
        started = time.monotonic()
        try:
            runs = self.scheduler.run_due()
            result = {
                "ok": True,
                "runs": runs,
                "run_count": len(runs),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            }
            self._last_scheduler = result
            return result
        except Exception as exc:
            result = {
                "ok": False,
                "error": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            }
            self._last_scheduler = result
            return result
        finally:
            self._scheduler_lock.release()

    def run_once(self) -> dict[str, Any]:
        return {"poll": self.process_events_once(), "scheduler": self.run_scheduler_once()}

    def start_workers(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        poll_thread = threading.Thread(target=self._poll_loop, name="wechat-agent-core-poll", daemon=True)
        scheduler_thread = threading.Thread(
            target=self._scheduler_loop, name="wechat-agent-scheduler", daemon=True
        )
        self._threads = [poll_thread, scheduler_thread]
        for thread in self._threads:
            thread.start()

    def stop_workers(self) -> None:
        self._stop.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        self._threads = []

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            result = self.process_events_once()
            delay = self.settings.poll_interval_seconds
            if not result.get("ok"):
                delay = max(delay, 2.0)
            self._stop.wait(delay)

    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            self.run_scheduler_once()
            self._stop.wait(self.settings.scheduler_interval_seconds)

