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
per test_doctor_external_contract.py) and escalates on how many CONSECUTIVE
session-starts in a row it has been unhealthy, a count persisted in a state
file. The raw uncaptured figure still rides along as detail in the message;
it just does not drive the alarm.
"""

import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from conftest import REPO_ROOT

HOOKS_DIR = REPO_ROOT / "plugins" / "cc-capture" / "hooks"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _freshness() -> ModuleType:
    return _load("ccw_freshness_check", HOOKS_DIR / "ccw-freshness-check.py")


def test_reads_the_pinned_doctor_substring() -> None:
    report = "  ok  uncaptured  Uncaptured: 296 session(s), 11 sub-agent(s) in ...\n"
    assert _freshness().extract_uncaptured(report) == 296


def test_missing_substring_is_none() -> None:
    assert _freshness().extract_uncaptured("no archive configured\n") is None


def test_zero_is_a_real_zero_not_a_miss() -> None:
    assert _freshness().extract_uncaptured("Uncaptured: 0 session(s)\n") == 0


def test_healthy_streak_is_silent_no_matter_the_backlog() -> None:
    """The exact false-alarm case found on real data: a large chronic
    uncaptured count with a healthy (streak 0) doctor verdict must stay
    quiet."""
    freshness = _freshness()
    assert freshness.freshness_message(0, 298) is None
    assert freshness.freshness_message(0, None) is None


def test_one_bad_check_differs_from_fifty_in_a_row() -> None:
    """The oracle test named in the ticket: output for 1 differs from output
    for 50 - here expressed as consecutive broken checks, the quantity that
    actually rises only when something is really wrong."""
    freshness = _freshness()
    low = freshness.freshness_message(1, 5)
    high = freshness.freshness_message(50, 5)
    assert low is not None
    assert high is not None
    assert low != high


def test_escalates_monotonically_across_tiers() -> None:
    freshness = _freshness()
    mild = freshness.freshness_message(1, 5)
    warn = freshness.freshness_message(3, 5)
    alert = freshness.freshness_message(6, 5)
    assert mild and warn and alert
    assert "WARNING" not in mild
    assert "ALERT" not in mild
    assert "WARNING" in warn
    assert "ALERT" not in warn
    assert "ALERT" in alert


def test_message_carries_the_streak_and_the_gap_figure() -> None:
    message = _freshness().freshness_message(3, 42)
    assert message is not None
    assert "3" in message
    assert "42" in message


def test_unknown_gap_figure_still_escalates_on_streak_alone() -> None:
    """`ccw doctor` can fail before it ever prints the Uncaptured line (e.g.
    it crashes outright) - the streak alone must still be enough to warn."""
    assert _freshness().freshness_message(2, None) is not None


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


def test_streak_increments_and_resets(tmp_path: Path) -> None:
    freshness = _freshness()
    state_path = tmp_path / "ccw-freshness-state.json"
    assert freshness.read_streak(state_path) == 0
    freshness.write_streak(state_path, 1)
    assert freshness.read_streak(state_path) == 1
    freshness.write_streak(state_path, 4)
    assert freshness.read_streak(state_path) == 4
    freshness.write_streak(state_path, 0)
    assert freshness.read_streak(state_path) == 0


def test_corrupt_state_file_reads_as_zero_not_a_crash(tmp_path: Path) -> None:
    state_path = tmp_path / "ccw-freshness-state.json"
    state_path.write_text("not json", encoding="utf-8")
    assert _freshness().read_streak(state_path) == 0


def test_missing_state_file_reads_as_zero(tmp_path: Path) -> None:
    assert _freshness().read_streak(tmp_path / "does-not-exist.json") == 0


def test_writing_the_streak_does_not_erase_other_state_fields(tmp_path: Path) -> None:
    """The state file grows a second concern (backlog-growth tracking, below)
    sharing the same file - write_streak must read-modify-write, not blindly
    overwrite the whole file, or the two concerns would fight over it."""
    freshness = _freshness()
    state_path = tmp_path / "ccw-freshness-state.json"
    freshness.write_backlog_snapshot(state_path, 42, "2026-08-24T00:00:00+00:00")
    freshness.write_streak(state_path, 3)
    assert freshness.read_streak(state_path) == 3
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


def test_a_healthy_streak_never_prints_growth_context_either() -> None:
    """Mirrors test_healthy_streak_is_silent_no_matter_the_backlog exactly,
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
