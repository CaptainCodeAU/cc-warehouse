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
        return subprocess.CompletedProcess(argv, 0, "\tlast exit code = 0\n", "")

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


def test_a_failure_persisting_past_the_alert_threshold_also_speaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freshness = _freshness()
    _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    later = T0 + timedelta(seconds=freshness._ALERT_AFTER_S + 1)
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), later)
    assert len(run.desktop) == 1
    assert len(run.spoken) == 1
    assert _log_statuses(tmp_path)[-1] == "alert"


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


def test_an_unreachable_doctor_still_escalates_by_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kept from the count design (2026-09-07 ruling): a doctor that cannot be
    asked is not evidence of health, so it runs the same clock, with wording
    that does not claim capture failed."""
    freshness = _freshness()
    timeout = subprocess.TimeoutExpired(cmd=["/fake/bin/ccw", "doctor"], timeout=45)
    first = _drive(freshness, tmp_path, monkeypatch, capsys, timeout, T0)
    assert first.desktop == []
    later = T0 + timedelta(seconds=freshness._WARN_AFTER_S + 1)
    run = _drive(freshness, tmp_path, monkeypatch, capsys, timeout, later)
    assert len(run.desktop) == 1
    assert "could not check capture" in run.desktop[0][-1]


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


def test_a_check_that_died_without_a_verdict_counts_from_when_it_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A check killed mid-doctor leaves `check_started_at` newer than its last
    verdict. That check got no answer, so the broken period began then."""
    freshness = _freshness()
    (tmp_path / "state.json").write_text(
        json.dumps(
            {
                "broken_since": None,
                "last_verdict": "ok",
                "last_verdict_at": (T0 - timedelta(hours=5)).isoformat(),
                "check_started_at": (T0 - timedelta(hours=3)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(1), T0)
    assert len(run.spoken) == 1


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
    no second doctor starts (no pile-up), and the waiting itself runs the clock
    from when the hung check began."""
    freshness = _freshness()
    lock = tmp_path / "freshness.lock"
    started = T0 - timedelta(seconds=freshness._WARN_AFTER_S + 60)
    with lock.open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.utime(lock, (started.timestamp(), started.timestamp()))
        run = _drive(freshness, tmp_path, monkeypatch, capsys, _doctor(0), T0)
    assert run.doctor_calls == 0
    assert len(run.desktop) == 1
    assert "has not answered" in run.desktop[0][-1]


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
