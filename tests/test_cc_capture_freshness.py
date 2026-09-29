"""Oracle tests for the cc-capture plugin's SessionStart freshness signal.

Contract: ticket 24.7. `plugins/cc-capture/hooks/ccw-freshness-check.py` is
excluded from ruff/pyright (pyproject.toml: it runs under whatever `python3`
the system provides, not this project's py312 target) and from the sdist
(FORBIDDEN_DIRS in test_packaging.py), but it is still real code with real
behavior, and this repo now HOLDS that code (ticket 28.19 moved the plugin
in-repo on 2026-08-10), so its oracle tests belong here rather than nowhere.

DESIGN NOTE, found by running the first draft against real data on the
principal's machine: this signal must NOT key off the raw "Uncaptured: N
session(s)" count. That count sits at 250-350 on a healthy install (old
sessions predating the archive, hidden/warmup sessions never meant to be
captured) - doctor.py itself marks it "ok" rather than a blocking failure.
Keying tiers off that count would print ALERT every session, forever, on a
perfectly healthy install - the opposite of "escalating, clearing only by
fixing". Instead the script reads `ccw doctor`'s own PASS/FAIL verdict (its
exit code - already the mechanism the external `ccw-watch` tool relies on,
per test_doctor_external_contract.py) and escalates on how LONG it has been
unhealthy, a "broken since" time persisted in a state file (until 2026-09-29
it was a count of consecutive session starts; see
test_cc_capture_freshness_timing.py for why that changed). The raw
uncaptured figure still rides along as detail in the message; it just does
not drive the alarm.
"""

import json
import re
import subprocess
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from conftest import HOOKS_DIR, UrlopenStub, load_hook_module


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


def test_reads_the_pinned_doctor_substring() -> None:
    report = "  ok  uncaptured  Uncaptured: 296 session(s), 11 sub-agent(s) in ...\n"
    assert _freshness().extract_uncaptured(report) == 296


def test_missing_substring_is_none() -> None:
    assert _freshness().extract_uncaptured("no archive configured\n") is None


def test_zero_is_a_real_zero_not_a_miss() -> None:
    assert _freshness().extract_uncaptured("Uncaptured: 0 session(s)\n") == 0


# Broken periods, in seconds, one inside each tier (30 min / 2 h boundaries).
_MILD = 60.0
_WARN = 31 * 60.0
_ALERT = 3 * 60 * 60.0


def test_healthy_verdict_is_silent_no_matter_the_backlog() -> None:
    """The exact false-alarm case found on real data: a large chronic
    uncaptured count with a healthy doctor verdict (no broken period) must
    stay quiet."""
    freshness = _freshness()
    assert freshness.freshness_message(None, 298) is None
    assert freshness.freshness_message(None, None) is None


def test_one_bad_minute_differs_from_days_of_it() -> None:
    """The oracle test named in the ticket: output for 1 differs from output
    for 50 - here expressed as how long capture has been broken, the
    quantity that actually rises only when something is really wrong."""
    freshness = _freshness()
    low = freshness.freshness_message(_MILD, 5)
    high = freshness.freshness_message(50 * 24 * 3600.0, 5)
    assert low is not None
    assert high is not None
    assert low != high


def test_escalates_monotonically_across_tiers() -> None:
    freshness = _freshness()
    mild = freshness.freshness_message(_MILD, 5)
    warn = freshness.freshness_message(_WARN, 5)
    alert = freshness.freshness_message(_ALERT, 5)
    assert mild and warn and alert
    assert "WARNING" not in mild
    assert "ALERT" not in mild
    assert "WARNING" in warn
    assert "ALERT" not in warn
    assert "ALERT" in alert


def test_message_carries_the_duration_and_the_gap_figure() -> None:
    message = _freshness().freshness_message(_WARN, 42)
    assert message is not None
    assert "31 min" in message
    assert "42" in message


def test_unknown_gap_figure_still_escalates_on_time_alone() -> None:
    """`ccw doctor` can fail before it ever prints the Uncaptured line (e.g.
    it crashes outright) - the broken period alone must still be enough to
    warn."""
    message = _freshness().freshness_message(_WARN, None)
    assert message is not None
    assert "WARNING" in message


