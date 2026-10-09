"""Oracle tests: W-20261010-A02, the job alert tells a finished sweep with a few
failed items apart from a job that cannot run.

2026-10-09: the session-start alert read "ALERT - scheduled job
com.captaincodeau.ccw-sweep has been failing for 4 h 11 min (exit 1). Check its
log under ~/.claude/logs/ now." The run had finished at 11:52 AM with
"30981 items, 7 stored, 30 with sidecars, 1 failed", and the log it pointed at
stacks runs with no timestamps, so its tail (a 2 Oct outage) was misread as
that day's failure. When the sweep's newest run summary in capture.jsonl closes
its newest start and names failed items, the alert now says so, with the count
and capture.jsonl as the place to look. Since W-20261010-A12 (Gavin, 2026-10-10,
Q10) such a run is capped at WARNING: it is never spoken.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from conftest import load_hook_module

SWEEP = "com.captaincodeau.ccw-sweep"
_WARN = timedelta(minutes=31).total_seconds()
_ALERT = timedelta(hours=4, minutes=11).total_seconds()


def _freshness() -> ModuleType:
    return load_hook_module("ccw_freshness_check", "ccw-freshness-check.py")


def _write_log(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _started(at: str) -> dict[str, object]:
    return {"at": at, "status": "sweep-started", "session": None, "project": None,
            "message": "sweep started (pid 2680)", "elapsed_ms": None}


def _summary(at: str, message: str, status: str = "error") -> dict[str, object]:
    return {"at": at, "status": status, "session": None, "project": None,
            "message": message, "elapsed_ms": None}


def _real_9_oct(tmp_path: Path) -> Path:
    return _write_log(
        tmp_path / "capture.jsonl",
        [
            _started("2026-10-08T15:00:05+00:00"),
            _summary("2026-10-09T00:35:45+00:00",
                     "sweep-triggered build failed: OSError: [Errno 22] Invalid argument"),
            _summary("2026-10-09T00:52:39+00:00",
                     "sweep: 30981 items, 7 stored, 30 with sidecars, 1 failed"),
        ],
    )


def test_the_finished_run_is_read_from_its_summary(tmp_path: Path) -> None:
    outcome = _freshness().latest_sweep_outcome(_real_9_oct(tmp_path))
    assert outcome is not None
    failed, items, at = outcome
    assert (failed, items) == (1, 30981)
    assert at == datetime(2026, 10, 9, 0, 52, 39, tzinfo=UTC)


def test_a_run_still_open_has_no_outcome(tmp_path: Path) -> None:
    """A start after the newest summary means that summary is the previous run's:
    it cannot explain the current exit code."""
    log = _real_9_oct(tmp_path)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_started("2026-10-09T15:00:05+00:00")) + "\n")
    assert _freshness().latest_sweep_outcome(log) is None


def test_a_missing_log_has_no_outcome(tmp_path: Path) -> None:
    assert _freshness().latest_sweep_outcome(tmp_path / "absent.jsonl") is None


def test_a_finished_run_with_failed_items_says_so_and_points_at_capture_log(
    tmp_path: Path,
) -> None:
    freshness = _freshness()
    log = _real_9_oct(tmp_path)
    outcome = freshness.latest_sweep_outcome(log)
    message = freshness.job_message(SWEEP, 1, _ALERT, outcome=outcome, capture_log=log)
    assert "has been failing for" not in message, message
    assert "1 of 30981 item(s) failed" in message, message
    assert str(log) in message, message
    assert "~/.claude/logs" not in message, message
    # Capped at WARNING since W-20261010-A12 (Gavin, Q10): never the spoken ALERT.
    assert message.startswith("cc-warehouse: WARNING - "), message
    assert "exit 1" in message and "4 h 11 min" in message, message


def test_the_tiers_still_apply_to_the_finished_run_wording(tmp_path: Path) -> None:
    freshness = _freshness()
    log = _real_9_oct(tmp_path)
    outcome = freshness.latest_sweep_outcome(log)
    mild = freshness.job_message(SWEEP, 1, 60.0, outcome=outcome, capture_log=log)
    warn = freshness.job_message(SWEEP, 1, _WARN, outcome=outcome, capture_log=log)
    assert "WARNING" not in mild and "ALERT" not in mild
    assert warn.startswith("cc-warehouse: WARNING - ")


def test_no_failed_items_keeps_the_job_wording(tmp_path: Path) -> None:
    """Exit 1 with '0 failed' (a refusal, say) is not explained by the summary."""
    freshness = _freshness()
    log = _write_log(
        tmp_path / "capture.jsonl",
        [_started("2026-10-08T15:00:05+00:00"),
         _summary("2026-10-09T00:52:39+00:00",
                  "sweep: 30981 items, 7 stored, 30 with sidecars, 0 failed", "ok")],
    )
    outcome = freshness.latest_sweep_outcome(log)
    message = freshness.job_message(SWEEP, 1, _ALERT, outcome=outcome, capture_log=log)
    assert "has been failing for" in message


def test_other_jobs_keep_the_job_wording(tmp_path: Path) -> None:
    freshness = _freshness()
    log = _real_9_oct(tmp_path)
    outcome = freshness.latest_sweep_outcome(log)
    message = freshness.job_message(
        "com.captaincodeau.ccw-archive", 1, _ALERT, outcome=outcome, capture_log=log
    )
    assert "has been failing for" in message and "30981" not in message
