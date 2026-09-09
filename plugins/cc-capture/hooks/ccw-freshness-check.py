#!/usr/bin/env python3
"""SessionStart signal: warn, escalating, if cc-warehouse capture has fallen behind.

WHY THIS EXISTS (ticket 24.7). Capture already reports a failure loudly at
SessionEnd (see ccw-hook.py), but a failure that happens quietly in between -
a crashed detached render child, a hook that silently stopped firing - had
nothing that announced itself at the START of the next session. This closes
that gap with the one alert shape that has actually worked on this operator:
it lives in the same place Claude Code already surfaces a SessionStart hook's
stdout, it gets LOUDER the longer it stays broken instead of showing a flat
banner, and it goes quiet again the moment it is actually fixed.

PUSH, NOT JUST PULL (ticket 42 item #1, 2026-09-09). The WARN/ALERT tiers used
to ONLY print to that stdout, which only reaches a human if a new session
happens to start and someone reads the scrollback - exactly what happened in
the 2026-09-09 incident this line commemorates, where a peer session's own
SessionStart hook had to relay the alert by hand. `report()` now also raises a
real desktop notification from WARN onward and speaks aloud from ALERT onward
(see the _DESKTOP_STATUSES/_SPEAKING_STATUSES comment beside it) - the print
stays too, so a session-start that IS read still shows the same line.

WHAT DRIVES THE ALARM, AND WHAT DOES NOT (found by running the first draft
against real data). `ccw doctor` prints an "Uncaptured: N session(s)" figure
that sits at a few hundred on a perfectly healthy install - old sessions that
predate the archive, hidden/warmup sessions never meant to be captured -
which is exactly why doctor.py marks that line "ok" rather than a blocking
failure (see `_overdue` / `desync_detail` in src/cc_warehouse/doctor.py).
Keying the alarm on that raw count would ALERT every single session forever,
on a machine where nothing is actually wrong: the opposite of "escalating,
clearing only by fixing". So the alarm is driven by `ccw doctor`'s own
PASS/FAIL verdict (its exit code - the same signal the external `ccw-watch`
tool already relies on, per tests/test_doctor_external_contract.py) and by
how many CONSECUTIVE session-starts in a row that verdict has been broken, a
small count persisted in a state file next to the hook log. The raw
uncaptured figure still rides along in the message as context; it just does
not decide whether to speak at all.

R9 (one implementation): the health verdict and the uncaptured figure both
come straight from `ccw doctor` - this script recomputes neither.

`find_ccw` and `report` are intentionally duplicated from `ccw-hook.py` rather
than factored into a shared module: this script must never risk a regression
in the SessionEnd capture hook, which is the one thing on this machine that
must not break, so it does not import from or otherwise touch that file.

PORTABILITY: this runs under whatever `python3` the system provides
(`hooks.json` invokes it as a plain script), which is 3.10 on Ubuntu 22.04 -
see the ruff exclusion for `plugins/` in pyproject.toml. Kept portable by
hand, same as ccw-hook.py.
"""

# WHY THIS IMPORT IS THE FIRST LINE OF CODE IN THE FILE. These hooks do not
# choose their own interpreter: hooks.json invokes them as a bare `python3`,
# so whichever one the hook process's PATH resolves is the one that runs, and
# that is not the PATH of any shell the operator can inspect. On the author's
# own Mac `/usr/bin/python3` is 3.9.6. Without this line, PEP 604 annotations
# (`str | None`) are evaluated at import and raise TypeError while the file is
# still being read - ABOVE every guard below, so report() is never reached,
# nothing is logged, nothing is spoken, capture silently does not happen, and
# `ccw doctor` still calls the hook ok because registration is intact and
# doctor only asks whether a hook is REGISTERED, never whether it can EXECUTE.
# This makes annotations lazy strings, which costs nothing and removes the
# whole failure class. Measured 2026-09-07: with it, this file runs its full
# path under 3.9.6; without it, it dies at find_ccw's signature writing
# nothing. Pinned by tests/test_cc_capture_freshness.py's
# test_every_hook_defers_its_annotations.