def test_the_floor_raises_the_tier_and_never_lowers_it() -> None:
    """A lost or unwritable state file floors the tier at WARNING (edge case
    2, fail toward alerting); it must not quieten an ALERT."""
    freshness = _freshness()
    floored = freshness.freshness_message(_MILD, 5, floor=1)
    assert floored is not None and "WARNING" in floored
    alert = freshness.freshness_message(_ALERT, 5, floor=1)
    assert alert is not None and "ALERT" in alert


# ---------------------------------------------------------------------------
# Watch the 3 scheduled launchd jobs (operator-approved follow-up, 2026-08-24 --
# see Plans/majestic-floating-cray.md). Real incident THIS check would have
# caught in 1 day instead of 2 weeks: the weekly `ccw-archive` job silently
# failed 591 (later 612) real sessions every run after a dependency it read was
# retired, with `ccw doctor`'s own PASS/FAIL verdict never affected (the
# archive job is not part of what doctor checks at all) - nothing above this
# point in the file would ever have noticed.
# ---------------------------------------------------------------------------


def test_reads_the_real_launchctl_print_wording() -> None:
    """Real `launchctl print gui/<uid>/<label>` output, captured on the
    operator's own machine 2026-08-24 (tab-indented, lowercase, no quotes -
    a DIFFERENT format from `launchctl list`'s plist-style output)."""
    text = "\tminimum runtime = 10\n\texit timeout = 5\n\truns = 2\n\tlast exit code = 1\n\n"
    assert _freshness().extract_last_exit(text) == 1


def test_a_healthy_job_reads_as_zero_not_a_miss() -> None:
    assert _freshness().extract_last_exit("\truns = 6\n\tlast exit code = 0\n") == 0


def test_missing_exit_line_is_none() -> None:
    """A job that has never run yet (or launchctl's own output format
    changed) prints no such line at all - must read as unknown, not 0 or a
    crash."""
    assert _freshness().extract_last_exit("\tstate = not running\n") is None


def test_no_broken_jobs_is_a_silent_empty_message() -> None:
    assert _freshness().job_health_message([]) is None


def test_one_broken_job_is_named_with_its_exit_code() -> None:
    message = _freshness().job_health_message(
        [("com.captaincodeau.ccw-archive", 1)]
    )
    assert message is not None
    assert "ccw-archive" in message
    assert "1" in message


def test_multiple_broken_jobs_are_all_named() -> None:
    message = _freshness().job_health_message(
        [("com.captaincodeau.ccw-archive", 1), ("com.captaincodeau.ccw-sweep", 2)]
    )
    assert message is not None
    assert "ccw-archive" in message
    assert "ccw-sweep" in message


def _since(state_path: Path) -> datetime | None:
    return _freshness().carried_broken_since(_freshness()._read_state(state_path))


def test_broken_since_is_carried_and_cleared(tmp_path: Path) -> None:
    freshness = _freshness()
    state_path = tmp_path / "ccw-freshness-state.json"
    assert _since(state_path) is None
    freshness._write_state(state_path, {"broken_since": "2026-09-29T01:45:19+00:00"})
    assert _since(state_path) == datetime(2026, 9, 29, 1, 45, 19, tzinfo=UTC)
    freshness._write_state(
        state_path, {"broken_since": None, "last_verdict_at": "2026-09-29T02:00:00+00:00"}
    )
    assert _since(state_path) is None


def test_corrupt_state_file_reads_as_lost_not_a_crash(tmp_path: Path) -> None:
    state_path = tmp_path / "ccw-freshness-state.json"
    state_path.write_text("not json", encoding="utf-8")
    assert _freshness()._load_state(state_path) == ({}, True)


def test_missing_state_file_reads_as_a_first_check(tmp_path: Path) -> None:
    assert _freshness()._load_state(tmp_path / "does-not-exist.json") == ({}, False)


