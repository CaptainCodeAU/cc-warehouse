"""Oracle tests: post-archive-write stage diagnostics in `_capture_locked` (ticket 31.4),
and the retry-with-backoff around the catalog write it deliberately left unshipped
(operator-approved follow-up, 2026-08-24 -- see Plans/majestic-floating-cray.md).

Contract: ticket 31.4 in `harness/tickets/31-sweep-full-corpus-cost.md`. The archive
JSONL write (`_archive_source`) already happened by the time either catalog call below
can raise, so `repr(exc)` alone at the top-level never-raise boundary does not say
whether the session ended up cataloged. The stage-diagnostic tests pin: which stage
failed is logged BEFORE the exception propagates, and a NON-contention exception still
propagates unchanged (no swallowing). The retry tests pin the new behavior: a
TRANSIENT "database is locked"/"database is busy" failure is retried a bounded number
of times before giving up, exactly the shape `_acquire_capture_lock` already uses one
layer up for the per-hash file lock.
"""

import sqlite3
from pathlib import Path

import pytest

from cc_warehouse import capture, catalog
from cc_warehouse.config import Config
from conftest import basic_session


def _capture_config(tmp_path: Path) -> tuple[Config, Path]:
    root = tmp_path / "wh"
    config = Config(root=root)
    source = tmp_path / "s.jsonl"
    source.write_bytes(basic_session())
    return config, source


def test_add_session_failure_is_logged_by_stage_and_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source = _capture_config(tmp_path)

    def boom(*args: object, **kwargs: object) -> str:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(catalog, "add_session", boom)

    with pytest.raises(sqlite3.OperationalError):
        capture.capture_transcript(config, source, session_id="s1", cwd="/home/a")

    log = (config.root / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    assert "add_session" in log
    assert "OperationalError" in log
    assert "database is locked" in log


def test_record_event_failure_is_logged_by_stage_and_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, source = _capture_config(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(catalog, "record_event", boom)

    with pytest.raises(sqlite3.OperationalError):
        capture.capture_transcript(config, source, session_id="s1", cwd="/home/a")

    log = (config.root / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    assert "record_event" in log
    assert "OperationalError" in log

    # The row from add_session is NOT rolled back by record_event's failure (they are
    # separate transactions, catalog.py's writing()) -- the session IS cataloged even
    # though the "stored" capture_event that would confirm it never got written. This is
    # exactly the gap ticket 31.4 exists to make diagnosable, not to close.
    conn = sqlite3.connect(config.root / "catalog.sqlite")
    try:
        count = conn.execute("SELECT count(*) FROM session").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_transient_lock_contention_on_add_session_is_retried_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A "database is locked" failure is transient under real concurrent captures
    (many sessions, one shared catalog.sqlite) -- unlike a real bug, retrying it a
    bounded number of times is the correct, safe response (R14: SQLite's own
    reserved lock, via BEGIN IMMEDIATE, is already the coordination primitive; the
    gap was giving up after exactly one 5s busy_timeout wait)."""
    config, source = _capture_config(tmp_path)
    real_add_session = catalog.add_session
    calls: list[int] = []

    def flaky(*args: object, **kwargs: object) -> str:
        calls.append(1)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")
        return real_add_session(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(catalog, "add_session", flaky)

    result = capture.capture_transcript(config, source, session_id="s1", cwd="/home/a")

    assert result.action == "stored"
    assert len(calls) == 3
    # No stage-failure line for a retry that ultimately succeeded -- only a genuine,
    # unrecovered failure is diagnostic-worthy (F6 protects LOSS, not a recovered retry).
    log_path = config.root / "logs" / "capture.jsonl"
    assert not log_path.exists() or "add_session" not in log_path.read_text(encoding="utf-8")


def test_lock_contention_retries_are_bounded_then_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5: refuse rather than wait forever. A holder that never releases (or a
    genuinely saturated catalog) must still surface a real failure, not hang or
    silently pretend to succeed."""
    config, source = _capture_config(tmp_path)
    calls: list[int] = []

    def always_locked(*args: object, **kwargs: object) -> str:
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(catalog, "add_session", always_locked)

    with pytest.raises(sqlite3.OperationalError):
        capture.capture_transcript(config, source, session_id="s1", cwd="/home/a")

    assert len(calls) == capture.CATALOG_RETRY_ATTEMPTS
    log = (config.root / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    assert "add_session" in log


def test_a_non_contention_exception_is_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retrying is licensed ONLY for the transient lock-contention shape. A real bug
    (a schema error, a programming mistake) must fail immediately and loudly, exactly
    as before -- masking it behind several silent retries would be worse, not safer."""
    config, source = _capture_config(tmp_path)
    calls: list[int] = []

    def broken(*args: object, **kwargs: object) -> str:
        calls.append(1)
        raise ValueError("not a lock contention case")

    monkeypatch.setattr(catalog, "add_session", broken)

    with pytest.raises(ValueError):
        capture.capture_transcript(config, source, session_id="s1", cwd="/home/a")

    assert len(calls) == 1