from __future__ import annotations  # 3.9 safety: see the note at the end of this docstring

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOG = Path.home() / ".claude" / "logs" / "ccw-hook.log"
STATE_PATH = Path.home() / ".claude" / "logs" / "ccw-freshness-state.json"
VOICE_URL = "http://localhost:8888/notify"
VOICE_ID = "fTtv3eikoepIosk8dTZ5"

# The exact substring ccw doctor's `gap_line` (status.py:152) prints and
# tests/test_doctor_external_contract.py pins as a public contract. Shown as
# context only (R9); see the module docstring for why it does not drive the
# alarm.
_UNCAPTURED = re.compile(r"Uncaptured:\s*(\d+)\s*session")

# Tiers on the STREAK of consecutive broken doctor verdicts, not on the raw
# gap figure (see module docstring). 1 is "just happened, might self-heal by
# the next sweep"; a handful in a row means several session-starts have gone
# by broken; five or more matches the scale ticket 24's own incident reached
# (ten days of silence) before anyone noticed.
_WARN_AT = 2
_ALERT_AT = 5

# How long to let `ccw doctor` think before giving up on it. Doctor has to
# walk ~/.claude/projects to count uncaptured sessions, so its cost tracks the
# size of that tree, not the health of capture. Measured on the operator's
# machine 2026-09-07: 2.75s warm against 27,277 files / 4.2 GB - but it went
# over the previous 15s budget TWICE at 12:55 local, minutes after ccw-sweep
# wrote 486 archive folders and left the page cache cold, while capture itself
# was perfectly healthy (a session had been archived 24ms earlier). 45s is
# roughly 16x the warm figure and still well inside what a SessionStart hook
# can afford to block for. See the timeout handling in main(): going over this
# budget is now a streak, not an alarm.
_DOCTOR_TIMEOUT = 45

# Per `launchctl print` call in broken_jobs(). Measured 2026-09-07: all three
# calls together return in 0.03s, because launchctl is local IPC and never
# touches the projects tree the way `ccw doctor` does. 2s is ~66x that. It was
# 5s, which cost nothing while the timeout path still returned early and never
# reached these calls; it does now, so this budget stacks on _DOCTOR_TIMEOUT
# and has to fit under the outer kill with it (see the invariant test named in
# the comment below).
_JOB_TIMEOUT = 2

# THE INVARIANT BOTH NUMBERS ABOVE LIVE UNDER: Claude Code kills this whole
# process at the `timeout` declared for SessionStart in this plugin's own
# hooks.json, so _DOCTOR_TIMEOUT + 3 * _JOB_TIMEOUT must stay strictly under
# it, or the hard kill lands before the graceful except branch below and skips
# the "unreachable" log line, the streak write and broken_jobs() - the exact
# silent-early-exit shape the timeout fix exists to close. The two files
# cannot see each other, so the relationship is pinned by
# tests/test_cc_capture_freshness.py's
# test_the_freshness_hook_budgets_fit_inside_its_own_outer_kill.

# Watch the 3 real launchd background jobs `ccw doctor` never looks at at all
# (operator-approved follow-up, 2026-08-24). Real incident THIS closes: the
# weekly ccw-archive job silently failed every real session it touched for two
# weeks after a dependency it read was retired -- `ccw doctor`'s PASS/FAIL
# verdict never moved, because archive.migrate isn't part of what doctor
# checks. Nothing above this point in the file would ever have caught it.
_WATCHED_JOBS = (
    "com.captaincodeau.ccw-sweep",
    "com.captaincodeau.ccw-archive",
    "com.captaincodeau.ccw-repair",
)

# `launchctl print gui/<uid>/<label>`'s own wording, tab-indented, lowercase,
# unquoted (verified against real output on the operator's own machine
# 2026-08-24) -- a DIFFERENT format from `launchctl list`'s plist-style
# "LastExitStatus" = N; that an earlier draft of this file wrongly assumed.
_LAST_EXIT = re.compile(r"last exit code = (-?\d+)")