def test_writing_the_clock_does_not_erase_other_state_fields(tmp_path: Path) -> None:
    """The state file holds a second concern (backlog-growth tracking, below)
    sharing the same file - every write must read-modify-write, not blindly
    overwrite the whole file, or the two concerns would fight over it."""
    freshness = _freshness()
    state_path = tmp_path / "ccw-freshness-state.json"
    freshness.write_backlog_snapshot(state_path, 42, "2026-08-24T00:00:00+00:00")
    freshness._write_state(state_path, {"broken_since": "2026-08-24T01:00:00+00:00"})
    assert _since(state_path) == datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    assert freshness.read_backlog_snapshot(state_path) == (42, "2026-08-24T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Alarm on backlog GROWTH RATE, not just a raw count or a broken doctor streak
# (operator-approved follow-up, 2026-08-24 -- see Plans/majestic-floating-cray.md).
# Applying this file's own hard-learned lesson: a raw count/rate is context,
# never the trigger by itself - this session's own real numbers (37 new
# uncaptured sessions in ~2h during ordinary multi-session usage, ~18/hr) are
# not reliably distinguishable from a real problem by rate alone.
# ---------------------------------------------------------------------------

def test_no_earlier_snapshot_means_no_rate() -> None:
    freshness = _freshness()
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    assert freshness.backlog_growth(None, None, 50, now) is None


def test_growth_rate_is_sessions_per_hour_since_the_last_check() -> None:
    freshness = _freshness()
    earlier = datetime(2026, 8, 24, 12, 0, tzinfo=UTC).isoformat()
    now = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)  # 2 hours later
    # matches this session's own real incident: 4 -> 40, over 2 hours = 18/hr
    assert freshness.backlog_growth(4, earlier, 40, now) == 18.0


def test_a_shrinking_backlog_is_a_negative_rate_not_clamped() -> None:
    """A sweep just ran and cleared most of the backlog - the rate should say
    so plainly, not be forced to zero."""
    freshness = _freshness()
    earlier = datetime(2026, 8, 24, 12, 0, tzinfo=UTC).isoformat()
    now = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
    assert freshness.backlog_growth(500, earlier, 4, now) == -496.0


def test_an_unparseable_earlier_timestamp_yields_no_rate_not_a_crash() -> None:
    freshness = _freshness()
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    assert freshness.backlog_growth(4, "not a timestamp", 40, now) is None


def test_a_healthy_verdict_never_prints_growth_context_either() -> None:
    """Mirrors test_healthy_verdict_is_silent_no_matter_the_backlog exactly,
    same false-alarm shape, new axis: growth context rides along on an
    escalating message, it is never itself the reason to speak."""
    freshness = _freshness()
    assert freshness.growth_context(None) == ""
    assert freshness.growth_context(0) == ""
    assert freshness.growth_context(-5) == ""  # shrinking is good news, not context to flag


def test_a_real_growth_rate_is_named_as_context() -> None:
    context = _freshness().growth_context(18.0)
    assert "18" in context
    assert "hr" in context


def test_backlog_snapshot_round_trips(tmp_path: Path) -> None:
    freshness = _freshness()
    state_path = tmp_path / "ccw-freshness-state.json"
    assert freshness.read_backlog_snapshot(state_path) == (None, None)
    freshness.write_backlog_snapshot(state_path, 12, "2026-08-24T01:00:00+00:00")
    assert freshness.read_backlog_snapshot(state_path) == (12, "2026-08-24T01:00:00+00:00")


def test_a_none_uncaptured_count_is_never_snapshotted(tmp_path: Path) -> None:
    """`ccw doctor` can fail before it ever prints the Uncaptured line - there
    is nothing meaningful to remember for the next comparison, and writing
    None would corrupt the next rate calculation, not just skip it."""
    freshness = _freshness()
    state_path = tmp_path / "ccw-freshness-state.json"
    freshness.write_backlog_snapshot(state_path, 12, "2026-08-24T01:00:00+00:00")
    freshness.write_backlog_snapshot(state_path, None, "2026-08-24T02:00:00+00:00")
    assert freshness.read_backlog_snapshot(state_path) == (12, "2026-08-24T01:00:00+00:00")


# Ticket 24.7 oracle test: a fence rejects `uv tool run` in any hook wrapper's
# actual invocation. Matched narrowly against the argv list shape
# (`["uv", "tool", "run"`), not the bare phrase - both wrapper docstrings quote
# that exact phrase in prose to document the 2026-08-03 incident that made
# this rule exist, and the fence must not flag its own history lesson.
_DANGEROUS_INVOCATION = re.compile(r'\[\s*"uv"\s*,\s*"tool"\s*,\s*"run"')


