"""Oracle tests: doctor reports a `ccw sweep` that started and never finished (W-20260930-A28).

THE HOLE. A sweep writes its run summary to capture.jsonl only as it ends
(ticket 42 #2). A sweep killed mid-run wrote nothing at all, so its absence was
indistinguishable from "no sweep was due". Live 2026-09-29: the 12:30 sweep
logged items until 12:49 AEST and never wrote its summary; its launchd job was
reloaded at 13:57, inside its expected 2 to 2.5 hour run on the share. Doctor
noticed only through the `overdue` count, days later, and could not say why.

THE RULE. `ccw sweep` writes a `sweep started (pid N)` line (status
`sweep-started`) before it runs. Doctor's `sweep` line pairs the newest start
with any later `sweep: ` run summary (a completed run, a failed one, or a lock
refusal all count as the invocation ending). A start with nothing after it,
older than a short grace, whose process is gone and while no process holds the
sweep lock, is a sweep that died. The pid matters because the sweep lock is
released before the sweep-triggered build and the coverage scan, so a live
sweep spends its tail holding no sweep lock at all.

NEVER BLOCKING, the same posture as `companions` (ticket 38 ruling (e)): the
next sweep redoes the work, and `overdue` already FAILs when sessions stay
uncaptured. This line says WHY, beside it. A running sweep (its process alive
or the lock held) and a start inside the grace are fine; a log with no start
line at all (every sweep before this change) is fine.

Contract: R5, F6, F7.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cc_warehouse import doctor
from cc_warehouse.config import Config, load_config
from conftest import lock_held_elsewhere, mark_archive, warehouse_root

ZONE = "UTC"


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


def _at(seconds_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def _record(config: Config, seconds_ago: float, status: str, message: str) -> None:
    path = config.root / "logs" / "capture.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "at": _at(seconds_ago),
        "status": status,
        "session": None,
        "project": None,
        "message": message,
        "elapsed_ms": None,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def _started(config: Config, seconds_ago: float) -> None:
    _record(config, seconds_ago, "sweep-started", "sweep started")


def _finished(config: Config, seconds_ago: float) -> None:
    _record(config, seconds_ago, "ok", "sweep: 29944 items, 38 stored, 0 failed")


def _check(config: Config, home: Path) -> doctor.Check:
    report = doctor.diagnose(config, home=home)
    found = [check for check in report.checks if check.name == "sweep"]
    assert len(found) == 1, [check.name for check in report.checks]
    return found[0]


def test_a_sweep_that_started_and_never_finished_is_reported(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _finished(config, seconds_ago=2 * 86400)
    _started(config, seconds_ago=3600)

    check = _check(config, Path(ccw_env["HOME"]))

    assert not check.ok, check.detail
    assert "never finished" in check.detail
    assert check.blocking is False, "the next sweep redoes the work; overdue owns the FAIL"


def test_the_report_names_when_the_dead_sweep_started(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, seconds_ago=3600)
    log = (config.root / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    started_at = str(json.loads(log.splitlines()[-1])["at"])

    check = _check(config, Path(ccw_env["HOME"]))

    assert started_at[:16] in check.detail, check.detail


def test_a_dead_sweep_does_not_move_doctors_exit_code(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    home = Path(ccw_env["HOME"])
    before = doctor.diagnose(config, home=home).ok
    _started(config, seconds_ago=3600)

    assert doctor.diagnose(config, home=home).ok == before


def test_a_sweep_that_finished_after_its_start_is_fine(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, seconds_ago=3600)
    _finished(config, seconds_ago=600)

    check = _check(config, Path(ccw_env["HOME"]))

    assert check.ok, check.detail


def test_a_lock_refusal_after_the_start_ends_that_invocation(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, seconds_ago=3600)
    _record(config, 3599, "error", "sweep: refused: lock held by a live holder")

    check = _check(config, Path(ccw_env["HOME"]))

    assert check.ok, check.detail


def test_an_older_finish_does_not_cover_a_newer_start(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, seconds_ago=90000)
    _finished(config, seconds_ago=86400)
    _started(config, seconds_ago=3600)

    check = _check(config, Path(ccw_env["HOME"]))

    assert not check.ok, check.detail


def test_a_sweep_still_holding_its_lock_is_running_not_dead(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, seconds_ago=3600)

    with lock_held_elsewhere(config.root, "sweep"):
        check = _check(config, Path(ccw_env["HOME"]))

    assert check.ok, check.detail
    assert "running" in check.detail


def test_a_sweep_whose_process_is_alive_is_running_even_with_no_lock(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The sweep lock is released BEFORE the sweep-triggered build and the coverage
    scan, and the run summary is written only after both, so on the share a live
    sweep spends a long tail holding no sweep lock. Its own pid answers for it."""
    config = _configure(ccw_env, tmp_path / "archive")
    _record(config, 3600, "sweep-started", f"sweep started (pid {os.getpid()})")

    check = _check(config, Path(ccw_env["HOME"]))

    assert check.ok, check.detail
    assert "running" in check.detail


def test_a_sweep_whose_process_is_gone_is_reported(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    _record(config, 3600, "sweep-started", f"sweep started (pid {gone.pid})")

    check = _check(config, Path(ccw_env["HOME"]))

    assert not check.ok, check.detail
    assert "never finished" in check.detail


def test_a_start_inside_the_grace_is_not_yet_reported(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`ccw sweep` writes its start line just BEFORE it takes the lock, so a doctor
    landing in that gap must not read a healthy sweep as a dead one."""
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, seconds_ago=5)

    check = _check(config, Path(ccw_env["HOME"]))

    assert check.ok, check.detail


def test_a_log_with_no_start_line_is_fine(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Every sweep before W-20260930-A28 wrote no start line; that history is not a fault."""
    config = _configure(ccw_env, tmp_path / "archive")
    _finished(config, seconds_ago=3600)

    check = _check(config, Path(ccw_env["HOME"]))

    assert check.ok, check.detail