# Ticket 42 item #1: which statuses raise WHICH channel. Before this, only
# "error" spoke at all and nothing ever raised a desktop notification, so the
# WARN/ALERT tiers below -- the actual escalation mechanism ticket 24.7 was
# built for -- only ever reached a human as SessionStart stdout: pull-based,
# not push-based, which is why the 2026-09-09 incident needed a peer session
# to notice and relay it by hand. Desktop fires from WARN onward (streak 2+,
# _tier() 1); voice waits for ALERT (streak 5+, _tier() 2, the scale ticket
# 24's own incident reached) so an ordinary run of multi-session work --
# where two session starts can be minutes apart -- does not get talked over
# by every WARN. Deliberately excluded: the unlabelled tier-0 first miss
# (streak 1) is logged as its own "info" status in main() rather than
# collapsed into "warn" -- raising a desktop toast on the very first failed
# check, every time, would be the same "chronic figure trains you to ignore
# banners" trap ticket 24.7 exists to avoid, just moved one tier earlier.
# "error" (ccw not installed, a broken scheduled job) keeps speaking
# immediately, same as before this ticket -- there is no chronic, expected
# case for it the way the doctor-streak has one, so waiting for a streak
# would just delay a real one-shot problem.
_DESKTOP_STATUSES = frozenset({"warn", "alert", "error"})
_SPEAKING_STATUSES = frozenset({"alert", "error"})


def _desktop_alert(title: str, body: str) -> None:
    """Raise ONE desktop notification, best-effort. Ported by hand from
    src/cc_warehouse/notify.py's alert() (this file must not import
    cc_warehouse -- see the module docstring), same shape and same reason:
    fire-and-forget so a slow or missing `osascript` can never delay session
    start, and no new timeout is added to the budget this file already
    spends on `ccw doctor` and `launchctl` (see
    test_the_freshness_hook_budgets_fit_inside_its_own_outer_kill).

    macOS ONLY, and a no-op everywhere else rather than a guess -- this
    machine is a Mac, but this script also runs on whatever Linux box
    inherits the plugin (see the module's PORTABILITY note). Double quotes
    and backslashes in either string are escaped before being spliced into
    the AppleScript source, so a message containing a quote cannot end the
    string early and change what runs (same bug class notify.py's own
    docstring calls out)."""
    if sys.platform != "darwin":
        return
    safe_body = body.replace("\\", "\\\\").replace('"', '\\"')
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{safe_body}" with title "{safe_title}"'
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001 - a notification must never raise here
        pass


def report(status: str, detail: str) -> None:
    """Same idiom as ccw-hook.py's report(): log durably, then escalate by
    tier -- desktop from WARN, voice from ALERT (ticket 42 item #1; see the
    _DESKTOP_STATUSES/_SPEAKING_STATUSES comment above for why the two
    channels split there and not together)."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "ccw-freshness-check",
        # WHICH INTERPRETER RAN. These hooks do not choose their own: hooks.json
        # invokes them as a bare `python3` and the launch context's PATH decides.
        # Measured 2026-09-07: `zsh -lc` on this machine already resolves
        # /usr/bin/python3 3.9.6, which is what a launchd job or cron gets, while
        # the interactive PATH resolves something newer. uv ships only
        # version-suffixed shims (python3.12/.13/.14) and no bare `python3`, so
        # the deliberately chosen interpreter is the one this name cannot reach.
        # The code no longer CARES which one runs, but the log should still say,
        # because the incident that started all this was invisible in every
        # instrument. Removing a failure class and recording what happened are
        # two different jobs.
        "python": f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} {sys.executable}",
        "status": status,
        "detail": detail,
    }
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass
    if status in _DESKTOP_STATUSES:
        _desktop_alert("cc-warehouse", detail)
    if status not in _SPEAKING_STATUSES:
        return
    try:
        payload = json.dumps(
            {
                "message": f"cc-warehouse freshness check failed. {detail}",
                "voice_id": VOICE_ID,
                "voice_enabled": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            VOICE_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(request, timeout=3).close()
    except Exception:  # noqa: BLE001 - reporting is best effort by design
        pass


def find_ccw() -> str | None:
    """A real executable path, never a package name - see ccw-hook.py's own
    docstring for the incident this rule exists to not repeat."""
    override = os.environ.get("CCW_BIN")
    if override and Path(override).is_file():
        return override
    found = shutil.which("ccw")
    if found:
        return found
    shim = Path.home() / ".local" / "bin" / "ccw"
    return str(shim) if shim.is_file() else None


def extract_uncaptured(doctor_output: str) -> int | None:
    """The uncaptured-session count from a real `ccw doctor` report, or None if
    the report never printed the line (no archive configured, or doctor itself
    did not run). Context only - see module docstring for why this never
    drives the alarm on its own."""
    match = _UNCAPTURED.search(doctor_output)
    return int(match.group(1)) if match else None


def _read_state(path: Path) -> dict[str, object]:
    """The full state dict, or {} if missing/corrupt/unreadable - a corrupt
    state file must never crash the check (same posture as read_streak)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, updates: dict[str, object]) -> None:
    """Merge `updates` into whatever state already exists and write the whole
    thing back, tmp-then-replace so a crash mid-write cannot corrupt the file
    for the next session-start. READ-modify-write, not a blind overwrite: the
    streak and the backlog-growth snapshot share this one file, and a naive
    overwrite would let writing one erase the other."""
    try:
        state = _read_state(path)
        state.update(updates)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def read_streak(path: Path) -> int:
    """Consecutive broken doctor verdicts so far, or 0 if unknown, missing, or
    unreadable - a corrupt state file must never crash the check."""
    streak = _read_state(path).get("consecutive_broken", 0)
    return streak if isinstance(streak, int) and streak >= 0 else 0


