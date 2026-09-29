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
how LONG that verdict has been broken, a "broken since" time persisted in a
state file next to the hook log. The raw uncaptured figure still rides along
in the message as context; it just does not decide whether to speak at all.

TIME, NOT COUNT, AND IN THE BACKGROUND (rulings, Gavin, 2026-09-29, open item
W-20260929-A93). This used to escalate on how many CONSECUTIVE session-starts
had seen a broken verdict. That counted how busy the operator was, not how
long capture had been down: at 01:45:19 and 01:45:24 two sessions started
five seconds apart, each ran its own doctor against the share, and one bad
moment became a WARNING. Now the first failed check stamps `broken_since`,
every later failed check measures from it, and the first healthy check
clears it. The hook also runs with `"async": true` in hooks.json, so a
session start never waits on doctor, and a kernel `flock` makes several
panes starting together run ONE doctor; the others reuse its last verdict.
What async changes (Claude Code's own docs, code.claude.com/docs/en/hooks,
and the installed 2.1.284 binary, checked 2026-09-29): plain stdout of an
async hook is DROPPED, only a JSON `hookSpecificOutput.additionalContext`
reaches the model, on its next turn, never the screen; and Claude Code does
not enforce the hook's `timeout`. So this script prints JSON, bounds itself,
and anything a human must hear goes through report()'s desktop and voice.

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

try:  # POSIX only. Without it the check still runs, just unlocked.
    import fcntl
except ImportError:  # Windows never runs this plugin; kept importable anyway
    fcntl = None  # type: ignore[assignment]

LOG = Path.home() / ".claude" / "logs" / "ccw-hook.log"
STATE_PATH = Path.home() / ".claude" / "logs" / "ccw-freshness-state.json"
LOCK_PATH = Path.home() / ".claude" / "logs" / "ccw-freshness.lock"
VOICE_URL = "http://localhost:8888/notify"
VOICE_ID = "fTtv3eikoepIosk8dTZ5"

# The exact substring ccw doctor's `gap_line` (status.py:152) prints and
# tests/test_doctor_external_contract.py pins as a public contract. Shown as
# context only (R9); see the module docstring for why it does not drive the
# alarm.
_UNCAPTURED = re.compile(r"Uncaptured:\s*(\d+)\s*session")

# Tiers on how LONG capture has been continuously broken, not on the raw gap
# figure (see module docstring) and no longer on a count of session starts.
# Picked 2026-09-29 against the real log: across 1,293 checks, two session
# starts sit a median 2.9 minutes apart, and five span a median 40 minutes
# (p75 92). So the old WARN at 2 starts fired about 3 minutes into a problem
# and ALERT at 5 about 40 minutes in, and a burst of panes compressed both.
# 30 minutes outlasts every transient doctor already knows how to excuse (the
# 120 s capture grace, the 300 s per-step pipeline ceiling), so a desktop
# alert means the problem survived all of them. 2 hours sits just past the
# p75 span of five starts, so the spoken ALERT lands no later than it did on
# an ordinary day, while a burst of panes can no longer bring it forward.
# The clock is wall time and includes sleep: a failure seen before the lid
# closed and again after it opened has persisted, it is not a blip.
_WARN_AFTER_S = 30 * 60
_ALERT_AFTER_S = 2 * 60 * 60

# A check holding the lock longer than this is hung, not slow: a normal one
# is bounded by _DOCTOR_TIMEOUT plus the launchctl calls, under a minute. A
# pane that finds the lock held this long stops quietly reusing the last
# verdict and reports an unanswered check, timed from when the hung one
# began, so a doctor stuck on the share can never keep the alarm quiet.
_HUNG_AFTER_S = 5 * 60

# How long to let `ccw doctor` think before giving up on it. Doctor has to
# walk ~/.claude/projects to count uncaptured sessions, so its cost tracks the
# size of that tree, not the health of capture. Measured on the operator's
# machine 2026-09-07: 2.75s warm against 27,277 files / 4.2 GB - but it went
# over the previous 15s budget TWICE at 12:55 local, minutes after ccw-sweep
# wrote 486 archive folders and left the page cache cold, while capture itself
# was perfectly healthy (a session had been archived 24ms earlier). 45s is
# roughly 16x the warm figure. See the timeout handling in main(): going over
# this budget starts the broken clock, it does not raise an alarm on its own.
# Since the hook became async (2026-09-29) this is the ONLY bound on a doctor
# run, because Claude Code does not enforce `timeout` on an async hook.
_DOCTOR_TIMEOUT = 45

