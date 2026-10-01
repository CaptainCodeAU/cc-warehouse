"""Oracle tests: doctor reports a SessionEnd hook that started and never finished (W-20260929-A105).

THE HOLE. A SessionEnd hook killed mid-capture leaves a `started` line in
`~/.claude/logs/ccw-hook.log` with nothing after it, a half-written
`.<uuid>.jsonl.<random>.tmp` in the session's archive folder (the tmp half of
`store.atomic_write`), a dead capture lock, and NO catalog row. Doctor's checks
ask the catalog, so it stayed green while the session existed only in
`~/.claude`. Live 2026-09-29: f952df5f and fc69613b, 3.2 and 4.0 MB `.tmp` files on
the share; 11 of 775 hook runs since 2026-09-06 started and never finished.

THE RULE (Gavin, 2026-09-29, option 1). Doctor reads the hook log (bounded to
the same 7-day window as its dispatch check) and pairs each `started` with a later
line for the same session. A run older than the hook's own timeout that never
finished, with no catalog row for its session, is a WARNING at once (the next
`ccw sweep` is expected to re-capture it from `~/.claude`), and turns BLOCKING
only once a sweep has COMPLETED after the run started and the session still has
no row: then the net that was meant to catch it has missed. A run since captured
is clean. Stray `.tmp` files in those runs' folders are named and left in place.

A hook killed BEFORE it wrote `started` leaves nothing here to find; the
`dispatch` line's own caveat covers what can and cannot be seen of that.

Contract: R5, F6, F7.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cc_warehouse import build, capture, catalog, doctor
from cc_warehouse.config import Config, load_config
from conftest import basic_session, mark_archive, warehouse_root, write_transcript

ZONE = "UTC"
CWD = "/home/alice/projects/widget"
SIBLING = "0a105000-0000-4000-8000-000000000001"
DEAD = "0a105000-0000-4000-8000-000000000002"


def _configure(env: dict[str, str], archive_root: Path) -> Config:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\narchive_root = "{archive_root}"\n'
        f'archive_timezone = "{ZONE}"\n',
        encoding="utf-8",
    )
    mark_archive(archive_root, ZONE)
    return load_config()


def _log(home: Path, *records: dict[str, object]) -> None:
    path = home / ".claude" / "logs" / "ccw-hook.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps({"source": "ccw-hook", **record}) + "\n")


def _at(seconds_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")


def _world(ccw_env: dict[str, str], tmp_path: Path) -> tuple[Config, Path, Path, Path]:
    """A captured sibling (so the project is registered), and a dead run for DEAD:
    its transcript in ~/.claude, its archive folder holding only a stray .tmp."""
    home = Path(ccw_env["HOME"])
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    sibling = write_transcript(
        ccw_env, basic_session(cwd=CWD, session_id=SIBLING), session_id=SIBLING
    )
    stored = capture.capture_transcript(config, sibling, session_id=SIBLING, cwd=CWD)
    assert stored.action == "stored"
    dead = write_transcript(ccw_env, basic_session(cwd=CWD, session_id=DEAD), session_id=DEAD)
    conn = catalog.open_catalog(config.root)
    try:
        label = str(conn.execute("SELECT label FROM project").fetchone()[0])
    finally:
        conn.close()
    folder = build.archive_dir(
        archive_root, label, "2026-01-05T10:00:00.000Z", DEAD, ZONE,
        fallback_stem="session",
    )
    folder.mkdir(parents=True)
    tmp = folder / f".{DEAD}.jsonl.ab12cd34.tmp"
    tmp.write_bytes(b"half a payload")
    return config, home, dead, tmp


def _sweep_completed(config: Config, seconds_ago: float) -> None:
    """The run-summary line `ccw sweep` writes to capture.jsonl when it finishes."""
    path = config.root / "logs" / "capture.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": _at(seconds_ago),
        "status": "ok",
        "session": None,
        "project": None,
        "message": "sweep: 29944 items, 38 stored, 0 failed",
        "elapsed_ms": None,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _started(home: Path, transcript: Path, seconds_ago: float, session: str = DEAD) -> None:
    _log(
        home,
        {"ts": _at(seconds_ago), "session": None, "status": "dispatched", "detail": ""},
        {
            "ts": _at(seconds_ago),
            "session": session,
            "status": "started",
            "detail": str(transcript),
        },
    )


def _check(config: Config, home: Path) -> doctor.Check:
    report = doctor.diagnose(config, home=home)
    found = [check for check in report.checks if check.name == "hook runs"]
    assert len(found) == 1, [check.name for check in report.checks]
    return found[0]


def test_a_dead_hook_with_no_sweep_since_is_a_warning_that_names_the_tmp(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, home, dead, tmp = _world(ccw_env, tmp_path)
    _sweep_completed(config, seconds_ago=3600)  # BEFORE the run: does not count
    _started(home, dead, seconds_ago=600)

    check = _check(config, home)

    assert not check.ok and not check.blocking
    assert DEAD[:8] in check.detail and "never finished" in check.detail
    assert tmp.name in check.detail
    assert tmp.read_bytes() == b"half a payload", "doctor must leave the stray .tmp in place"


def test_a_dead_hook_still_uncaptured_after_a_completed_sweep_fails_doctor(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, home, dead, tmp = _world(ccw_env, tmp_path)
    _started(home, dead, seconds_ago=600)
    _sweep_completed(config, seconds_ago=60)

    check = _check(config, home)

    assert not check.ok and check.blocking
    assert DEAD[:8] in check.detail and "sweep" in check.detail
    assert tmp.name in check.detail
    assert not doctor.diagnose(config, home=home).ok


def test_a_refused_sweep_is_not_a_completed_one(ccw_env: dict[str, str], tmp_path: Path) -> None:
    config, home, dead, _tmp = _world(ccw_env, tmp_path)
    _started(home, dead, seconds_ago=600)
    path = config.root / "logs" / "capture.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    refused = {
        "at": _at(60),
        "status": "error",
        "session": None,
        "project": None,
        "message": "sweep: refused: lock held by a live holder",
        "elapsed_ms": None,
    }
    path.write_text(json.dumps(refused) + "\n", encoding="utf-8")

    check = _check(config, home)

    assert not check.ok and not check.blocking


@pytest.mark.parametrize(
    "case",
    ["finished", "finished-with-error", "still-running", "older-than-window", "captured-since"],
)
def test_runs_that_are_not_lost_do_not_fail(
    ccw_env: dict[str, str], tmp_path: Path, case: str
) -> None:
    config, home, dead, tmp = _world(ccw_env, tmp_path)
    if case == "finished":
        _started(home, dead, seconds_ago=600)
        _log(home, {"ts": _at(599), "session": DEAD, "status": "ok", "detail": "ok: captured"})
    elif case == "finished-with-error":
        _started(home, dead, seconds_ago=600)
        _log(home, {"ts": _at(599), "session": DEAD, "status": "capture-error", "detail": "x"})
    elif case == "still-running":
        _started(home, dead, seconds_ago=5)
    elif case == "older-than-window":
        _started(home, dead, seconds_ago=8 * 24 * 3600)
    else:
        _started(home, dead, seconds_ago=600)
        assert capture.capture_transcript(config, dead, session_id=DEAD, cwd=CWD).action == "stored"
        _sweep_completed(config, seconds_ago=60)

    check = _check(config, home)

    assert check.ok, check.detail
    if case == "captured-since":
        # Captured now, but the half-written file is still there: named, not failed.
        assert "never finished" in check.detail and tmp.name in check.detail


def test_no_hook_log_is_not_a_failure(ccw_env: dict[str, str], tmp_path: Path) -> None:
    config, home, _dead, _tmp = _world(ccw_env, tmp_path)
    check = _check(config, home)
    assert check.ok and "no ccw-hook.log" in check.detail