def write_streak(path: Path, streak: int) -> None:
    _write_state(path, {"consecutive_broken": streak})


def read_backlog_snapshot(path: Path) -> tuple[int | None, str | None]:
    """(uncaptured count, ISO timestamp) from the LAST check that had a real
    figure to record, or (None, None) if this is the first check ever, or the
    state file is missing/corrupt."""
    state = _read_state(path)
    count = state.get("last_uncaptured")
    at = state.get("last_checked_at")
    return (
        count if isinstance(count, int) else None,
        at if isinstance(at, str) else None,
    )


def write_backlog_snapshot(path: Path, uncaptured: int | None, at: str) -> None:
    """Remember this check's figure for the NEXT check's rate comparison.
    Skipped entirely when `uncaptured` is None (doctor crashed before
    printing the line) - writing None here would silently corrupt the next
    rate calculation rather than just skip it, and the previous real snapshot
    is still a better comparison point than nothing."""
    if uncaptured is None:
        return
    _write_state(path, {"last_uncaptured": uncaptured, "last_checked_at": at})


def backlog_growth(
    prev_count: int | None, prev_at: str | None, current: int, now: datetime
) -> float | None:
    """Sessions-per-hour growth in the uncaptured backlog since the last
    check, or None if there is nothing to compare against (first-ever check,
    an unparseable earlier timestamp, or too little real time has passed for
    a rate to mean anything rather than a divide-by-near-zero artifact)."""
    if prev_count is None or prev_at is None:
        return None
    try:
        earlier = datetime.fromisoformat(prev_at)
    except ValueError:
        return None
    elapsed_hours = (now - earlier).total_seconds() / 3600
    if elapsed_hours <= 0.01:  # under ~36s
        return None
    return (current - prev_count) / elapsed_hours


def growth_context(rate: float | None) -> str:
    """A short informational suffix naming the backlog's growth rate, or ''
    when there is nothing worth adding (no earlier snapshot, flat, or
    shrinking - good news is not context to flag). CONTEXT ONLY, appended to
    an ALREADY-escalating message in main() - never itself the reason to
    speak, for the exact false-alarm reason freshness_message's own docstring
    gives for the raw uncaptured count: this session's own real numbers show
    ordinary multi-session usage can produce a rate (37 in ~2h, ~18/hr) not
    reliably distinguishable from a real problem by rate alone."""
    if rate is None or rate <= 0:
        return ""
    return f", growing ~{rate:.0f}/hr since last check"


def extract_last_exit(launchctl_output: str) -> int | None:
    """The job's own last-exit-code, from a real `launchctl print` report, or
    None if the line was never printed (the job has never run yet, or
    launchctl's own output format changed under us) -- unknown is not the
    same as healthy, callers must not treat it as 0."""
    match = _LAST_EXIT.search(launchctl_output)
    return int(match.group(1)) if match else None