# Per `launchctl print` call in broken_jobs(). Measured 2026-09-07: all three
# calls together return in 0.03s, because launchctl is local IPC and never
# touches the projects tree the way `ccw doctor` does. 2s is ~66x that. It was
# 5s, which cost nothing while the timeout path still returned early and never
# reached these calls; it does now, so this budget stacks on _DOCTOR_TIMEOUT
# and has to fit under the outer kill with it (see the invariant test named in
# the comment below).
_JOB_TIMEOUT = 2

# THE INVARIANT BOTH NUMBERS ABOVE LIVE UNDER: when this hook runs in the
# foreground (a Claude Code that predates or ignores `"async": true`), Claude
# Code kills the whole process at the `timeout` declared for SessionStart in
# this plugin's own hooks.json, so _DOCTOR_TIMEOUT + 3 * _JOB_TIMEOUT must
# stay strictly under it, or the hard kill lands before the graceful except
# branch below and skips the "unreachable" log line, the state write and
# broken_jobs() - the exact
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
# to notice and relay it by hand. Desktop fires from WARN onward (broken 30
# minutes, _tier() 1); voice waits for ALERT (broken 2 hours, _tier() 2) so a
# problem that is still resolving does not get talked over. Since the hook
# became async (2026-09-29) these two channels are the ONLY ones that reach
# the human at all: the session's copy goes to the model, not the screen.
# Deliberately excluded: the unlabelled tier-0 first half hour is logged as
# its own "info" status in main() rather than
# collapsed into "warn" -- raising a desktop toast on the very first failed
# check, every time, would be the same "chronic figure trains you to ignore
# banners" trap ticket 24.7 exists to avoid, just moved one tier earlier.
# "error" (ccw not installed, a broken scheduled job) keeps speaking
# immediately, same as before this ticket -- there is no chronic, expected
# case for it the way the doctor verdict has one, so waiting on a clock
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
    # See ccw-hook.py's own find_ccw() for the incident (ticket 41 Finding 1,
    # confirmed live 2026-09-09) - a `.venv` hit is this repo's own editable
    # dev checkout and must fall through to the frozen shim instead.
    if found and "/.venv/" not in found:
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


