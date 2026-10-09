"""Oracle tests: doctor reports a `ccw repair` or `ccw archive` run that started
and never finished (review of 71d5aec, 2026-10-10; Gavin: "Yes, now").

Since W-20261010-A12 both jobs write `<verb> started (pid N)` (status
`<verb>-started`) before their work and a run summary after: `repair-summary`
for repair, an `archive: ` message for archive, including refusals and
crashes. A start with nothing after it, past the grace, whose process is gone
and whose lock is free, is a run that was killed. Same rule and the same
never-blocking posture as the `sweep` line (tests/test_doctor_unfinished_sweep.py):
the next scheduled run redoes the work, so this line says WHY and never moves
doctor's exit code.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cc_warehouse import doctor
from cc_warehouse.config import Config, load_config
from conftest import mark_archive, warehouse_root

ZONE = "UTC"
JOBS = ["repair", "archive"]


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


def _record(config: Config, seconds_ago: float, status: str, message: str) -> None:
    path = config.root / "logs" / "capture.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "at": (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat(),
        "status": status,
        "session": None,
        "project": None,
        "message": message,
        "elapsed_ms": None,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def _dead_pid() -> int:
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    return gone.pid


def _started(config: Config, verb: str, seconds_ago: float, pid: int) -> None:
    _record(config, seconds_ago, f"{verb}-started", f"{verb} started (pid {pid})")


def _finished(config: Config, verb: str, seconds_ago: float) -> None:
    if verb == "repair":
        _record(config, seconds_ago, "repair-summary",
                "repair: 25 checked, 0 fixed, 0 still broken, 0 held, 0 pending; "
                "0 open refusal(s)")
    else:
        _record(config, seconds_ago, "ok", "archive: 3 folders written, 0 failed")


def _check(config: Config, home: Path, verb: str) -> doctor.Check:
    found = [c for c in doctor.diagnose(config, home=home).checks if c.name == verb]
    assert len(found) == 1, [c.name for c in doctor.diagnose(config, home=home).checks]
    return found[0]


@pytest.mark.parametrize("verb", JOBS)
def test_a_run_that_started_and_never_finished_is_reported(
    verb: str, ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _finished(config, verb, seconds_ago=2 * 86400)
    _started(config, verb, seconds_ago=3600, pid=_dead_pid())

    check = _check(config, Path(ccw_env["HOME"]), verb)

    assert not check.ok, check.detail
    assert "never finished" in check.detail, check.detail
    assert check.blocking is False


@pytest.mark.parametrize("verb", JOBS)
def test_a_dead_run_does_not_move_doctors_exit_code(
    verb: str, ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    home = Path(ccw_env["HOME"])
    before = doctor.diagnose(config, home=home).ok
    _started(config, verb, seconds_ago=3600, pid=_dead_pid())

    assert doctor.diagnose(config, home=home).ok == before


@pytest.mark.parametrize("verb", JOBS)
def test_a_run_that_finished_after_its_start_is_fine(
    verb: str, ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, verb, seconds_ago=3600, pid=_dead_pid())
    _finished(config, verb, seconds_ago=600)

    assert _check(config, Path(ccw_env["HOME"]), verb).ok


@pytest.mark.parametrize("verb", JOBS)
def test_a_run_whose_process_is_alive_is_running(
    verb: str, ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, verb, seconds_ago=3600, pid=os.getpid())

    check = _check(config, Path(ccw_env["HOME"]), verb)

    assert check.ok and "running" in check.detail, check.detail


@pytest.mark.parametrize("verb", JOBS)
def test_a_log_with_no_start_line_is_fine(
    verb: str, ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, tmp_path / "archive")

    assert _check(config, Path(ccw_env["HOME"]), verb).ok


def test_a_sweep_summary_does_not_close_a_repair_start(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Each job pairs only its own lines."""
    config = _configure(ccw_env, tmp_path / "archive")
    _started(config, "repair", seconds_ago=3600, pid=_dead_pid())
    _record(config, 600, "ok", "sweep: 10 items, 0 stored, 0 failed")

    assert not _check(config, Path(ccw_env["HOME"]), "repair").ok
