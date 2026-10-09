"""Oracle tests: the SessionStart freshness check runs in the background, runs
`ccw doctor` once however many sessions start together, and escalates on how
LONG capture has been broken, not on how many sessions started meanwhile.

Rulings (Gavin, 2026-09-29, open item W-20260929-A93): (1) the check must never
block a session start; (2) escalate by time, not by count.

The incident behind (2), from `~/.claude/logs/ccw-hook.log`: two sessions
started five seconds apart at 01:45:19 and 01:45:24 each ran their own doctor
against the share, each counted one more "broken in a row", and one bad moment
became a WARNING desktop alert. A count of session starts measures how busy the
operator is, not how long capture has been down.

What `"async": true` does was established from Claude Code's own docs
(code.claude.com/docs/en/hooks) and the installed 2.1.284 binary's schema
string "If true, hook runs in background without blocking": plain stdout of an
async hook is DROPPED; only a JSON `hookSpecificOutput.additionalContext` (or
`systemMessage`) reaches the model, on the next turn, and never the screen; and
Claude Code does not enforce `timeout` on it. So the script must bound itself,
print JSON, and push anything a human must hear through `report()`.

Two tests here run the hook as real processes, because a lock is only proved by
processes that actually race for it. Every outside edge (ccw, launchctl,
osascript, the voice server) is faked in those processes too.
"""

import fcntl
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from conftest import HOOKS_DIR, UrlopenStub, load_hook_module

T0 = datetime(2026, 9, 29, 1, 45, 19, tzinfo=UTC)


@pytest.fixture(autouse=True)
def scratch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hook resolves LOG, STATE_PATH and LOCK_PATH from HOME when it is
    loaded, so a test that forgets to redirect one writes into a scratch
    home, never the real `~/.claude`. Real leak it closes: a red run on
    2026-09-29 left a lock file in the real `~/.claude/logs` because one
    helper had not yet been taught LOCK_PATH."""
    monkeypatch.setenv("HOME", str(tmp_path / "scratch-home"))
    # The warehouse root the hook reads repair's summary from: default only.
    monkeypatch.delenv("CCW_ROOT", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


def test_the_hook_never_points_at_the_real_home(tmp_path: Path) -> None:
    freshness = _freshness()
    for path in (freshness.LOG, freshness.STATE_PATH, freshness.LOCK_PATH):
        assert tmp_path in path.parents


def _freshness() -> ModuleType:
    return load_hook_module("ccw_freshness_check", "ccw-freshness-check.py")


def _doctor(rc: int, uncaptured: int = 42) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["/fake/bin/ccw", "doctor"], rc, f"Uncaptured: {uncaptured} session(s)\n", ""
    )


class Run:
    """What one in-process main() call did to the outside world."""

    def __init__(self) -> None:
        self.spoken: list[dict[str, Any]] = []
        self.desktop: list[list[str]] = []
        self.doctor_calls = 0
        self.stdout = ""


def _drive(
    freshness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    doctor: BaseException | subprocess.CompletedProcess[str],
    at: datetime,
    state_path: Path | None = None,
    jobs: dict[str, int] | None = None,
    running: frozenset[str] = frozenset(),
) -> Run:
    run = Run()
    monkeypatch.setattr(freshness, "LOG", tmp_path / "ccw-hook.log")
    monkeypatch.setattr(freshness, "STATE_PATH", state_path or tmp_path / "state.json")
    monkeypatch.setattr(freshness, "LOCK_PATH", tmp_path / "freshness.lock")
    monkeypatch.setattr(freshness, "find_ccw", lambda: "/fake/bin/ccw")
    monkeypatch.setattr(freshness, "_now", lambda: at)
    monkeypatch.setattr(freshness.sys, "platform", "darwin")

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "/fake/bin/ccw":
            run.doctor_calls += 1
            if isinstance(doctor, BaseException):
                raise doctor
            return doctor
        label = argv[-1].rsplit("/", 1)[-1]
        code = (jobs or {}).get(label, 0)
        state = "running" if label in running else "not running"
        out = f"\tstate = {state}\n\tlast exit code = {code}\n"
        return subprocess.CompletedProcess(argv, 0, out, "")

    def fake_popen(argv: list[str], **_kwargs: Any) -> object:
        if argv[0] == "osascript":
            run.desktop.append(argv)
        return object()

    def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> UrlopenStub:
        body = request.data
        assert isinstance(body, bytes)
        run.spoken.append(json.loads(body.decode("utf-8")))
        return UrlopenStub()

    monkeypatch.setattr(freshness.subprocess, "run", fake_run)
    monkeypatch.setattr(freshness.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(freshness.urllib.request, "urlopen", fake_urlopen)
    capsys.readouterr()
    assert freshness.main() == 0
    run.stdout = capsys.readouterr().out
    return run


def _log_statuses(tmp_path: Path) -> list[str]:
    lines = (tmp_path / "ccw-hook.log").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["status"] for line in lines]


# ---------------------------------------------------------------------------
# Ruling 2: time, not count.
# ---------------------------------------------------------------------------


def test_two_failures_five_seconds_apart_do_not_escalate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 01:45:19 / 01:45:24 incident, replayed. Under the old count this was
    streak 2, a WARNING and a desktop alert."""
    freshness = _freshness()
    first = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    second = _drive(
        freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(seconds=5)
    )
    assert first.desktop == [] and second.desktop == []
    assert first.spoken == [] and second.spoken == []
    assert _log_statuses(tmp_path)[-1] == "info"


