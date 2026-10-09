"""Oracle tests: W-20261010-A12, the start-up hook's job lines.

1. Gavin, 2026-10-10 (Q10, "Cap it at WARNING"): a ccw-sweep run that FINISHED
   with failed items is a few items for the next sweep to retry, not a job
   that cannot run. It escalates to a desktop WARNING at most and never to the
   spoken ALERT. A job that cannot run keeps the full ladder.
2. The jobs' logs moved out of ~/.claude/logs/ on 2026-10-10. The generic job
   line names the job's real log, read from `launchctl print`'s
   `stdout path =`, so it can never point at a stale folder again.
"""

import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_cc_capture_freshness_timing import (  # pyright: ignore[reportPrivateUsage]
    T0,
    _doctor,  # pyright: ignore[reportPrivateUsage]
    _drive,  # pyright: ignore[reportPrivateUsage]
    _freshness,  # pyright: ignore[reportPrivateUsage]
    scratch_home,  # noqa: F401  # pyright: ignore[reportUnusedImport] - autouse: no real HOME
)

SWEEP = "com.captaincodeau.ccw-sweep"
REPAIR = "com.captaincodeau.ccw-repair"


def _capture_log(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    """The default warehouse's capture.jsonl under the scratch HOME, where the
    hook looks when doctor's output names no root."""
    log = tmp_path / "scratch-home" / "cc-warehouse-data" / "logs" / "capture.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return log


def _finished_sweep_with_one_failed(tmp_path: Path) -> Path:
    base = {"session": None, "project": None}
    return _capture_log(
        tmp_path,
        [
            {**base, "at": (T0 - timedelta(hours=3)).isoformat(), "status": "sweep-started",
             "message": "sweep started (pid 2680)", "elapsed_ms": None},
            {**base, "at": (T0 - timedelta(hours=1)).isoformat(), "status": "error",
             "message": "sweep: 30981 items, 7 stored, 30 with sidecars, 1 failed",
             "elapsed_ms": 7_200_000},
        ],
    )


def test_a_finished_sweep_with_failed_items_never_speaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finished_sweep_with_one_failed(tmp_path)
    runs = [
        _drive(
            _freshness(), tmp_path, monkeypatch, capsys, _doctor(0),
            T0 + timedelta(minutes=m), jobs={SWEEP: 1},
        )
        for m in (0, 31, 121, 600)
    ]
    assert [len(r.desktop) for r in runs] == [0, 1, 0, 0]
    assert all(r.spoken == [] for r in runs)
    late = runs[2].stdout
    assert "cc-warehouse: WARNING - " in late and "ALERT" not in late, late


def test_a_sweep_that_cannot_run_keeps_the_full_ladder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No finished run explains the exit code, so it is a job failing."""
    runs = [
        _drive(
            _freshness(), tmp_path, monkeypatch, capsys, _doctor(0),
            T0 + timedelta(minutes=m), jobs={SWEEP: 1},
        )
        for m in (0, 31, 121)
    ]
    assert [len(r.spoken) for r in runs] == [0, 0, 1]
    assert "ALERT" in runs[2].stdout


def _launchctl_with_log(
    monkeypatch: pytest.MonkeyPatch, freshness: Any, log_dir: str, codes: dict[str, int]
) -> None:
    """launchctl print as it reads on this Mac since 2026-10-10: the job's
    exit code and the stdout path its plist names."""

    def fake(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        label = argv[-1].rsplit("/", 1)[-1]
        name = label.removeprefix("com.captaincodeau.")
        out = (
            f"\tstdout path = {log_dir}/{name}.log\n"
            f"\tstderr path = {log_dir}/{name}.log\n"
            f"\tlast exit code = {codes.get(label, 0)}\n"
        )
        return subprocess.CompletedProcess(argv, 0, out, "")

    monkeypatch.setattr(freshness.subprocess, "run", fake)


def test_the_job_line_names_the_log_launchctl_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freshness = _freshness()
    log_dir = "/srv/companion/launch-agents/logs"
    _launchctl_with_log(monkeypatch, freshness, log_dir, {REPAIR: 1})
    updates: dict[str, object] = {}
    lines = freshness._job_lines({}, T0, updates)  # pyright: ignore[reportPrivateUsage]
    (line,) = lines
    assert f"{log_dir}/ccw-repair.log" in line, line
    assert "~/.claude/logs" not in line, line


def test_a_job_whose_log_launchctl_does_not_name_never_points_at_claude_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The driver's launchctl prints only the exit code: no log path is known,
    so the line says how to find it instead of guessing a folder."""
    run = _drive(
        _freshness(), tmp_path, monkeypatch, capsys, _doctor(0), T0, jobs={REPAIR: 1}
    )
    assert "ccw-repair" in run.stdout
    assert "~/.claude/logs" not in run.stdout, run.stdout
    assert "launchctl print" in run.stdout, run.stdout