def _job_last_exit(label: str) -> int | None:
    """Ask launchctl about one job, best-effort. None on ANY failure to check
    at all (launchctl missing -- e.g. not macOS, the job not loaded, a hung
    call) -- this must never block or fail session start, same posture as the
    `ccw doctor` subprocess call below."""
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=_JOB_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return extract_last_exit(result.stdout)


def broken_jobs() -> list[tuple[str, int]]:
    """Every watched job whose last known run did NOT exit 0. A job that has
    never run yet, or that launchctl could not be asked about, is not
    reported broken -- absence of evidence is not evidence of failure here,
    the same conservative posture `ccw doctor` already takes on its own
    uncaptured-count line."""
    broken: list[tuple[str, int]] = []
    for label in _WATCHED_JOBS:
        code = _job_last_exit(label)
        if code is not None and code != 0:
            broken.append((label, code))
    return broken


def job_health_message(broken: list[tuple[str, int]]) -> str | None:
    """The line to print/report for broken scheduled jobs, or None if none are
    broken. Unlike the doctor-streak message, this never needs a streak of its
    own: a nonzero exit code is ALWAYS a real problem (there is no chronic,
    expected-nonzero case the way the raw uncaptured count has one), so firing
    plainly every session-start until it is fixed IS the correct escalating-
    then-clearing behaviour, not a false-alarm risk."""
    if not broken:
        return None
    named = ", ".join(f"{label} (exit {code})" for label, code in broken)
    return f"cc-warehouse: scheduled job failing: {named}. Check its log under ~/.claude/logs/."


def _tier(streak: int) -> int:
    """Which escalation tier a streak falls in: 0 mild, 1 WARNING, 2 ALERT.
    One definition, shared by every kind of trouble this script reports, so
    the boundaries can never drift apart per-case (caught in review
    2026-09-07, when the unreachable-doctor wording arrived with its own
    copy-pasted ladder over the same two constants)."""
    if streak < _WARN_AT:
        return 0
    if streak < _ALERT_AT:
        return 1
    return 2


def freshness_message(
    streak: int, uncaptured: int | None, unreachable: str | None = None
) -> str | None:
    """The escalating line to print, or None to stay quiet.

    Streak 0 (doctor healthy) stays silent no matter how large the chronic
    backlog is: this signal clears the moment the real problem is fixed, not
    merely once it has been seen (ticket 24.7).

    `unreachable` names why `ccw doctor` could not be ASKED at all - a
    timeout, an OSError, any SubprocessError. It changes the WORDING only,
    never the tiering. A probe that got no answer produced no verdict, so it
    must not be reported as "capture failed": on the 2026-09-07 incident that
    made this parameter exist, capture was working perfectly and had archived
    a session 24ms earlier, while doctor merely lost a race against a sweep
    that had just written 486 archive folders. It DOES share the same streak,
    because a doctor nobody can reach for five session-starts running is a
    real problem, and the branch this replaced could never say so - it never
    touched the counter, so it shouted one flat line forever and never
    escalated (operator-approved fix, 2026-09-07).

    The uncaptured figure is deliberately left out of the unreachable wording:
    doctor never printed the line, so it is always "count unknown" there, and
    a phrase that can only ever say "unknown" is noise on an alert."""
    if streak <= 0:
        return None
    tier = _tier(streak)
    if unreachable is not None:
        subject = f"could not check capture ({unreachable})"
        return (
            f"cc-warehouse: {subject}. Capture may well be fine; the check got "
            f"no answer. Run `ccw doctor`.",
            f"cc-warehouse: WARNING - {subject}, {streak} session-starts in a "
            f"row. Run `ccw doctor`.",
            f"cc-warehouse: ALERT - {subject}, {streak} session-starts in a row. "
            f"`ccw doctor` has not answered once. Run it by hand now.",
        )[tier]
    detail = f"{uncaptured} uncaptured" if uncaptured is not None else "count unknown"
    return (
        f"cc-warehouse: capture check failed ({detail}). Run `ccw doctor`.",
        f"cc-warehouse: WARNING - capture check has failed {streak} times in a row "
        f"({detail}). Run `ccw doctor`.",
        f"cc-warehouse: ALERT - capture has been broken for {streak} session-starts in a "
        f"row ({detail}). Run `ccw doctor` now.",
    )[tier]