def test_many_failures_inside_the_warn_window_stay_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Six starts in under half an hour was an ALERT under the count."""
    freshness = _freshness()
    for minutes in (0, 2, 5, 9, 14, 20):
        run = _drive(
            freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(minutes=minutes)
        )
        assert run.desktop == [] and run.spoken == []


def test_a_failure_persisting_past_the_warn_threshold_raises_a_desktop_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    later = T0 + timedelta(seconds=freshness._WARN_AFTER_S + 1)
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), later)
    assert len(run.desktop) == 1
    assert run.spoken == []
    assert _log_statuses(tmp_path)[-1] == "warn"


def _fail_every(
    freshness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    minutes: list[int],
) -> list[Run]:
    return [
        _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(minutes=m))
        for m in minutes
    ]


def test_a_failure_persisting_past_the_alert_threshold_also_speaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    runs = _fail_every(freshness, tmp_path, monkeypatch, capsys, [0, 40, 80, 121])
    assert len(runs[-1].desktop) == 1
    assert len(runs[-1].spoken) == 1
    assert _log_statuses(tmp_path)[-1] == "alert"


# ---------------------------------------------------------------------------
# Sent back 2026-09-29 (review of 9383200; ruling: Gavin, "send back, keep the
# background hook"). Four defects, each proved in a sandbox by the reviewers:
# an unanswered check started the clock; a gap between checks counted as
# broken; a hung check made every pane alert; a failed launchd job spoke at
# every session start regardless of the clock.
# ---------------------------------------------------------------------------


def test_a_killed_check_does_not_backdate_the_next_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 1. `claude -p` kills async hooks at teardown, and 177 of 420
    recent sessions were headless. A check that started 2.5 h ago and never
    answered made the next single failure a spoken ALERT."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "broken_since": None,
                "last_verdict": "ok",
                "last_verdict_at": (T0 - timedelta(hours=5)).isoformat(),
                "check_started_at": (T0 - timedelta(hours=2, minutes=30)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert run.desktop == [] and run.spoken == []
    assert _log_statuses(tmp_path)[-1] == "info"


def test_a_recently_killed_check_does_not_backdate_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 1 inside the continuity window: a check killed 40 minutes ago,
    then one failure, is a failure minutes old, not a 40-minute outage."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "broken_since": None,
                "last_verdict": "ok",
                "last_verdict_at": (T0 - timedelta(hours=5)).isoformat(),
                "check_started_at": (T0 - timedelta(minutes=40)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert run.desktop == [] and run.spoken == []


def test_an_unanswered_check_does_not_start_the_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 1. Only a real broken verdict starts an outage. A timeout, then a
    real failure 31 minutes later, is a failure that is minutes old."""
    freshness = _freshness()
    timeout = subprocess.TimeoutExpired(cmd=["/fake/bin/ccw", "doctor"], timeout=45)
    first = _drive(freshness, tmp_path, monkeypatch, capsys, timeout, T0)
    assert first.desktop == [] and first.spoken == []
    assert _log_statuses(tmp_path)[-1] == "unknown"
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(minutes=31))
    assert run.desktop == [] and run.spoken == []


def test_unanswered_checks_never_alarm_on_their_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 1, the other half: a doctor that never answers for hours is
    logged as unknown each time and tells the model. It never speaks, and
    its only desktop channel is the one 2-hour notice (ruling 2026-09-29,
    tested below); it never raises a capture-broken alert."""
    freshness = _freshness()
    timeout = subprocess.TimeoutExpired(cmd=["/fake/bin/ccw", "doctor"], timeout=45)
    desktops = 0
    for minutes in (0, 40, 80, 130, 300):
        run = _drive(
            freshness, tmp_path, monkeypatch, capsys, timeout, T0 + timedelta(minutes=minutes)
        )
        assert run.spoken == []
        desktops += len(run.desktop)
        assert all("WARNING" not in argv[-1] and "ALERT" not in argv[-1] for argv in run.desktop)
        context = json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "could not check capture" in context
    assert desktops == 1


def test_an_unanswered_check_does_not_extend_an_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 1 with fix 2: a real failure, then only unanswered checks for
    three hours, then a failure. Nothing in between said broken, so the
    second failure opens a new outage."""
    freshness = _freshness()
    timeout = subprocess.TimeoutExpired(cmd=["/fake/bin/ccw", "doctor"], timeout=45)
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    for minutes in (40, 80, 120, 160):
        _drive(freshness, tmp_path, monkeypatch, capsys, timeout, T0 + timedelta(minutes=minutes))
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(hours=3))
    assert run.desktop == [] and run.spoken == []


