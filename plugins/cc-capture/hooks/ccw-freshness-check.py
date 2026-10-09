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

SENT BACK THE SAME DAY (review of 9383200; ruling: Gavin, "send back, keep
the background hook"). Four rules, each proved wrong in a sandbox first:
- Only a real broken verdict from doctor opens or extends an outage. A
  check that got no answer (timeout, hang, or killed: `claude -p` kills
  async hooks at teardown) is UNKNOWN: logged and handed to the session,
  never counted.
- An outage is only as long as its evidence: a failing check continues it
  only if the previous failing check is under _CONTINUITY_S old.
- Each tier raises its desktop/voice channel ONCE per outage, deduplicated
  in the state file, and only the lock holder ever raises anything.
- Failing launchd jobs, and archive folders `ccw repair` refuses to
  re-render (read from its one `repair-summary` log line per run), run the
  same clock with their own dedup instead of speaking at every start.

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
from datetime import datetime, timedelta, timezone
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

# doctor's `config` line, f"root={config.root} archive_root={config.archive_root}"
# (src/cc_warehouse/doctor.py). The one source for the warehouse root here
# (ruling 2026-09-29: never re-read config.toml by hand, R9). Lazy up to the
# fixed " archive_root=" that always follows, so a root with a space survives.
_CONFIG_ROOT = re.compile(r"^\s*\S+\s+config\s+root=(.+?) archive_root=", re.M)

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
_WARN_AFTER_S = 30 * 60
_ALERT_AFTER_S = 2 * 60 * 60

# AN OUTAGE IS ONLY AS LONG AS ITS EVIDENCE (sent back 2026-09-29; the review
# proved a Friday blip and a Monday blip, 64 h apart with no check between,
# read as one 64 h outage and spoke). A failing check continues the current
# outage only if the previous FAILING check is at most this old; otherwise it
# opens a new one. An hour is about the p90 gap between session starts (56
# minutes in the same log), so a real outage during working hours is re-seen
# well inside it, and a night, a weekend or a sleep with no check between
# restarts the clock. Because it is under _ALERT_AFTER_S, two failures can
# never span the ALERT threshold by themselves: a spoken alert always rests on
# three or more failing checks. What it gives up: an outage checked less than
# hourly never escalates past its first half hour; each check still logs it
# and hands it to the session.
_CONTINUITY_S = 60 * 60

# A check holding the lock longer than this is hung, not slow: a normal one
# is bounded by _DOCTOR_TIMEOUT plus the launchctl calls, under a minute. A
# pane that finds the lock held this long logs an UNANSWERED check (unknown,
# never an alarm: sent back 2026-09-29) rather than quietly reusing the last
# verdict as if a fresh check were under way.
_HUNG_AFTER_S = 5 * 60

# `ccw repair` raises its own one-time alert when it finds a NEW refusal. A
# reminder from this hook within this long of repair's summary line would
# speak twice about one run, so it waits for the next check. Deferred, never
# dropped: the tier is not recorded as alerted until it actually alerts.
_REPAIR_QUIET_S = 10 * 60

# Unanswered checks never open an outage (above), but a doctor that NEVER
# answers must not be silent forever either. Ruling 2026-09-29 (Gavin, option
# ii): once unanswered checks have run unbroken this long, with no real
# verdict between them and no gap over _CONTINUITY_S, raise ONE desktop-only
# notice. Never voice, never a capture-broken outage; any real verdict resets
# it. SessionEnd capture still reports its own failures loudly, which is why
# desktop is enough here.
_UNKNOWN_NOTICE_S = 2 * 60 * 60

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

# Per `launchctl print` call in job_reports(), ONE call per job: the exit code
# and the log path come from the same report (W-20261010-A12). Measured 2026-09-07: all three
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
# branch below and skips the "unknown" log line, the state write and
# the job check - the exact
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
# The same report's log line, e.g. "stdout path = /.../launch-agents/logs/ccw-sweep.log".
# The jobs' logs moved out of ~/.claude/logs/ on 2026-10-10, so the hook reads
# where each job really writes rather than naming a folder (W-20261010-A12).
_LOG_PATH = re.compile(r"^\s*(stdout|stderr) path = (.+?)\s*$", re.MULTILINE)
# The same report's top-level state, "state = running" while the job runs. A
# running sweep still shows the PREVIOUS run's exit code, so the hook must not
# read that code as today's run (review of 71d5aec, 2026-10-10).
_STATE = re.compile(r"^\tstate = (.+?)\s*$", re.MULTILINE)

# How recent a finished sweep must be to explain the job's exit code: one daily
# run plus slack. Older, and the job has missed a run, so it is failing to run.
_FINISHED_RUN_MAX_AGE = timedelta(hours=26)

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
_DESKTOP_STATUSES = frozenset({"warn", "alert", "error", "unknown-notice"})
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


def report(status: str, detail: str, notify: bool = True) -> None:
    """Same idiom as ccw-hook.py's report(): log durably, then escalate by
    tier -- desktop from WARN, voice from ALERT (ticket 42 item #1; see the
    _DESKTOP_STATUSES/_SPEAKING_STATUSES comment above for why the two
    channels split there and not together). `notify=False` logs at the same
    status without raising anything: the tier was already alerted in this
    outage (one alert per tier per outage, sent back 2026-09-29)."""
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
    if not notify:
        return
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


def carried_broken_since(state: dict[str, object], now: datetime) -> datetime | None:
    """When the outage still running at `now` began, or None when there is
    none to carry (the last real verdict was healthy, there is no record, or
    the last failing check is older than _CONTINUITY_S).

    Only a real broken verdict from doctor ever counts. A check that started
    and never answered (killed, hung, timed out) is unknown and neither opens
    nor extends an outage: `claude -p` kills async hooks at teardown, and
    trusting such a start is how the review turned one blip into a spoken
    ALERT (sent back 2026-09-29).

    A state file from before 2026-09-29 kept a count. A count of 1 or more
    means the previous check failed at `last_checked_at`, so that is carried
    as both the start and the last failure, under the same continuity rule.
    Read once: the first new-style write drops the count."""
    since = _parse_ts(state.get("broken_since"))
    last_fail = _parse_ts(state.get("last_fail_at"))
    count = state.get("consecutive_broken")
    if since is None and "broken_since" not in state and isinstance(count, int) and count >= 1:
        since = last_fail = _parse_ts(state.get("last_checked_at"))
    if since is None or last_fail is None:
        return None
    if (now - last_fail).total_seconds() > _CONTINUITY_S:
        return None
    return since


def _alerted(entry: object) -> int:
    """The highest tier already alerted for one outage record, 0 if none."""
    if isinstance(entry, dict):
        tier = entry.get("alerted_tier")
        if isinstance(tier, int):
            return tier
    return 0


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


def extract_log_path(launchctl_output: str) -> str | None:
    """The job's log from a `launchctl print` report: its stdout path, else
    its stderr path, never /dev/null; None when the report names neither."""
    paths = {
        kind: path
        for kind, path in reversed(_LOG_PATH.findall(launchctl_output))
        if path != "/dev/null"
    }
    return paths.get("stdout") or paths.get("stderr")


def extract_running(launchctl_output: str) -> bool:
    """True when a `launchctl print` report says the job is running now."""
    match = _STATE.search(launchctl_output)
    return match is not None and match.group(1) == "running"


def _job_report(label: str) -> tuple[int | None, str | None, bool]:
    """Ask launchctl about one job, best-effort: (last exit code, log path,
    running now). (None, None, False) on ANY failure to check at all (launchctl missing -- e.g. not
    macOS, the job not loaded, a hung call) -- this must never block or fail
    session start, same posture as the `ccw doctor` subprocess call below."""
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=_JOB_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, False
    out = result.stdout
    return extract_last_exit(out), extract_log_path(out), extract_running(out)


def job_reports() -> dict[str, tuple[int | None, str | None, bool]]:
    """Each watched job's (last exit code, log path, running now). The code is None where
    launchctl could not say (never run, not loaded, not macOS, a hung call).
    Unknown is not the same as healthy, and not the same as failing either:
    callers leave a job's failure period untouched when its code is None."""
    return {label: _job_report(label) for label in _WATCHED_JOBS}


# `cli._log_run_summary`'s completed-sweep line: "sweep: N items, ..., K failed".
# A run that STOPPED (the archive root lost mid-run) adds "; stopped: ..." and
# did not finish, so it never counts as a finished run.
_SWEEP_SUMMARY = re.compile(r"^sweep: (\d+) items, .*?(\d+) failed")


def latest_sweep_outcome(
    capture_log: Path, running: bool = False
) -> tuple[int, int, datetime] | None:
    """(failed, items, finished_at) of the newest sweep that ran to the end, or
    None when there is none, the log cannot be read, the newest run summary is
    not a finished run (a refusal, a crash, a stop), or a sweep has started
    since (so the newest summary is the previous run's and cannot explain the
    current exit code). Pairs lines in file order, as `ccw doctor` does: the
    log is append-only (W-20261010-A02).

    `running`: launchctl says the job is running now. Its exit code is then
    the previous run's, so a start with no summary yet is THAT run, and the
    outcome before it is the one that explains the code (review of 71d5aec)."""
    try:
        lines = capture_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    outcome: tuple[int, int, datetime] | None = None
    before_start: tuple[int, int, datetime] | None = None
    open_start = False
    for line in lines:
        if '"sweep' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message")
        if record.get("status") == "sweep-started":
            before_start, outcome, open_start = outcome, None, True
            continue
        if not isinstance(message, str) or not message.startswith("sweep: "):
            continue
        open_start = False
        match = _SWEEP_SUMMARY.match(message)
        at = _parse_ts(record.get("at"))
        outcome = None
        if match is not None and at is not None and "; stopped:" not in message:
            outcome = (int(match.group(2)), int(match.group(1)), at)
    if running and open_start:
        return before_start
    return outcome


def _finished_with_failures(
    label: str,
    code: int,
    outcome: tuple[int, int, datetime] | None,
    now: datetime | None = None,
) -> bool:
    """The sweep's exit code is explained by its newest run, which FINISHED
    with failed items: exit 1 (ccw sweep's code for failed items; any other
    code is the job itself failing), a finished run (never a refusal, a stop
    or a crash; see latest_sweep_outcome), within a day (W-20261010-A02,
    tightened after the review of 71d5aec)."""
    if not label.endswith("ccw-sweep") or code != 1 or outcome is None or outcome[0] <= 0:
        return False
    return (now or _now()) - outcome[2] <= _FINISHED_RUN_MAX_AGE


def job_tier(
    label: str,
    code: int,
    broken_for_s: float,
    outcome: tuple[int, int, datetime] | None = None,
    now: datetime | None = None,
) -> int:
    """The job's tier on its clock. A sweep that FINISHED with failed items is
    capped at WARNING (Gavin, 2026-10-10, Q10: "Cap it at WARNING"): the next
    sweep retries those items, so it is never spoken. A job that cannot run
    keeps the full ladder."""
    tier = _tier(broken_for_s)
    return min(tier, 1) if _finished_with_failures(label, code, outcome, now) else tier


def job_message(
    label: str,
    code: int,
    broken_for_s: float,
    outcome: tuple[int, int, datetime] | None = None,
    capture_log: Path | None = None,
    log_path: str | None = None,
    now: datetime | None = None,
) -> str:
    """The line for one failing scheduled job, tiered on how long it has been
    seen failing. `ccw doctor` does not check these jobs at all, so this is
    the only place that would have caught the real archive-job incident this
    exists to close (operator-approved, 2026-08-24). It used to fire plainly,
    desktop and voice, at every session start until fixed; sent back
    2026-09-29 it runs the same clock and dedup as the doctor verdict,
    because `ccw repair` exiting 1 for a day would otherwise speak at every
    start of that day.

    W-20261010-A02: when the sweep's newest run finished with failed items,
    say that, with the count and capture.jsonl, instead of "has been failing
    for": on 2026-10-09 that wording sent a session to the launchd log, whose
    untimestamped tail was a 2 Oct outage, for a run with 1 of 30,981 failed.

    W-20261010-A12: the generic line names the log launchctl reports for the
    job, or says how to find it; it no longer names ~/.claude/logs/, which the
    jobs stopped writing to on 2026-10-10."""
    lasted = _duration(broken_for_s)
    tier = job_tier(label, code, broken_for_s, outcome, now)
    if outcome is not None and _finished_with_failures(label, code, outcome, now):
        failed, items, at = outcome
        when = at.astimezone().strftime("%-I:%M %p %a %-d %b")
        body = (
            f"ccw-sweep's last run finished {when} with {failed} of {items} item(s) "
            f"failed (exit {code}, first seen {lasted} ago). Which items and why: "
            f"{capture_log if capture_log is not None else 'capture.jsonl'}."
        )
        return ("cc-warehouse: ", "cc-warehouse: WARNING - ", "cc-warehouse: ALERT - ")[tier] + body
    target = log_path or f"the path named by launchctl print gui/$(id -u)/{label}"
    return (
        f"cc-warehouse: scheduled job failing: {label} (exit {code}), first seen "
        f"{lasted} ago. Check its log: {target}",
        f"cc-warehouse: WARNING - scheduled job {label} has been failing for "
        f"{lasted} (exit {code}). Check its log: {target}",
        f"cc-warehouse: ALERT - scheduled job {label} has been failing for "
        f"{lasted} (exit {code}). Check its log now: {target}",
    )[tier]


def extract_root(doctor_output: str) -> Path | None:
    """The warehouse root from `ccw doctor`'s own `config` line, or None when
    doctor printed none (it never answered, or crashed first)."""
    match = _CONFIG_ROOT.search(doctor_output)
    return Path(match.group(1)) if match else None


def _warehouse_root(doctor_output: str | None) -> Path:
    """Where `ccw` keeps its logs. Doctor's own answer first: it resolved the
    root with ccw's real config code, so this script does not port that code
    (ruling 2026-09-29; it used to read config.toml with tomllib, which
    silently skipped the file on a python3 older than 3.11). Only when doctor
    gave no answer: CCW_ROOT, then the documented default."""
    found = extract_root(doctor_output) if doctor_output else None
    if found is not None:
        return found
    env = os.environ.get("CCW_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / "cc-warehouse-data"


def latest_repair_summary(capture_log: Path) -> dict[str, object] | None:
    """The newest `repair-summary` line in ccw's capture log, or None when
    there is none (repair never ran on this build) or the log cannot be read.
    That one line per repair run is the whole interface (agreed 2026-09-29
    with the repair side): `repair-refused` and per-run error lines are
    ignored, and exit code 1 from repair means repair itself broke, which
    the scheduled-job check already covers."""
    try:
        lines = capture_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"repair-summary"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("status") == "repair-summary":
            return record
    return None


def refusal_message(count: int, broken_for_s: float) -> str:
    """The line for archive folders `ccw repair` will not re-render, tiered
    from when the oldest was first seen."""
    lasted = _duration(broken_for_s)
    body = (
        f"{count} archive folder(s) changed in a way ccw cannot explain, first "
        f"seen {lasted} ago. Restore them from ~/.claude or see "
        f"docs/operations.md; `ccw repair` will not re-render over them."
    )
    return (
        f"cc-warehouse: {body}",
        f"cc-warehouse: WARNING - {body}",
        f"cc-warehouse: ALERT - {body}",
    )[_tier(broken_for_s)]


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
    floor: int = 0,
) -> str | None:
    """The escalating line to print, or None to stay quiet.

    `broken_for_s` None (doctor healthy) stays silent no matter how large the
    chronic backlog is: this signal clears the moment the real problem is
    fixed, not merely once it has been seen (ticket 24.7). Otherwise it is how
    long capture has been continuously broken, and picks the tier. `floor`
    raises the tier when the clock itself cannot be trusted (a lost or
    unwritable state file), never lowers it."""
    if broken_for_s is None:
        return None
    tier = max(_tier(broken_for_s), floor)
    lasted = _duration(broken_for_s)
    detail = f"{uncaptured} uncaptured" if uncaptured is not None else "count unknown"
    return (
        f"cc-warehouse: capture check failed ({detail}), first seen {lasted} ago. "
        f"Run `ccw doctor`.",
        f"cc-warehouse: WARNING - capture check has been failing for {lasted} "
        f"({detail}). Run `ccw doctor`.",
        f"cc-warehouse: ALERT - capture has been broken for {lasted} "
        f"({detail}). Run `ccw doctor` now.",
    )[tier]


def unknown_message(reason: str) -> str:
    """The line for a check that got NO verdict: a timeout, an OSError, a
    hung check. It says the check could not get an answer, never that capture
    failed: on the 2026-09-07 incident that made this wording exist, capture
    was working perfectly while doctor lost a race against a sweep. It has no
    tier. Until 2026-09-07 it spoke at once; from then until 2026-09-29 it
    shared the broken streak/clock; sent back 2026-09-29 (ruling: Gavin) it
    counts for nothing, because a killed headless check (`claude -p` kills
    async hooks) backdated the next blip into a spoken ALERT. The uncaptured
    figure is left out: doctor never printed it."""
    return (
        f"cc-warehouse: could not check capture ({reason}); the result is "
        f"unknown and not counted as broken. Run `ccw doctor` if this repeats."
    )


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
    """Another pane holds the lock, so its check is running now. This pane
    never alerts and never writes state (only the holder does, R14): it logs
    and hands the session the last recorded lines. A lock held past
    _HUNG_AFTER_S means that check is hung, which is an UNANSWERED check:
    logged as unknown, handed to the session, never alarmed (sent back
    2026-09-29; three panes during one hang used to raise three desktop and
    three spoken alerts)."""
    state = _read_state(STATE_PATH)
    try:
        held_since = datetime.fromtimestamp(LOCK_PATH.stat().st_mtime, timezone.utc)
    except OSError:
        held_since = now
    held_for = max(0.0, (now - held_since).total_seconds())
    last = state.get("last_lines")
    lines = [line for line in last if isinstance(line, str)] if isinstance(last, list) else []
    if held_for > _HUNG_AFTER_S:
        reason = f"a check started {_duration(held_for)} ago has not answered"
        report("unknown", reason)
        _emit([unknown_message(reason)] + lines)
        return 0
    report("reused", f"another session's check started {int(held_for)}s ago")
    _emit(lines)
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


def _raise(status_tier: int, message: str, notify: bool) -> None:
    report(("info", "warn", "alert")[status_tier], message, notify=notify)


def _check(executable: str, started: datetime, lock_fd: int | None) -> int:
    prev, lost = _load_state(STATE_PATH)
    # A readable file whose start time is garbled has lost the clock too.
    if prev.get("broken_since") is not None and _parse_ts(prev.get("broken_since")) is None:
        lost = True
    saved = _write_state(STATE_PATH, {"check_started_at": started.isoformat()})

    # A doctor that could not be ASKED and a doctor that answered FAIL are
    # different facts. The first is UNKNOWN: logged, handed to the session,
    # and it neither opens nor extends an outage (sent back 2026-09-29; see
    # unknown_message). Before 2026-09-07 it spoke at once and `return 0`-ed,
    # skipping broken_jobs(); both halves fired for real, which is why this
    # branch still falls through to the job and refusal checks below.
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
        report("unknown", f"{executable} doctor did not answer: {type(exc).__name__}: {exc}")

    uncaptured = extract_uncaptured(result.stdout) if result is not None else None
    now = _now()
    prev_count, prev_at = read_backlog_snapshot(STATE_PATH)
    rate = backlog_growth(prev_count, prev_at, uncaptured, now) if uncaptured is not None else None
    lines: list[str] = []
    updates: dict[str, object] = {}

    if unreachable is not None:
        lines.append(unknown_message(unreachable))
    elif result is not None and result.returncode == 0:
        updates.update(
            {"broken_since": None, "last_fail_at": None, "alerted_tier": 0,
             "last_verdict": "ok", "last_verdict_at": now.isoformat()}
        )
        report("ok", f"uncaptured={uncaptured}")
    else:
        carried = carried_broken_since(prev, now)
        since = carried if carried is not None else started
        alerted = _alerted(prev) if carried is not None else 0
        broken_for = max(0.0, (now - since).total_seconds())
        # Edge case 2: a clock that was lost, or cannot be saved, would
        # restart at zero on every check and never escalate. Fail toward
        # alerting: at least a WARNING, and say why. The dedup cannot be
        # trusted either, so it alerts each time until the file is fixed.
        floor = 1 if (lost or not saved) else 0
        tier = max(_tier(broken_for), floor)
        message = freshness_message(broken_for, uncaptured, floor=floor) or ""
        if floor:
            message += " (The freshness state file could not be read or written, so how long is unknown.)"
        message += growth_context(rate)
        notify = tier > alerted or bool(floor)
        updates.update(
            {"broken_since": since.isoformat(), "last_fail_at": now.isoformat(),
             "alerted_tier": max(alerted, tier), "last_verdict": "fail",
             "last_verdict_at": now.isoformat()}
        )
        # Ticket 42 item #1: the log status tracks the tier; tier 0, the
        # first half hour, is "info", never a toast (the ticket 24.7 lesson).
        # Each tier raises its channels ONCE per outage; later checks log at
        # the same status and hand the line to the session only.
        _raise(tier, message, notify)
        lines.append(message)

    lines += _unknown_notice(prev, now, unreachable is not None, updates)
    lines += _job_lines(prev, now, updates, result.stdout if result is not None else None)
    lines += _refusal_lines(prev, now, updates, result.stdout if result is not None else None)
    updates["last_lines"] = lines
    _write_state(STATE_PATH, updates, drop=("consecutive_broken",))
    write_backlog_snapshot(STATE_PATH, uncaptured, now.isoformat())
    _emit(lines)
    return 0


def _job_lines(
    prev: dict[str, object],
    now: datetime,
    updates: dict[str, object],
    doctor_output: str | None = None,
) -> list[str]:
    """Each failing watched job on its own clock, from when this hook first
    saw it failing, with its own one-alert-per-tier dedup. A job seen exiting
    0 clears; a job launchctl could not answer about keeps its period."""
    try:
        reports = job_reports()
    except Exception:  # noqa: BLE001 - must never fail session start
        reports = {}
    codes = {label: code for label, (code, _log, _running) in reports.items()}
    capture_log = _warehouse_root(doctor_output) / "logs" / "capture.jsonl"
    sweep_running = any(
        running for label, (_c, _l, running) in reports.items() if label.endswith("ccw-sweep")
    )
    outcome = (
        latest_sweep_outcome(capture_log, running=sweep_running) if any(codes.values()) else None
    )
    old = prev.get("jobs")
    jobs: dict[str, object] = dict(old) if isinstance(old, dict) else {}
    lines: list[str] = []
    for label, code in codes.items():
        entry = jobs.get(label)
        if code is None:
            continue
        if code == 0:
            jobs.pop(label, None)
            continue
        since = _parse_ts(entry.get("since")) if isinstance(entry, dict) else None
        alerted = _alerted(entry) if since is not None else 0
        since = since or now
        broken_for = max(0.0, (now - since).total_seconds())
        tier = job_tier(label, code, broken_for, outcome, now)
        message = job_message(
            label, code, broken_for, outcome, capture_log, reports[label][1], now
        )
        _raise(tier, message, tier > alerted)
        jobs[label] = {"since": since.isoformat(), "exit": code, "alerted_tier": max(alerted, tier)}
        lines.append(message)
    updates["jobs"] = jobs
    return lines


def _unknown_notice(
    prev: dict[str, object], now: datetime, unanswered: bool, updates: dict[str, object]
) -> list[str]:
    """The one desktop-only notice for a long run of unanswered checks (see
    _UNKNOWN_NOTICE_S). A real verdict, or a gap over _CONTINUITY_S between
    unanswered checks, restarts the run; the notice fires once per run."""
    if not unanswered:
        updates.update({"unknown_since": None, "last_unknown_at": None, "unknown_noticed": False})
        return []
    since = _parse_ts(prev.get("unknown_since"))
    last = _parse_ts(prev.get("last_unknown_at"))
    noticed = prev.get("unknown_noticed") is True
    if since is None or last is None or (now - last).total_seconds() > _CONTINUITY_S:
        since, noticed = now, False
    updates.update({"unknown_since": since.isoformat(), "last_unknown_at": now.isoformat()})
    lasted = (now - since).total_seconds()
    if lasted < _UNKNOWN_NOTICE_S or noticed:
        updates["unknown_noticed"] = noticed
        return []
    message = (
        f"cc-warehouse: could not check capture for {_duration(lasted)}; `ccw doctor` "
        f"has not answered once in that time. Run it by hand."
    )
    report("unknown-notice", message)
    updates["unknown_noticed"] = True
    return [message]


def _refusal_lines(
    prev: dict[str, object], now: datetime, updates: dict[str, object], doctor_output: str | None
) -> list[str]:
    """Open refusals from `ccw repair`'s latest summary, on the same clock
    from `oldest_refusal_at`, with their own dedup. A summary with 0 clears;
    no summary says nothing; a reminder within _REPAIR_QUIET_S of repair's
    own run waits for the next check (repair alerted on that run itself)."""
    summary = latest_repair_summary(_warehouse_root(doctor_output) / "logs" / "capture.jsonl")
    if summary is None:
        return []
    count = summary.get("open_refusals")
    oldest = _parse_ts(summary.get("oldest_refusal_at"))
    if not isinstance(count, int) or count <= 0:
        updates["refusals"] = None
        return []
    since = oldest or _parse_ts(summary.get("at")) or now
    old = prev.get("refusals")
    alerted = _alerted(old)
    broken_for = max(0.0, (now - since).total_seconds())
    tier = _tier(broken_for)
    message = refusal_message(count, broken_for)
    notify = tier > alerted
    summary_at = _parse_ts(summary.get("at"))
    if notify and summary_at is not None and (now - summary_at).total_seconds() < _REPAIR_QUIET_S:
        notify = False
        report(("info", "warn", "alert")[tier], message + " (reminder deferred: repair just ran)", notify=False)
    else:
        _raise(tier, message, notify)
        if notify:
            alerted = tier
    updates["refusals"] = {"since": since.isoformat(), "alerted_tier": alerted}
    return [message]


if __name__ == "__main__":
    # SessionStart hooks must never fail session start; everything above already
    # returns 0, this is the backstop for anything unforeseen.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        report("error", f"freshness check crashed: {type(exc).__name__}: {exc}")
        sys.exit(0)