def _now() -> datetime:
    """The one clock this script reads, so tests can move it."""
    return datetime.now(timezone.utc)


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _load_state(path: Path) -> tuple[dict[str, object], bool]:
    """(state, lost). `lost` is True when the file EXISTS but cannot be read
    as a JSON object: the broken period's start time is gone, and the caller
    must fail toward alerting rather than restart the clock (edge case 2). A
    MISSING file is not lost: it is the first check on this machine."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, False
    except OSError:
        return {}, True
    try:
        data = json.loads(text)
    except ValueError:
        return {}, True
    return (data, False) if isinstance(data, dict) else ({}, True)


def _read_state(path: Path) -> dict[str, object]:
    """The full state dict, or {} if missing/corrupt/unreadable - a corrupt
    state file must never crash the check."""
    return _load_state(path)[0]


def _write_state(path: Path, updates: dict[str, object], drop: tuple[str, ...] = ()) -> bool:
    """Merge `updates` into whatever state already exists and write the whole
    thing back, tmp-then-replace so a crash mid-write cannot corrupt the file
    for the next session-start. READ-modify-write, not a blind overwrite: the
    broken clock and the backlog-growth snapshot share this one file, and a
    naive overwrite would let writing one erase the other. Returns False when
    the write did not land, because a clock that cannot be saved restarts on
    every check and would never escalate: the caller treats that as an alarm.
    Only the lock holder writes (R14); a pane that finds the lock held never
    calls this."""
    try:
        state = _read_state(path)
        state.update(updates)
        for key in drop:
            state.pop(key, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True


def carried_broken_since(state: dict[str, object]) -> datetime | None:
    """When the current broken period began, as far as the state file can
    say, or None when the last recorded check was healthy (or there is none).

    Three sources, in order:
    - `broken_since`, stamped by the first failed check of this period;
    - a check that STARTED and never recorded a verdict (killed mid-doctor,
      or its doctor hung past its holder's life): it got no answer, so the
      period began when it started;
    - a state file from before 2026-09-29, which kept a count. A count of 1 or
      more means the previous check failed, and `last_checked_at` is when that
      check ran, so the period began no later than that. Read once: the first
      new-style write drops the count."""
    since = _parse_ts(state.get("broken_since"))
    if since is not None:
        return since
    started = _parse_ts(state.get("check_started_at"))
    verdict_at = _parse_ts(state.get("last_verdict_at"))
    if started is not None and (verdict_at is None or verdict_at < started):
        return started
    count = state.get("consecutive_broken")
    if "broken_since" not in state and isinstance(count, int) and count >= 1:
        return _parse_ts(state.get("last_checked_at"))
    return None


def _try_lock(path: Path, now: datetime) -> tuple[int | None, bool]:
    """(fd, contended). Take the check lock without waiting.

    A kernel `flock`, never a pid file: it is released when the last process
    holding the open file exits, however it exits, so a dead holder can never
    leave it stuck (edge case 4, the W-20260929-A84 class of trusting a pid
    forever). The fd is passed to the doctor child, so a doctor that outlives
    a killed hook keeps the lock and no second doctor starts beside it (edge
    case 3). The file's mtime records when the holder started, for panes that
    find it held; the pid written into it is for a human reading it, and
    nothing here trusts it.

    Any failure to lock that is NOT "someone else holds it" returns
    (None, False): run the check unlocked rather than skip it."""
    if fcntl is None:
        return None, False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None, False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None, True
    except OSError:
        os.close(fd)
        return None, False
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {now.isoformat(timespec='seconds')}\n".encode("utf-8"))
        os.utime(str(path), (now.timestamp(), now.timestamp()))
    except OSError:
        pass
    return fd, False


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
    broken. Unlike the doctor-verdict message, this never needs a clock of its
    own: a nonzero exit code is ALWAYS a real problem (there is no chronic,
    expected-nonzero case the way the raw uncaptured count has one), so firing
    plainly every session-start until it is fixed IS the correct escalating-
    then-clearing behaviour, not a false-alarm risk."""
    if not broken:
        return None
    named = ", ".join(f"{label} (exit {code})" for label, code in broken)
    return f"cc-warehouse: scheduled job failing: {named}. Check its log under ~/.claude/logs/."


def _tier(broken_for_s: float) -> int:
    """Which escalation tier a broken period falls in: 0 mild, 1 WARNING, 2
    ALERT. One definition, shared by every kind of trouble this script
    reports, so the boundaries can never drift apart per-case (caught in
    review 2026-09-07, when the unreachable-doctor wording arrived with its
    own copy-pasted ladder over the same two constants)."""
    if broken_for_s < _WARN_AFTER_S:
        return 0
    if broken_for_s < _ALERT_AFTER_S:
        return 1
    return 2


def _duration(seconds: float) -> str:
    """Short human wording for a broken period: "under a minute", "47 min",
    "3 h 5 min"."""
    minutes = int(max(0.0, seconds) // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 120:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def freshness_message(
    broken_for_s: float | None,
    uncaptured: int | None,
    unreachable: str | None = None,
    floor: int = 0,
) -> str | None:
    """The escalating line to print, or None to stay quiet.

    `broken_for_s` None (doctor healthy) stays silent no matter how large the
    chronic backlog is: this signal clears the moment the real problem is
    fixed, not merely once it has been seen (ticket 24.7). Otherwise it is how
    long capture has been continuously broken, and picks the tier. `floor`
    raises the tier when the clock itself cannot be trusted (a lost or
    unwritable state file), never lowers it.

    `unreachable` names why `ccw doctor` could not be ASKED at all - a
    timeout, an OSError, any SubprocessError, a hung check. It changes the
    WORDING only, never the tiering. A probe that got no answer produced no
    verdict, so it must not be reported as "capture failed": on the
    2026-09-07 incident that made this parameter exist, capture was working
    perfectly and had archived a session 24ms earlier, while doctor merely
    lost a race against a sweep that had just written 486 archive folders. It
    DOES run the same clock, because a doctor nobody can reach for hours is a
    real problem (operator-approved fix, 2026-09-07).

    The uncaptured figure is deliberately left out of the unreachable wording:
    doctor never printed the line, so it is always "count unknown" there, and
    a phrase that can only ever say "unknown" is noise on an alert."""
    if broken_for_s is None:
        return None
    tier = max(_tier(broken_for_s), floor)
    lasted = _duration(broken_for_s)
    if unreachable is not None:
        subject = f"could not check capture ({unreachable})"
        return (
            f"cc-warehouse: {subject}. Capture may well be fine; the check got "
            f"no answer. Run `ccw doctor`.",
            f"cc-warehouse: WARNING - {subject}, no answer for {lasted}. "
            f"Run `ccw doctor`.",
            f"cc-warehouse: ALERT - {subject}, no answer for {lasted}. "
            f"Run `ccw doctor` by hand now.",
        )[tier]
    detail = f"{uncaptured} uncaptured" if uncaptured is not None else "count unknown"
    return (
        f"cc-warehouse: capture check failed ({detail}), first seen {lasted} ago. "
        f"Run `ccw doctor`.",
        f"cc-warehouse: WARNING - capture check has been failing for {lasted} "
        f"({detail}). Run `ccw doctor`.",
        f"cc-warehouse: ALERT - capture has been broken for {lasted} "
        f"({detail}). Run `ccw doctor` now.",
    )[tier]


def _emit(lines: list[str]) -> None:
    """Hand the session its lines the one way an async hook can: a JSON
    `additionalContext`, which Claude Code delivers to the MODEL on its next
    turn and never shows on screen (code.claude.com/docs/en/hooks, "Async
    hooks"). Plain stdout from an async hook is dropped. A foreground run
    (an older Claude Code) reads the same JSON. Nothing is printed when all
    is well, so a healthy check adds nothing to the session."""
    if not lines:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n".join(lines),
                }
            }
        )
    )