def test_a_weekend_between_two_failures_is_not_one_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 2. The reviewer's case: one Friday blip, one Monday blip, 64 h
    apart with no check between. It read as a 64 h outage and spoke."""
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(hours=64))
    assert run.desktop == [] and run.spoken == []
    assert _log_statuses(tmp_path)[-1] == "info"


def test_a_gap_just_over_the_continuity_window_starts_a_new_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    gap = freshness._CONTINUITY_S
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    inside = _drive(
        freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(seconds=gap)
    )
    assert len(inside.desktop) == 1  # an hour broken, re-seen within the window: WARN
    outside = _drive(
        freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(seconds=2 * gap + 1)
    )
    assert outside.desktop == [] and outside.spoken == []


def test_a_spoken_alert_needs_at_least_three_failing_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The property the window buys: with it under the ALERT threshold, two
    failures can never span 2 h as one outage, so a spoken alert always rests
    on three or more failing checks."""
    freshness = _freshness()
    assert freshness._CONTINUITY_S * 2 >= freshness._ALERT_AFTER_S
    assert freshness._CONTINUITY_S < freshness._ALERT_AFTER_S
    runs = _fail_every(freshness, tmp_path, monkeypatch, capsys, [0, 60, 119])
    assert all(r.spoken == [] for r in runs)
    runs = _fail_every(freshness, tmp_path, monkeypatch, capsys, [121])
    assert len(runs[0].spoken) == 1


def test_each_tier_alerts_once_per_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 3. Desktop once on crossing WARN, desktop plus voice once on
    crossing ALERT, then silence (logged, and the model still hears it)
    until the outage clears."""
    freshness = _freshness()
    runs = _fail_every(freshness, tmp_path, monkeypatch, capsys, list(range(0, 300, 20)))
    assert sum(len(r.desktop) for r in runs) == 2
    assert sum(len(r.spoken) for r in runs) == 1
    assert all(r.stdout for r in runs)


def test_a_new_outage_alerts_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    first = _fail_every(freshness, tmp_path, monkeypatch, capsys, [0, 20, 40])
    assert sum(len(r.desktop) for r in first) == 1
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(minutes=50))
    second = _fail_every(freshness, tmp_path, monkeypatch, capsys, [60, 80, 100])
    assert sum(len(r.desktop) for r in second) == 1


def test_a_hung_check_seen_by_three_panes_raises_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 3, the reviewer's sandbox: three panes during a hung check gave
    three desktop and three spoken alerts. A hung check is an unanswered one
    (fix 1), and only the lock holder ever alerts."""
    freshness = _freshness()
    _fail_every(freshness, tmp_path, monkeypatch, capsys, [0, 40, 80])
    lock = tmp_path / "freshness.lock"
    started = T0 + timedelta(minutes=85)
    runs: list[Run] = []
    with lock.open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.utime(lock, (started.timestamp(), started.timestamp()))
        for minutes in (140, 141, 142):
            runs.append(
                _drive(
                    freshness, tmp_path, monkeypatch, capsys, _doctor(1),
                    T0 + timedelta(minutes=minutes),
                )
            )
    assert all(r.doctor_calls == 0 for r in runs)
    assert sum(len(r.desktop) for r in runs) == 0
    assert sum(len(r.spoken) for r in runs) == 0
    assert _log_statuses(tmp_path)[-3:] == ["unknown"] * 3


_REPAIR = "com.captaincodeau.ccw-repair"
_SWEEP = "com.captaincodeau.ccw-sweep"


def test_a_failed_job_runs_the_same_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 4. The repair job will exit 1 on purpose until a refused folder is
    looked at, which used to mean desktop plus voice at every session start
    for a day. Now: quiet at first, desktop once at 30 minutes, voice once at
    2 hours, then quiet until it exits 0."""
    freshness = _freshness()
    runs = [
        _drive(
            freshness, tmp_path, monkeypatch, capsys, _doctor(0),
            T0 + timedelta(minutes=m), jobs={_REPAIR: 1},
        )
        for m in (0, 10, 31, 45, 90, 121, 180, 600)
    ]
    assert [len(r.desktop) for r in runs] == [0, 0, 1, 0, 0, 1, 0, 0]
    assert [len(r.spoken) for r in runs] == [0, 0, 0, 0, 0, 1, 0, 0]
    assert all("ccw-repair" in r.stdout for r in runs)


def test_a_job_that_recovers_and_fails_again_starts_a_new_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    for m in (0, 31):
        _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(minutes=m),
               jobs={_REPAIR: 1})
    ok = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(hours=1))
    assert ok.stdout == ""
    again = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0),
                   T0 + timedelta(hours=2), jobs={_REPAIR: 1})
    assert again.desktop == [] and again.spoken == []


def test_job_alerts_are_deduplicated_per_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two jobs failing are two problems: each gets its own WARN, once."""
    freshness = _freshness()
    runs = [
        _drive(
            freshness, tmp_path, monkeypatch, capsys, _doctor(0),
            T0 + timedelta(minutes=m), jobs={_REPAIR: 1, _SWEEP: 2},
        )
        for m in (0, 31, 45)
    ]
    assert [len(r.desktop) for r in runs] == [0, 2, 0]
    assert all(r.spoken == [] for r in runs)