def main() -> int:
    if os.environ.get("CCW_SKIP_HOOK") == "1":
        report("skipped", "CCW_SKIP_HOOK=1")
        return 0

    executable = find_ccw()
    if executable is None:
        report("error", "ccw is not installed; freshness check skipped")
        return 0

    # A doctor that could not be ASKED and a doctor that answered FAIL are
    # different facts, but they share one property: neither is evidence that
    # capture is healthy. So both fall through to the same streak below.
    # They used to not: the except branch spoke immediately (before ticket 42
    # item #1, "error" was the only status report() ever said out loud) and
    # then `return 0`-ed, which never touched the streak counter AND skipped
    # broken_jobs() entirely. One slow moment therefore shouted a raw Python
    # traceback, while a permanently unreachable doctor could never escalate
    # past that same flat line. Fixed 2026-09-07 after both halves fired for
    # real. "unreachable" itself still stays off _DESKTOP_STATUSES/
    # _SPEAKING_STATUSES on purpose: it means the check got no answer, not
    # that capture failed (see freshness_message's own docstring), so it logs
    # durably and lets the streak below carry the actual escalation.
    result: subprocess.CompletedProcess[str] | None = None
    unreachable: str | None = None
    try:
        result = subprocess.run(
            [executable, "doctor"],
            capture_output=True,
            text=True,
            timeout=_DOCTOR_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        unreachable = type(exc).__name__
        # Keep the full detail durably in the log, at a status report() does
        # not speak, so nothing this branch used to record is lost. The short
        # type name is what rides along in the banner message below.
        report(
            "unreachable",
            f"{executable} doctor did not answer: {type(exc).__name__}: {exc}",
        )

    uncaptured = extract_uncaptured(result.stdout) if result is not None else None
    now = datetime.now(timezone.utc)
    prev_count, prev_at = read_backlog_snapshot(STATE_PATH)
    rate = backlog_growth(prev_count, prev_at, uncaptured, now) if uncaptured is not None else None

    if result is not None and result.returncode == 0:
        write_streak(STATE_PATH, 0)
        report("ok", f"uncaptured={uncaptured}")
    else:
        streak = read_streak(STATE_PATH) + 1
        write_streak(STATE_PATH, streak)
        message = freshness_message(streak, uncaptured, unreachable)
        if message is not None:
            message += growth_context(rate)
            # Ticket 42 item #1: the report STATUS must track _tier(), not just
            # "below/at _ALERT_AT" - streak 1 is tier 0, the unlabelled first
            # miss, and must stay as quiet on the new desktop channel as it
            # already was on voice. Collapsing tier 0 into "warn" here (the
            # pre-ticket-42 shape) would have raised a desktop notification on
            # the very first failed check, every time - the same "chronic
            # figure trains you to ignore banners" trap ticket 24.7 exists to
            # avoid, just moved a tier earlier. "info" is a new log status,
            # deliberately outside _DESKTOP_STATUSES/_SPEAKING_STATUSES; no
            # test or external consumer keys on the old "warn"-at-tier-0 value
            # (checked: ccw-watch and this plugin's docs key on `ccw doctor`'s
            # own exit code, never on this file's log status strings).
            report(("info", "warn", "alert")[_tier(streak)], message)
            print(message)

    write_backlog_snapshot(STATE_PATH, uncaptured, now.isoformat())

    # Independent of the doctor-streak signal above (see job_health_message's
    # own docstring for why): `ccw doctor` does not check these jobs at all,
    # so this is the only place that would ever have caught the real archive-
    # job incident this exists to close. Best-effort, guarded the same way as
    # everything above: must never block or fail session start.
    try:
        job_message = job_health_message(broken_jobs())
    except Exception:  # noqa: BLE001 - see main()'s own top-level guard below
        job_message = None
    if job_message is not None:
        report("error", job_message)
        print(job_message)
    return 0


if __name__ == "__main__":
    # SessionStart hooks must never fail session start; everything above already
    # returns 0, this is the backstop for anything unforeseen.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        report("error", f"freshness check crashed: {type(exc).__name__}: {exc}")
        sys.exit(0)
