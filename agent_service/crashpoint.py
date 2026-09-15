"""Deterministic crash-point injection for durability qualification.

The RC.14 V4 crash matrix (C1-C5) needs the process to die at exact,
reproducible points inside a local atomic batch, and it needs that to be
provable rather than inferred from logs. This module provides the hook.

Production is unaffected by construction:

* injection is inert unless ``WECHAT_AGENT_CRASH_POINT`` names the point,
* the env var is cleared as soon as a point fires (one-shot per process),
* ``os._exit`` is used so that no ``finally``/``atexit``/interpreter-teardown
  path can commit, checkpoint or close anything -- the process disappears
  exactly the way a SIGKILL or a power cut makes it disappear.

Points
------
``before_commit``
    Die between the last write of the local atomic batch and ``COMMIT``.
    Expected: the whole batch rolls back, the cursor does not move (C1).
``after_commit``
    Die the instant ``COMMIT`` returns. Expected: every event of the batch is
    durable and the cursor sits exactly on the committed boundary (C2).
``after_local_commit_before_core``
    Die after the local transaction is durable but before the Core checkpoint
    is issued. Expected: local state kept, Core checkpoint lagging, replay
    suppressed as duplicates (C3).
``shutdown_during_batch``
    Request a graceful stop from inside the batch. Expected: the incomplete
    transaction rolls back, the last complete durable boundary is flushed and
    the process exits clean (C4).
``fail_writer``
    Simulate a writer connection that has become invalid. Expected: fail
    closed, reopen and reconcile, never keep using an uncertain writer (C5).
``slow_batch``
    Not a crash: pace the batch so an externally delivered signal can land
    mid-transaction deterministically. Pair with ``WECHAT_AGENT_TEST_PACING_MS``.
"""
from __future__ import annotations

import os
import sqlite3
import sys

CRASH_POINT_ENV = "WECHAT_AGENT_CRASH_POINT"
PACING_ENV = "WECHAT_AGENT_TEST_PACING_MS"
DEFAULT_EXIT_CODE = 137

POINTS = (
    "before_commit",
    "after_commit",
    "after_local_commit_before_core",
    "shutdown_during_batch",
    "fail_writer",
    "slow_batch",
)


def armed_point() -> str:
    """Name of the currently armed crash point, or ``""``."""
    return str(os.environ.get(CRASH_POINT_ENV) or "").strip()


def is_armed(name: str) -> bool:
    return armed_point() == name


def crash_point(name: str, *, exit_code: int = DEFAULT_EXIT_CODE) -> bool:
    """Terminate the process if ``name`` is the armed crash point.

    Returns ``False`` when the point is not armed, so call sites can be a
    single statement. Returns nothing else: an armed point never returns.
    """
    if not is_armed(name):
        return False
    os.environ[CRASH_POINT_ENV] = ""  # one-shot: never fire twice
    try:
        sys.stderr.write(f"CRASH_POINT_FIRED={name} exit_code={exit_code}\n")
        sys.stderr.flush()
        sys.stdout.flush()
    except Exception:  # pragma: no cover - best effort evidence
        pass
    os._exit(exit_code)
    raise AssertionError("unreachable")  # pragma: no cover


def raise_fault(name: str, message: str = "injected fault") -> None:
    """Raise an injected fault if ``name`` is armed (one-shot).

    Unlike :func:`crash_point` the process survives, so this models a
    *recoverable* failure such as an invalidated SQLite connection. The raised
    type/message are deliberately indistinguishable from a genuine SQLite I/O
    failure so that the caller's real error classification is exercised.
    """
    if not is_armed(name):
        return
    os.environ[CRASH_POINT_ENV] = ""  # one-shot
    raise sqlite3.OperationalError(message)


def pacing_delay_seconds() -> float:
    """Per-event delay used by the real-signal variant of C4.

    Purely a test knob: it is inert (0.0) unless ``WECHAT_AGENT_TEST_PACING_MS``
    is set, so production batches are never slowed down.
    """
    try:
        return max(0.0, float(os.environ.get(PACING_ENV, "0")) / 1000.0)
    except (TypeError, ValueError):
        return 0.0