def test_a_job_the_hook_could_not_ask_about_keeps_its_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """launchctl failing to answer is unknown, not recovered: the failure
    period must not reset and re-alert when launchctl answers again."""
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0, jobs={_REPAIR: 1})
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(minutes=31),
           jobs={_REPAIR: 1})
    def unanswerable(_label: str) -> tuple[int | None, str | None, bool]:
        return None, None, False

    monkeypatch.setattr(freshness, "_job_report", unanswerable)
    capsys.readouterr()
    monkeypatch.setattr(freshness, "_now", lambda: T0 + timedelta(minutes=40))
    freshness.main()
    monkeypatch.undo()
    again = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0),
                   T0 + timedelta(minutes=50), jobs={_REPAIR: 1})
    assert again.desktop == []
    # Still timed from T0, so ALERT lands on schedule, not two hours later.
    alert = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0),
                   T0 + timedelta(minutes=121), jobs={_REPAIR: 1})
    assert len(alert.spoken) == 1


def test_the_thresholds_are_the_ruled_ones() -> None:
    """30 minutes to a desktop alert, 2 hours to a spoken one. Pinned so a
    change to either is a deliberate, reviewed edit."""
    freshness = _freshness()
    assert freshness._WARN_AFTER_S == 30 * 60
    assert freshness._ALERT_AFTER_S == 2 * 60 * 60


def test_recovery_clears_the_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Broken for hours, then one healthy check, then a fresh failure: the new
    failure starts from zero, so it is quiet."""
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(hours=3))
    healthy = _drive(
        freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(hours=3, minutes=1)
    )
    assert healthy.stdout.strip() == ""
    again = _drive(
        freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(hours=3, minutes=2)
    )
    assert again.desktop == [] and again.spoken == []
    assert _log_statuses(tmp_path)[-1] == "info"


def test_the_message_names_how_long_it_has_been_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(minutes=47))
    assert "47 min" in run.desktop[0][-1]


# ---------------------------------------------------------------------------
# Edge cases: the state file.
# ---------------------------------------------------------------------------


def test_a_corrupt_state_file_fails_toward_alerting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A state file that exists but cannot be read has lost the start time.
    Treating that as "just started" would restart the clock on every check the
    corruption survives; so it warns at once instead."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert len(run.desktop) == 1


def test_a_garbled_start_time_fails_toward_alerting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Readable JSON, but the one field that holds the clock is not a time:
    the same loss as a corrupt file, so the same answer."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text(
        json.dumps({"broken_since": "yesterday-ish"}), encoding="utf-8"
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert len(run.desktop) == 1


def test_an_unwritable_state_file_fails_toward_alerting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The silent shape: every check writes "broken since now", the write is
    lost, and the next check starts the clock again, forever. Warn instead."""
    freshness = _freshness()
    state_dir = tmp_path / "ro"
    state_dir.mkdir()
    state_dir.chmod(0o500)
    try:
        run = _drive(
            freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0, state_dir / "state.json"
        )
        assert len(run.desktop) == 1
    finally:
        state_dir.chmod(0o700)


def test_a_missing_state_file_is_a_first_check_not_an_alarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control for the two above: no file at all is the first check ever (a
    fresh install), which starts the clock and stays quiet."""
    freshness = _freshness()
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert run.desktop == [] and run.spoken == []
    assert _log_statuses(tmp_path)[-1] == "info"


def test_an_old_count_state_file_carries_its_broken_period_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Upgrading must not silently restart a broken period. A count of 1 or
    more means the previous check failed, and `last_checked_at` is when that
    check ran, so capture has been broken at least since then."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "consecutive_broken": 3,
                "last_uncaptured": 40,
                "last_checked_at": (T0 - timedelta(minutes=45)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert len(run.desktop) == 1


def test_an_old_count_state_file_from_days_ago_is_not_carried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fix 2 on the upgrade path: the reviewer's "old count=1 from 3 days
    ago" read as 72 h and spoke."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text(
        json.dumps(
            {"consecutive_broken": 1, "last_checked_at": (T0 - timedelta(days=3)).isoformat()}
        ),
        encoding="utf-8",
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert run.desktop == [] and run.spoken == []


# ---------------------------------------------------------------------------
# Ruling 1: background, and one doctor for many panes.
# ---------------------------------------------------------------------------


def _hooks() -> dict[str, Any]:
    return json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))


def test_the_session_start_entry_runs_in_the_background() -> None:
    entry = _hooks()["hooks"]["SessionStart"][0]["hooks"][0]
    assert entry.get("async") is True
    # asyncRewake would interrupt the model on exit 2 and brings back the
    # enforced timeout; neither is wanted here.
    assert "asyncRewake" not in entry


def test_the_capture_hook_stays_in_the_foreground() -> None:
    """Control: SessionEnd capture must finish its synchronous JSONL write
    before the session is gone. Only the SessionStart check moves."""
    entry = _hooks()["hooks"]["SessionEnd"][0]["hooks"][0]
    assert "async" not in entry


def test_a_message_reaches_the_model_as_json_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An async hook's plain stdout is dropped; only JSON additionalContext is
    delivered (next turn, to the model). The line must survive as that."""
    freshness = _freshness()
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    payload = json.loads(run.stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert output["additionalContext"].startswith("cc-warehouse: ")


def test_a_healthy_check_prints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0)
    assert run.stdout == ""


