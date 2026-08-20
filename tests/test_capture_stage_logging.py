"""Oracle tests: post-archive-write stage diagnostics in `_capture_locked` (ticket 31.4).

Contract: ticket 31.4 in `harness/tickets/31-sweep-full-corpus-cost.md`. The archive
JSONL write (`_archive_source`) already happened by the time either catalog call below
can raise, so `repr(exc)` alone at the top-level never-raise boundary does not say
whether the session ended up cataloged. This pins two things: which stage failed is
logged BEFORE the exception propagates, and the exception still propagates unchanged
(no swallowing, no retry -- 31.4 ships logging only, not a fix for an unconfirmed cause).
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