def test_no_hook_wrapper_invokes_a_bare_package_name() -> None:
    offenders: list[str] = []
    for path in sorted(HOOKS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if _DANGEROUS_INVOCATION.search(text):
            offenders.append(path.name)
    assert offenders == [], f"bare `uv tool run` invocation in: {offenders}"


def test_the_historical_prose_is_still_intact() -> None:
    """Control for the fence above: prove the pattern really can miss prose,
    so a pass above is not just an empty haystack."""
    text = (HOOKS_DIR / "ccw-hook.py").read_text(encoding="utf-8")
    assert "uv tool run" in text
    assert _DANGEROUS_INVOCATION.search(text) is None


# Ticket 24.7 oracle test: every CCW_* name a wrapper sets must be a name
# cc_warehouse actually reads. Compared LIVE against config.ENV_VARS, which
# the sibling-repo version of this test could never do (no dependency between
# the two repos existed there) - the whole reason to move the plugin in-repo.
_SET_PATTERN = re.compile(r'env\.setdefault\(\s*"(CCW_[A-Z_]+)"')


def test_every_env_var_a_wrapper_sets_is_a_real_ccw_name() -> None:
    from cc_warehouse.config import ENV_VARS

    offenders: list[str] = []
    for path in sorted(HOOKS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in _SET_PATTERN.findall(text):
            if name not in ENV_VARS:
                offenders.append(f"{path.name}: {name}")
    assert offenders == [], f"CCW_* names cc-warehouse never reads: {offenders}"


# ---------------------------------------------------------------------------
# A doctor that could not be ASKED is not a doctor that said FAIL
# (operator-approved fix, 2026-09-07). Real incident THIS closes: on
# 2026-09-07 `ccw doctor` was healthy and takes 2.75s, but had to cold-walk
# 27,277 files in ~/.claude/projects (4.2 GB) immediately after ccw-sweep
# wrote 486 archive folders in fifteen minutes. It went over the 15s budget
# twice, and the hook spoke a raw Python traceback aloud both times, at full
# volume, on the first occurrence, with no streak behind it.
#
# That is the opposite of what this file's own module docstring promises
# ("how many CONSECUTIVE session-starts in a row that verdict has been
# broken") and it contradicts broken_jobs()'s own stated principle, three
# functions further down the same file: "absence of evidence is not evidence
# of failure here". A probe that timed out produced NO verdict at all.
# ---------------------------------------------------------------------------


def test_an_unreachable_doctor_does_not_claim_capture_is_broken() -> None:
    """The wording must say the check could not get an answer, NOT that
    capture failed - on the real incident capture was working perfectly and
    had just archived a session in 24ms."""
    message = _freshness().freshness_message(_MILD, None, unreachable="TimeoutExpired")
    assert message is not None
    assert "could not" in message.lower()


def test_unreachable_and_failed_verdict_read_differently() -> None:
    """Two genuinely different situations - doctor ran and said FAIL, versus
    doctor never answered - must not print the same line, or the log cannot
    tell them apart afterwards."""
    freshness = _freshness()
    failed = freshness.freshness_message(_WARN, 5)
    unreachable = freshness.freshness_message(_WARN, 5, unreachable="TimeoutExpired")
    assert failed is not None
    assert unreachable is not None
    assert failed != unreachable


def test_an_unreachable_doctor_still_escalates_on_the_clock() -> None:
    """The half of the defect that was NOT about noise: because the timeout
    branch never touched the counter, a doctor that timed out every single
    session-start would have shouted the same flat line forever and never
    reached ALERT. It now runs the same broken clock."""
    freshness = _freshness()
    mild = freshness.freshness_message(_MILD, None, unreachable="TimeoutExpired")
    warn = freshness.freshness_message(_WARN, None, unreachable="TimeoutExpired")
    alert = freshness.freshness_message(_ALERT, None, unreachable="TimeoutExpired")
    assert mild and warn and alert
    assert "WARNING" not in mild
    assert "ALERT" not in mild
    assert "WARNING" in warn
    assert "ALERT" not in warn
    assert "ALERT" in alert


def test_a_healthy_doctor_stays_silent_even_with_an_unreachable_argument() -> None:
    """No broken period is silent on every axis this function has - the
    property the whole signal rests on (it clears when fixed, not when
    seen)."""
    assert _freshness().freshness_message(None, 298, unreachable="TimeoutExpired") is None


def test_the_named_cause_rides_along_in_the_message() -> None:
    """Whoever reads the banner needs to know WHY there was no answer -
    a timeout and a missing binary are not the same problem."""
    message = _freshness().freshness_message(_MILD, None, unreachable="TimeoutExpired")
    assert message is not None
    assert "TimeoutExpired" in message


# ---------------------------------------------------------------------------
# main() routing for an unreachable doctor. These drive the real entry point
# through a fake `subprocess.run`, because the three defects being closed here
# all lived in main()'s except branch and none of them were reachable from a
# pure function: it spoke on the FIRST occurrence, it never touched the streak
# counter, and it `return 0`-ed early, which silently skipped broken_jobs() -
# so the launchd job watch died at exactly the moment things looked worst.
# ---------------------------------------------------------------------------


def _timed_out() -> subprocess.TimeoutExpired:
    """The exact failure the operator hit on 2026-09-07: `ccw doctor` alive and
    healthy, but not finished inside its budget."""
    return subprocess.TimeoutExpired(cmd=["/fake/bin/ccw", "doctor"], timeout=45)


def _drive_main(
    freshness: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    doctor: BaseException | subprocess.CompletedProcess[str],
) -> tuple[list[dict[str, Any]], list[list[str]], dict[str, float], list[list[str]]]:
    """Run main() with every outside edge faked. `doctor` is either an
    exception to raise for the `ccw doctor` call, or a CompletedProcess to
    return. Yields (things spoken aloud, argv of every subprocess.run call,
    timeout budget per call, argv of every subprocess.Popen call - the
    desktop-notification channel, ticket 42 item #1)."""
    spoken: list[dict[str, Any]] = []
    calls: list[list[str]] = []
    budgets: dict[str, float] = {}
    popened: list[list[str]] = []

    monkeypatch.setattr(freshness, "LOG", tmp_path / "ccw-hook.log")
    monkeypatch.setattr(freshness, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(freshness, "LOCK_PATH", tmp_path / "freshness.lock")
    monkeypatch.setattr(freshness, "find_ccw", lambda: "/fake/bin/ccw")
    monkeypatch.setattr(freshness.sys, "platform", "darwin")

    def fake_run(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        timeout = kwargs.get("timeout")
        if isinstance(timeout, (int, float)):
            budgets["doctor" if argv[0] == "/fake/bin/ccw" else argv[0]] = float(timeout)
        if argv[0] == "/fake/bin/ccw":
            if isinstance(doctor, BaseException):
                raise doctor
            return doctor
        return subprocess.CompletedProcess(argv, 0, "\tlast exit code = 0\n", "")

    def fake_urlopen(
        request: urllib.request.Request, timeout: float = 0
    ) -> UrlopenStub:
        body = request.data
        assert isinstance(body, bytes)
        spoken.append(json.loads(body.decode("utf-8")))
        return UrlopenStub()

    def fake_popen(argv: list[str], **_kwargs: Any) -> object:
        popened.append(argv)
        return object()

    monkeypatch.setattr(freshness.subprocess, "run", fake_run)
    monkeypatch.setattr(freshness.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(freshness.urllib.request, "urlopen", fake_urlopen)

    assert freshness.main() == 0
    return spoken, calls, budgets, popened


def test_a_single_timeout_says_nothing_out_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported symptom: one slow moment produced a spoken raw Python
    traceback. report() speaks only on status "alert"/"error" (ticket 42 item
    #1), so the fix is that a timeout no longer takes that path."""
    freshness = _freshness()
    spoken, _, _, _ = _drive_main(freshness, tmp_path, monkeypatch, _timed_out())
    assert spoken == []


def test_a_single_timeout_raises_no_desktop_notification_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first-ever unreachable doctor is inside the first half hour - it must
    stay as quiet on the new desktop channel as it already is on voice, or a
    perfectly ordinary slow moment starts popping up notifications."""
    freshness = _freshness()
    _, _, _, popened = _drive_main(freshness, tmp_path, monkeypatch, _timed_out())
    assert not any(argv[0] == "osascript" for argv in popened)


def _seed_broken(tmp_path: Path, seconds_ago: float) -> None:
    """A state file saying capture has been broken for `seconds_ago`."""
    since = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    _freshness()._write_state(tmp_path / "state.json", {"broken_since": since.isoformat()})


def _broken_since(tmp_path: Path) -> datetime | None:
    freshness = _freshness()
    return freshness.carried_broken_since(freshness._read_state(tmp_path / "state.json"))


def test_a_timeout_starts_the_broken_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half of the defect that was not about noise: the old branch never
    wrote the counter, so a permanently unreachable doctor could never reach
    WARNING, let alone ALERT."""
    freshness = _freshness()
    _drive_main(freshness, tmp_path, monkeypatch, _timed_out())
    assert _broken_since(tmp_path) is not None


def test_a_timeout_still_checks_the_scheduled_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third defect in the same branch: `return 0` skipped broken_jobs()
    entirely. The archive-job incident that check exists to catch would have
    gone unnoticed again, for as long as doctor stayed slow."""
    freshness = _freshness()
    _, calls, _, _ = _drive_main(freshness, tmp_path, monkeypatch, _timed_out())
    assert any(argv[0] == "launchctl" for argv in calls)


def test_a_healthy_doctor_still_clears_the_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: the fix must not break the property the whole signal rests on."""
    freshness = _freshness()
    _seed_broken(tmp_path, 3 * 60 * 60)
    healthy = subprocess.CompletedProcess(
        ["/fake/bin/ccw", "doctor"], 0, "Uncaptured: 36 session(s)\n", ""
    )
    spoken, _, _, popened = _drive_main(freshness, tmp_path, monkeypatch, healthy)
    assert _broken_since(tmp_path) is None
    assert spoken == []
    assert not any(argv[0] == "osascript" for argv in popened)


def test_the_doctor_budget_fits_a_cold_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured on the operator's machine 2026-09-07: `ccw doctor` is 2.75s
    warm, but has to walk 27,277 files / 4.2 GB under ~/.claude/projects, and
    lost that race twice inside the old 15s budget minutes after ccw-sweep
    wrote 486 archive folders. 45s is roughly 16x the warm figure."""
    freshness = _freshness()
    healthy = subprocess.CompletedProcess(
        ["/fake/bin/ccw", "doctor"], 0, "Uncaptured: 36 session(s)\n", ""
    )
    _, _, budgets, _ = _drive_main(freshness, tmp_path, monkeypatch, healthy)
    assert budgets["doctor"] >= 45
    assert budgets["launchctl"] == freshness._JOB_TIMEOUT


# ---------------------------------------------------------------------------
# Ticket 42 item #1: WARN raises a desktop notification, ALERT also speaks.
#
# Before this, `report()` only ever fired the voice POST on status "error",
# and nothing at all raised a desktop notification, so a WARN/ALERT tier
# only ever reached a human as SessionStart stdout - pull-based, not
# push-based, which is exactly why the 2026-09-09 incident needed a peer
# session to relay it by hand instead of an alert reaching the operator on
# its own. None of the branch these tests cover (main()'s escalating
# `report("warn"/"alert", message)` calls) had ANY test before this ticket.
# ---------------------------------------------------------------------------


def _failing_doctor(uncaptured: int = 42) -> subprocess.CompletedProcess[str]:
    """A `ccw doctor` that answered but reported unhealthy - the FAIL branch,
    distinct from `_timed_out()`'s could-not-be-asked branch."""
    return subprocess.CompletedProcess(
        ["/fake/bin/ccw", "doctor"], 1, f"Uncaptured: {uncaptured} session(s)\n", ""
    )


def test_a_warn_tier_period_raises_a_desktop_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broken past 30 minutes crosses into WARNING. Desktop fires from WARN
    onward; voice waits for ALERT (see the module's
    _DESKTOP_STATUSES/_SPEAKING_STATUSES) so a problem that is still
    resolving is not talked over."""
    freshness = _freshness()
    _seed_broken(tmp_path, freshness._WARN_AFTER_S + 60)
    spoken, _, _, popened = _drive_main(
        freshness, tmp_path, monkeypatch, _failing_doctor()
    )
    osa = [argv for argv in popened if argv[0] == "osascript"]
    assert len(osa) == 1
    assert spoken == []


def test_an_alert_tier_period_raises_both_desktop_and_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broken past 2 hours crosses into ALERT. This is the tier the whole
    ticket exists to make loud."""
    freshness = _freshness()
    _seed_broken(tmp_path, freshness._ALERT_AFTER_S + 60)
    spoken, _, _, popened = _drive_main(
        freshness, tmp_path, monkeypatch, _failing_doctor()
    )
    osa = [argv for argv in popened if argv[0] == "osascript"]
    assert len(osa) == 1
    assert len(spoken) == 1


def test_the_notification_body_matches_the_printed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """All three channels - log, the session's JSON context, desktop - must
    say the same thing; a notification with different wording than the
    session's line would be a second place for the message to drift."""
    freshness = _freshness()
    _seed_broken(tmp_path, freshness._WARN_AFTER_S + 60)
    _, _, _, popened = _drive_main(freshness, tmp_path, monkeypatch, _failing_doctor())
    printed = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    osa = next(argv for argv in popened if argv[0] == "osascript")
    script = osa[-1]
    assert printed and printed in script


def test_desktop_alert_escapes_quotes_so_the_applescript_stays_one_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ported by hand from notify.py's alert(): AppleScript is assembled as
    source text, so an unescaped double quote in the message would end the
    string early and change what runs."""
    freshness = _freshness()
    seen: list[list[str]] = []

    def fake_popen(argv: list[str], **_kwargs: Any) -> object:
        seen.append(argv)
        return object()

    monkeypatch.setattr(freshness.sys, "platform", "darwin")
    monkeypatch.setattr(freshness.subprocess, "Popen", fake_popen)
    freshness._desktop_alert("cc-warehouse", 'capture check failed ("desync")')
    script = seen[0][-1]
    assert '\\"desync\\"' in script


def test_desktop_alert_is_a_no_op_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    freshness = _freshness()
    seen: list[list[str]] = []

    def fake_popen(argv: list[str], **_kwargs: Any) -> object:
        seen.append(argv)
        return object()

    monkeypatch.setattr(freshness.sys, "platform", "linux")
    monkeypatch.setattr(freshness.subprocess, "Popen", fake_popen)
    freshness._desktop_alert("cc-warehouse", "anything")
    assert seen == []


def test_desktop_alert_swallows_a_failure_to_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """A notification sink must never be able to fail a SessionStart hook."""
    freshness = _freshness()

    def boom(*_args: Any, **_kwargs: Any) -> object:
        raise OSError("no such binary")

    monkeypatch.setattr(freshness.sys, "platform", "darwin")
    monkeypatch.setattr(freshness.subprocess, "Popen", boom)
    freshness._desktop_alert("cc-warehouse", "anything")


# ---------------------------------------------------------------------------
# The budget invariant. Every timeout this script sets is INNER: Claude Code
# kills the whole hook process at the `timeout` its own hooks.json declares,
# and an inner budget larger than that outer one can never fire on its own
# terms - the hard kill lands first, so the graceful except branch, the
# "unreachable" log line, the state write and broken_jobs() are all skipped.
# That is the same silent-early-exit shape this file's timeout fix exists to
# close, just one layer up, which is exactly why it needs a test and not a
# comment: the two numbers live in different files and nothing else relates
# them. Caught in review 2026-09-07, after the first draft of that fix set an
# inner 45s against an outer 20s.
# ---------------------------------------------------------------------------


def _outer_budget(event: str) -> int:
    """The `timeout` Claude Code enforces on the whole hook process for one
    event, read from the plugin's real hooks.json."""
    config = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    matchers = config["hooks"][event]
    return int(matchers[0]["hooks"][0]["timeout"])


def test_the_freshness_hook_budgets_fit_inside_its_own_outer_kill() -> None:
    freshness = _freshness()
    worst_case = freshness._DOCTOR_TIMEOUT + len(freshness._WATCHED_JOBS) * freshness._JOB_TIMEOUT
    assert worst_case < _outer_budget("SessionStart"), (
        f"inner budgets total {worst_case}s but Claude Code kills the hook at "
        f"{_outer_budget('SessionStart')}s"
    )


def test_the_capture_hook_obeys_the_same_invariant() -> None:
    """Control: prove the test reads real numbers, using the sibling hook that
    already had this right (inner 40 under outer 45) before the rule existed."""
    text = (HOOKS_DIR / "ccw-hook.py").read_text(encoding="utf-8")
    inner = max(int(m) for m in re.findall(r"timeout=(\d+),", text))
    assert inner == 40
    assert inner < _outer_budget("SessionEnd")


# ---------------------------------------------------------------------------
# The hooks must survive an OLD python3, because they do not choose their own
# interpreter. `hooks.json` invokes them as a bare `python3` and the hook
# process's PATH decides which one answers - a PATH no shell the operator can
# see is authoritative about. `/usr/bin/python3` on the author's Mac is 3.9.6.
#
# The failure this prevents is the worst shape available: the file dies while
# being PARSED, above every guard it contains, so `report()` is never reached.
# Nothing is logged, nothing is spoken, capture silently never runs - and
# `ccw doctor` still says the hook is fine, because registration is intact and
# doctor never asks whether the thing it found can EXECUTE.
#
# `from __future__ import annotations` makes every annotation a lazy string,
# so PEP 604 (`str | None`) costs nothing at import. Measured 2026-09-07: with
# that one line, ccw-freshness-check.py runs its FULL unreachable-doctor path
# under 3.9.6 - logs "unreachable" with detail, logs "warn", writes
# consecutive_broken=1, prints the banner. Without it, it dies at find_ccw's
# signature and writes nothing at all.
# ---------------------------------------------------------------------------

_FUTURE = "from __future__ import annotations"
# `match`/`case` are real 3.10+ SYNTAX; no __future__ import defers them.
_MATCH_STMT = re.compile(r"^\s*(match|case)\b.*:\s*$", re.M)


def test_every_hook_defers_its_annotations() -> None:
    offenders = [
        path.name
        for path in sorted(HOOKS_DIR.glob("*.py"))
        if _FUTURE not in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"hooks that would die on an old python3: {offenders}"


def test_the_hooks_glob_is_not_an_empty_haystack() -> None:
    """Control for the fence above: a pass means nothing if there are no hooks."""
    assert len(list(HOOKS_DIR.glob("*.py"))) >= 2


def test_no_hook_uses_syntax_no_future_import_can_defer() -> None:
    """The fence above only buys 3.9 compatibility for ANNOTATIONS. A match
    statement is parsed as syntax and would reintroduce the same silent death."""
    offenders = [
        path.name
        for path in sorted(HOOKS_DIR.glob("*.py"))
        if _MATCH_STMT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"3.10+ syntax a __future__ import cannot defer: {offenders}"


# ---------------------------------------------------------------------------
# EXECUTE the hooks under the oldest python3 on the box, rather than reasoning
# about which syntax is safe. The static fences above pin the __future__ import
# and reject match/case, and they were NOT ENOUGH: `from datetime import UTC` is
# an ordinary import of a name that only exists on 3.11+, so it passes every
# static check in this file and still kills the file at import time.
#
# That shipped. `83b7e73` claimed BOTH hooks survived 3.9.6 having tested only
# ccw-freshness-check.py, which uses `timezone.utc`, and generalised to
# ccw-hook.py, which did not. Generalising a shape from one sample is a lesson
# this repo already has in contract/HARNESS.md, and it still happened.
#
# So this runs the real files under a real old interpreter. It skips rather than
# fails where no old python exists (Linux CI often ships only a new one), which
# means it is a NET, not a proof - the static fences stay for that reason.
# ---------------------------------------------------------------------------


def _oldest_python() -> tuple[str, tuple[int, int]] | None:
    """A python3 on this box older than the hooks' floor, or None. macOS always
    has /usr/bin/python3 and it is usually years behind."""
    for path in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if not Path(path).is_file():
            continue
        probe = subprocess.run(
            [path, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.returncode != 0:
            continue
        try:
            major, minor = (int(n) for n in probe.stdout.split())
        except ValueError:
            continue
        if (major, minor) < (3, 10):
            return path, (major, minor)
    return None


def test_every_hook_imports_cleanly_under_an_old_python3() -> None:
    found = _oldest_python()
    if found is None:
        pytest.skip("no python3 older than 3.10 on this machine to test against")
    interpreter, version = found
    offenders: list[str] = []
    for path in sorted(HOOKS_DIR.glob("*.py")):
        result = subprocess.run(
            [interpreter, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={"CCW_SKIP_HOOK": "1", "HOME": "/tmp", "PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
        )
        if "Traceback" in result.stderr or result.returncode != 0:
            first = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "?"
            offenders.append(f"{path.name}: {first}")
    assert offenders == [], (
        f"hooks that die under python {version[0]}.{version[1]} ({interpreter}): {offenders}"
    )