def test_a_pane_that_finds_the_lock_held_reuses_the_last_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    lock = tmp_path / "freshness.lock"
    with lock.open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.utime(lock, (T0.timestamp(), T0.timestamp()))
        run = _drive(
            freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(seconds=5)
        )
    assert run.doctor_calls == 0
    assert run.desktop == [] and run.spoken == []
    assert _log_statuses(tmp_path)[-1] == "reused"
    # The model still hears the last verdict.
    context = json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "capture check failed" in context


def test_a_lock_held_far_past_its_budget_is_an_unanswered_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Edge case 3, a doctor hung on the share: its holder keeps the lock, so
    no second doctor starts (no pile-up). The hang is an unanswered check:
    logged as unknown and handed to the model, never alarmed (fix 1)."""
    freshness = _freshness()
    lock = tmp_path / "freshness.lock"
    started = T0 - timedelta(seconds=freshness._WARN_AFTER_S + 60)
    with lock.open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.utime(lock, (started.timestamp(), started.timestamp()))
        run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0)
    assert run.doctor_calls == 0
    assert run.desktop == [] and run.spoken == []
    assert _log_statuses(tmp_path)[-1] == "unknown"
    context = json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "has not answered" in context


# ---------------------------------------------------------------------------
# Real processes.
# ---------------------------------------------------------------------------

_RUNNER = textwrap.dedent(
    """
    import importlib.util, sys, urllib.request
    spec = importlib.util.spec_from_file_location("fc", sys.argv[1])
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    def refuse(*a, **k):
        raise OSError("voice disabled in tests")
    m.urllib.request.urlopen = refuse
    sys.exit(m.main())
    """
)


def _sandbox(tmp_path: Path, doctor_sleep: float) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    (home / ".claude" / "logs").mkdir(parents=True)
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    counter = tmp_path / "doctor-runs"
    ccw = fakebin / "ccw"
    # A doctor meant to be killed `exec`s its sleep, so the pid it records IS
    # the process holding the inherited lock fd; a plain `sleep` child would
    # survive a kill of the shell and keep the lock, which is this fake's
    # shape, not ccw's (Python's subprocess closes fds in its own children).
    body = (
        f"exec sleep {doctor_sleep}\n"
        if doctor_sleep >= 10
        else f"sleep {doctor_sleep}\necho 'Uncaptured: 1 session(s)'\nexit 0\n"
    )
    ccw.write_text(f"#!/bin/sh\necho $$ >> '{counter}'\n{body}", encoding="utf-8")
    (fakebin / "launchctl").write_text(
        "#!/bin/sh\nprintf '\\tlast exit code = 0\\n'\n", encoding="utf-8"
    )
    (fakebin / "osascript").write_text(
        f"#!/bin/sh\necho osa >> '{tmp_path / 'osa'}'\n", encoding="utf-8"
    )
    for tool in fakebin.iterdir():
        tool.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "CCW_BIN": str(ccw),
    }
    return env, counter


def _spawn(env: dict[str, str], tmp_path: Path) -> subprocess.Popen[bytes]:
    runner = tmp_path / "runner.py"
    runner.write_text(_RUNNER, encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(runner), str(HOOKS_DIR / "ccw-freshness-check.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_for_lines(path: Path, count: int, within: float = 10.0) -> list[str]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if path.exists():
            lines = path.read_text(encoding="utf-8").split()
            if len(lines) >= count:
                return lines
        time.sleep(0.05)
    raise AssertionError(f"{path} never reached {count} line(s)")


def test_concurrent_session_starts_run_doctor_once(tmp_path: Path) -> None:
    env, counter = _sandbox(tmp_path, doctor_sleep=3)
    procs = [_spawn(env, tmp_path) for _ in range(4)]
    for proc in procs:
        assert proc.wait(timeout=30) == 0
    assert len(counter.read_text(encoding="utf-8").split()) == 1


def test_a_killed_hook_leaves_its_doctor_holding_the_lock(tmp_path: Path) -> None:
    """Edge case 3 without Claude Code's help: an async hook has no enforced
    timeout, and an interactive exit may orphan it. If the hook process dies
    while doctor is still running, a new session start must not start a
    second doctor beside the first."""
    env, counter = _sandbox(tmp_path, doctor_sleep=15)
    first = _spawn(env, tmp_path)
    doctor_pid = int(_wait_for_lines(counter, 1)[0])
    try:
        first.kill()
        first.wait(timeout=10)
        second = _spawn(env, tmp_path)
        assert second.wait(timeout=30) == 0
        assert len(counter.read_text(encoding="utf-8").split()) == 1
    finally:
        try:
            os.kill(doctor_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_a_dead_holder_never_leaves_a_stale_lock(tmp_path: Path) -> None:
    """Edge case 4: the lock is a kernel `flock`, released when the last
    process holding it exits. No pid is recorded or trusted, so a dead holder
    cannot keep the next check out (the W-20260929-A84 class)."""
    env, counter = _sandbox(tmp_path, doctor_sleep=15)
    first = _spawn(env, tmp_path)
    doctor_pid = int(_wait_for_lines(counter, 1)[0])
    first.kill()
    first.wait(timeout=10)
    os.kill(doctor_pid, signal.SIGKILL)
    time.sleep(0.2)
    quick_env, _ = _sandbox(tmp_path / "quick", doctor_sleep=0)
    quick_env["HOME"] = env["HOME"]
    quick_env["CCW_BIN"] = env["CCW_BIN"].replace("/bin/ccw", "/quick/bin/ccw")
    (tmp_path / "quick" / "bin" / "ccw").write_text(
        f"#!/bin/sh\necho $$ >> '{counter}'\necho 'Uncaptured: 1 session(s)'\nexit 0\n",
        encoding="utf-8",
    )
    second = _spawn(quick_env, tmp_path)
    assert second.wait(timeout=30) == 0
    assert len(counter.read_text(encoding="utf-8").split()) == 2


# ---------------------------------------------------------------------------
# Repair's refusals (interface agreed 2026-09-29 between the conductor and the
# fix-doctor-quick worker). `ccw repair` exits 1 only when repair itself
# broke; a folder it will not re-render because ccw cannot explain a change
# is reported through ONE `repair-summary` line per run in the warehouse's
# logs/capture.jsonl. The hook reads the latest one and puts open refusals on
# the same clock, from `oldest_refusal_at`, with its own dedup.
# ---------------------------------------------------------------------------

# A line the REAL writer produced (integrate-0929, 2026-09-29): `ccw repair` run
# in a sandbox on a folder it had to hold (a changed tool result whose source had
# changed too), copied verbatim from logs/capture.jsonl. Note the microseconds in
# both timestamps. tests/test_integration_0929.py pins the writer to this exact
# key set and these value types, so neither side can drift alone.
# W-20261010-A12 extended it BY HAND (message, elapsed_ms, which was null, and
# the five work counts), in the shape tests/test_run_summary_logging.py pins;
# the hook still reads only status, open_refusals and oldest_refusal_at.
_SUMMARY_FIXTURE = json.loads(
    '{"at": "2026-09-29T05:28:39.478309+00:00", "status": "repair-summary",'
    ' "session": null, "project": null,'
    ' "message": "repair: 1 checked, 0 fixed, 0 still broken, 1 held, 0 pending;'
    ' 1 open refusal(s)",'
    ' "elapsed_ms": 1840, "open_refusals": 1,'
    ' "oldest_refusal_at": "2026-09-29T05:28:39.478226+00:00",'
    ' "checked": 1, "fixed": 0, "still_broken": 0, "held": 1, "pending": 0}'
)


def _summary(tmp_path: Path, at: datetime, open_refusals: int, oldest: datetime | None) -> None:
    log = tmp_path / "scratch-home" / "cc-warehouse-data" / "logs" / "capture.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    line = dict(_SUMMARY_FIXTURE)
    line.update(
        {
            "at": at.isoformat(),
            "message": f"repair: {open_refusals} open refusal(s)",
            "open_refusals": open_refusals,
            "oldest_refusal_at": oldest.isoformat() if oldest else None,
        }
    )
    other = {"at": at.isoformat(), "status": "repair-refused", "session": "s", "project": "p",
             "elapsed_ms": None, "message": "ignored: only the summary counts"}
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")
        handle.write(json.dumps(other) + "\n")


def _at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        minutes: float) -> Run:
    return _drive(
        _freshness_cached(), tmp_path, monkeypatch, capsys, _doctor(0),
        T0 + timedelta(minutes=minutes),
    )


_CACHE: dict[str, ModuleType] = {}


def _freshness_cached() -> ModuleType:
    if "m" not in _CACHE:
        _CACHE["m"] = _freshness()
    return _CACHE["m"]


@pytest.fixture(autouse=True)
def fresh_module_cache() -> None:
    _CACHE.clear()


def test_the_summary_fixture_matches_the_agreed_interface() -> None:
    assert set(_SUMMARY_FIXTURE) == {
        "at", "status", "session", "project", "elapsed_ms", "message",
        "open_refusals", "oldest_refusal_at",
        "checked", "fixed", "still_broken", "held", "pending",
    }
    assert _SUMMARY_FIXTURE["status"] == "repair-summary"


def test_no_repair_summary_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _at(tmp_path, monkeypatch, capsys, 0)
    assert run.stdout == ""


def test_open_refusals_run_the_clock_from_the_oldest_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _summary(tmp_path, T0 - timedelta(minutes=20), 2, T0 - timedelta(minutes=20))
    runs = [_at(tmp_path, monkeypatch, capsys, m) for m in (0, 5, 11, 30, 101, 150)]
    assert [len(r.desktop) for r in runs] == [0, 0, 1, 0, 1, 0]
    assert [len(r.spoken) for r in runs] == [0, 0, 0, 0, 1, 0]
    assert all("2 archive folder(s)" in r.stdout for r in runs)


def test_a_summary_with_no_open_refusals_clears_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _summary(tmp_path, T0 - timedelta(minutes=40), 1, T0 - timedelta(minutes=40))
    warned = _at(tmp_path, monkeypatch, capsys, 0)
    assert len(warned.desktop) == 1
    _summary(tmp_path, T0 + timedelta(minutes=5), 0, None)
    cleared = _at(tmp_path, monkeypatch, capsys, 10)
    assert cleared.stdout == ""
    _summary(tmp_path, T0 + timedelta(minutes=15), 1, T0 - timedelta(minutes=40))
    again = _at(tmp_path, monkeypatch, capsys, 30)
    assert len(again.desktop) == 1  # a new period alerts again


def test_a_reminder_right_after_repairs_own_alert_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repair raises its own one-time alert on a NEW refusal. A reminder
    minutes later would speak twice about one run, so it is deferred, never
    dropped."""
    _summary(tmp_path, T0 - timedelta(minutes=2), 3, T0 - timedelta(hours=3))
    soon = _at(tmp_path, monkeypatch, capsys, 0)
    assert soon.desktop == [] and soon.spoken == []
    later = _at(tmp_path, monkeypatch, capsys, 11)
    assert len(later.desktop) == 1 and len(later.spoken) == 1