def _reuse(now: datetime) -> int:
    """Another pane holds the lock, so its doctor is running now. Reuse the
    last recorded verdict and write nothing (only the holder writes, R14).
    One exception: a lock held past _HUNG_AFTER_S means that check is hung,
    and quietly reusing an old verdict would hide it, so this reports an
    unanswered check timed from when the hung one began."""
    state = _read_state(STATE_PATH)
    try:
        held_since = datetime.fromtimestamp(LOCK_PATH.stat().st_mtime, timezone.utc)
    except OSError:
        held_since = now
    held_for = (now - held_since).total_seconds()
    if held_for > _HUNG_AFTER_S:
        carried = carried_broken_since(state)
        since = min(carried, held_since) if carried is not None else held_since
        broken_for = max(0.0, (now - since).total_seconds())
        message = freshness_message(
            broken_for,
            None,
            unreachable=f"a check started {_duration(held_for)} ago has not answered",
        )
        report(("info", "warn", "alert")[_tier(broken_for)], message or "")
        _emit([message] if message else [])
        return 0
    last = state.get("last_verdict")
    report(
        "reused",
        f"another session's check started {int(max(0.0, held_for))}s ago; "
        f"last verdict {last} at {state.get('last_verdict_at')}",
    )
    message = state.get("last_message")
    if last != "ok" and isinstance(message, str) and message:
        _emit([message])
    return 0