# ---------------------------------------------------------------------------
# Rulings 2026-09-29 on the send-back report (Gavin via the conductor):
# (a) option ii: unanswered checks that run unbroken for 2 h, with no real
#     verdict between them, raise ONE desktop-only notice, deduplicated, never
#     voice and never a capture-broken outage;
# (c) the warehouse root comes from `ccw doctor`'s own `config` line, not from
#     reading config.toml by hand; CCW_ROOT then the default only when doctor
#     gave no answer.
# ---------------------------------------------------------------------------

_TIMEOUT = subprocess.TimeoutExpired(cmd=["/fake/bin/ccw", "doctor"], timeout=45)


def _unknown_at(
    freshness: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], minutes: float,
) -> Run:
    at = T0 + timedelta(minutes=minutes)
    return _drive(freshness, tmp_path, monkeypatch, capsys, _TIMEOUT, at)


def _broken_since_now(freshness: ModuleType, tmp_path: Path, at: datetime) -> datetime | None:
    return freshness.carried_broken_since(freshness._read_state(tmp_path / "state.json"), at)


def test_two_hours_of_unanswered_checks_raise_one_desktop_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    runs = [_unknown_at(freshness, tmp_path, monkeypatch, capsys, m) for m in range(0, 241, 30)]
    assert [len(r.desktop) for r in runs] == [0, 0, 0, 0, 1, 0, 0, 0, 0]
    assert all(r.spoken == [] for r in runs)
    assert "could not check capture for" in runs[4].desktop[0][-1]
    # It never opens a capture-broken outage.
    assert _broken_since_now(freshness, tmp_path, T0 + timedelta(minutes=240)) is None


def test_a_real_verdict_between_unanswered_checks_restarts_that_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    for m in (0, 45, 90):
        _unknown_at(freshness, tmp_path, monkeypatch, capsys, m)
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(minutes=100))
    runs = [_unknown_at(freshness, tmp_path, monkeypatch, capsys, m) for m in (110, 150, 200)]
    assert all(r.desktop == [] for r in runs)


def test_a_failing_verdict_also_restarts_the_unanswered_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    for m in (0, 45, 90):
        _unknown_at(freshness, tmp_path, monkeypatch, capsys, m)
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0 + timedelta(minutes=100))
    run = _unknown_at(freshness, tmp_path, monkeypatch, capsys, 130)
    assert run.desktop == []


def test_a_gap_between_unanswered_checks_restarts_that_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 1 h continuity window applies here too: two unanswered checks
    hours apart with nothing between are not two hours of evidence."""
    freshness = _freshness()
    _unknown_at(freshness, tmp_path, monkeypatch, capsys, 0)
    _unknown_at(freshness, tmp_path, monkeypatch, capsys, 50)
    run = _unknown_at(freshness, tmp_path, monkeypatch, capsys, 200)
    assert run.desktop == []


def test_the_unanswered_notice_comes_back_after_a_real_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    first = [_unknown_at(freshness, tmp_path, monkeypatch, capsys, m) for m in range(0, 181, 30)]
    assert sum(len(r.desktop) for r in first) == 1
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0 + timedelta(minutes=190))
    second = [_unknown_at(freshness, tmp_path, monkeypatch, capsys, m) for m in range(200, 381, 30)]
    assert sum(len(r.desktop) for r in second) == 1


# The `config` line as the installed `ccw doctor` printed it on the operator's
# machine, 2026-09-29, with the home directory replaced by a placeholder (this
# repo is public). Source of the format: doctor.py's
# f"root={config.root} archive_root={config.archive_root}".
_REAL_CONFIG_LINE = (
    "  ok  config      root=/home/alice/cc-warehouse-data "
    "archive_root=/Volumes/share/cc-warehouse-archive zone=Australia/Melbourne "
    "keep_objects=False keep_projections=False"
)


def test_the_root_is_read_from_doctors_config_line() -> None:
    report = (
        f"  ok  hook        found\n{_REAL_CONFIG_LINE}\n"
        "  ok  uncaptured  Uncaptured: 3 session(s)\n"
    )
    assert _freshness().extract_root(report) == Path("/home/alice/cc-warehouse-data")


def test_a_root_with_a_space_survives() -> None:
    line = _REAL_CONFIG_LINE.replace("/home/alice/cc-warehouse-data", "/home/alice/My Data")
    assert _freshness().extract_root(line) == Path("/home/alice/My Data")


def test_no_config_line_is_none() -> None:
    assert _freshness().extract_root("  ok  uncaptured  Uncaptured: 3 session(s)\n") is None


def test_repair_summary_is_read_from_the_root_doctor_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A custom root must win over the default: the summary under the
    default says nothing is refused, the one under doctor's root says 4."""
    freshness = _freshness()
    _summary(tmp_path, T0 - timedelta(minutes=5), 0, None)  # the default root
    custom = tmp_path / "custom root"
    log = custom / "logs" / "capture.jsonl"
    log.parent.mkdir(parents=True)
    line = dict(_SUMMARY_FIXTURE)
    line.update({"at": (T0 - timedelta(minutes=5)).isoformat(), "open_refusals": 4,
                 "oldest_refusal_at": (T0 - timedelta(minutes=5)).isoformat()})
    log.write_text(json.dumps(line) + "\n", encoding="utf-8")
    config_line = _REAL_CONFIG_LINE.replace("/home/alice/cc-warehouse-data", str(custom))
    doctor = subprocess.CompletedProcess(
        ["/fake/bin/ccw", "doctor"], 0, f"{config_line}\n  ok  x  Uncaptured: 1 session(s)\n", ""
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, doctor, T0)
    assert "4 archive folder(s)" in run.stdout