def main() -> int:
    if os.environ.get("CCW_SKIP_HOOK") == "1":
        report("skipped", "CCW_SKIP_HOOK=1")
        return 0

    executable = find_ccw()
    if executable is None:
        report("error", "ccw is not installed; freshness check skipped")
        return 0

    started = _now()
    lock_fd, contended = _try_lock(LOCK_PATH, started)
    if contended:
        return _reuse(started)
    try:
        return _check(executable, started, lock_fd)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def _check(executable: str, started: datetime, lock_fd: int | None) -> int:
    prev, lost = _load_state(STATE_PATH)
    carried = carried_broken_since(prev)
    # A readable file whose start time is garbled has lost the clock too.
    if prev.get("broken_since") is not None and _parse_ts(prev.get("broken_since")) is None:
        lost = True
    saved = _write_state(STATE_PATH, {"check_started_at": started.isoformat()})

    # A doctor that could not be ASKED and a doctor that answered FAIL are
    # different facts, but they share one property: neither is evidence that
    # capture is healthy. So both run the same broken clock below.
    # They used to not: the except branch spoke immediately (before ticket 42
    # item #1, "error" was the only status report() ever said out loud) and
    # then `return 0`-ed, which never touched the counter AND skipped
    # broken_jobs() entirely. One slow moment therefore shouted a raw Python
    # traceback, while a permanently unreachable doctor could never escalate
    # past that same flat line. Fixed 2026-09-07 after both halves fired for
    # real. "unreachable" itself still stays off _DESKTOP_STATUSES/
    # _SPEAKING_STATUSES on purpose: it means the check got no answer, not
    # that capture failed (see freshness_message's own docstring), so it logs
    # durably and lets the clock below carry the actual escalation.
    result: subprocess.CompletedProcess[str] | None = None
    unreachable: str | None = None
    try:
        result = subprocess.run(
            [executable, "doctor"],
            capture_output=True,
            text=True,
            timeout=_DOCTOR_TIMEOUT,
            check=False,
            # The doctor child holds the lock too, so if this hook dies first
            # a still-running doctor keeps later panes from starting another.
            pass_fds=(lock_fd,) if lock_fd is not None else (),
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
    now = _now()
    prev_count, prev_at = read_backlog_snapshot(STATE_PATH)
    rate = backlog_growth(prev_count, prev_at, uncaptured, now) if uncaptured is not None else None
    lines: list[str] = []

    if result is not None and result.returncode == 0:
        _write_state(
            STATE_PATH,
            {
                "broken_since": None,
                "last_verdict": "ok",
                "last_verdict_at": now.isoformat(),
                "last_message": None,
            },
            drop=("consecutive_broken",),
        )
        report("ok", f"uncaptured={uncaptured}")
    else:
        since = carried if carried is not None else started
        broken_for = max(0.0, (now - since).total_seconds())
        saved = (
            _write_state(
                STATE_PATH,
                {
                    "broken_since": since.isoformat(),
                    "last_verdict": "unreachable" if unreachable else "fail",
                    "last_verdict_at": now.isoformat(),
                },
                drop=("consecutive_broken",),
            )
            and saved
        )
        # Edge case 2: a clock that was lost, or cannot be saved, would
        # restart at zero on every check and never escalate. Fail toward
        # alerting: at least a WARNING, and say why.
        floor = 1 if (lost or not saved) else 0
        message = freshness_message(broken_for, uncaptured, unreachable, floor=floor)
        message = message or ""
        if floor:
            message += " (The freshness state file could not be read or written, so how long is unknown.)"
        message += growth_context(rate)
        _write_state(STATE_PATH, {"last_message": message})
        # Ticket 42 item #1: the report STATUS tracks the tier. Tier 0, the
        # first half hour, is "info": logged and handed to the session, never
        # a desktop toast, or a blip would train the reader to ignore banners
        # (the ticket 24.7 lesson). No external consumer keys on these log
        # status strings (checked: ccw-watch and this plugin's docs key on
        # `ccw doctor`'s own exit code).
        report(("info", "warn", "alert")[max(_tier(broken_for), floor)], message)
        lines.append(message)

    write_backlog_snapshot(STATE_PATH, uncaptured, now.isoformat())

    # Independent of the broken clock above (see job_health_message's own
    # docstring for why): `ccw doctor` does not check these jobs at all, so
    # this is the only place that would ever have caught the real archive-
    # job incident this exists to close. Only the lock holder asks, so a
    # burst of panes speaks a broken job once, not once per pane.
    try:
        job_message = job_health_message(broken_jobs())
    except Exception:  # noqa: BLE001 - see the top-level guard below
        job_message = None
    if job_message is not None:
        report("error", job_message)
        lines.append(job_message)
    _emit(lines)
    return 0


if __name__ == "__main__":
    # SessionStart hooks must never fail session start; everything above already
    # returns 0, this is the backstop for anything unforeseen.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        report("error", f"freshness check crashed: {type(exc).__name__}: {exc}")
        sys.exit(0)