def test_without_a_doctor_answer_ccw_root_is_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    root = tmp_path / "env-root"
    log = root / "logs" / "capture.jsonl"
    log.parent.mkdir(parents=True)
    line = dict(_SUMMARY_FIXTURE)
    line.update({"at": (T0 - timedelta(minutes=5)).isoformat(), "open_refusals": 7,
                 "oldest_refusal_at": (T0 - timedelta(minutes=5)).isoformat()})
    log.write_text(json.dumps(line) + "\n", encoding="utf-8")
    monkeypatch.setenv("CCW_ROOT", str(root))
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _TIMEOUT, T0)
    assert "7 archive folder(s)" in run.stdout


def test_config_toml_is_no_longer_read_by_hand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling (c): one source for the root (R9). A config.toml naming another
    root must not be consulted by the hook itself."""
    freshness = _freshness()
    other = tmp_path / "toml-root"
    log = other / "logs" / "capture.jsonl"
    log.parent.mkdir(parents=True)
    line = dict(_SUMMARY_FIXTURE)
    line.update({"open_refusals": 9})
    log.write_text(json.dumps(line) + "\n", encoding="utf-8")
    cfg = tmp_path / "scratch-home" / ".config" / "cc-warehouse" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(f'root = "{other}"\n', encoding="utf-8")
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _TIMEOUT, T0)
    assert "9 archive folder(s)" not in run.stdout
    source = (HOOKS_DIR / "ccw-freshness-check.py").read_text(encoding="utf-8")
    assert "import tomllib" not in source
