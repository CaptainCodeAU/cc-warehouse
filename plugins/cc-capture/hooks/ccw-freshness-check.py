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


def report(status: str, detail: str) -> None:
    """Same idiom as ccw-hook.py's report(): log durably, speak only on trouble."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "ccw-freshness-check",
        "status": status,
        "detail": detail,
    }
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass
    if status not in ("error",):
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


def read_streak(path: Path) -> int:
    """Consecutive broken doctor verdicts so far, or 0 if unknown, missing, or
    unreadable - a corrupt state file must never crash the check."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        streak = data.get("consecutive_broken", 0)
        return streak if isinstance(streak, int) and streak >= 0 else 0
    except (OSError, ValueError):
        return 0


def write_streak(path: Path, streak: int) -> None:
    """Best-effort, tmp-then-replace so a crash mid-write cannot corrupt the
    file for the next session-start."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"consecutive_broken": streak}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


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
            timeout=5,
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


def freshness_message(streak: int, uncaptured: int | None) -> str | None:
    """The escalating line to print, or None to stay quiet.

    Streak 0 (doctor healthy) stays silent no matter how large the chronic
    backlog is: this signal clears the moment the real problem is fixed, not
    merely once it has been seen (ticket 24.7)."""
    if streak <= 0:
        return None
    detail = f"{uncaptured} uncaptured" if uncaptured is not None else "count unknown"
    if streak < _WARN_AT:
        return f"cc-warehouse: capture check failed ({detail}). Run `ccw doctor`."
    if streak < _ALERT_AT:
        return (
            f"cc-warehouse: WARNING - capture check has failed {streak} times in a row "
            f"({detail}). Run `ccw doctor`."
        )
    return (
        f"cc-warehouse: ALERT - capture has been broken for {streak} session-starts in a "
        f"row ({detail}). Run `ccw doctor` now."
    )


def main() -> int:
    if os.environ.get("CCW_SKIP_HOOK") == "1":
        report("skipped", "CCW_SKIP_HOOK=1")
        return 0

    executable = find_ccw()
    if executable is None:
        report("error", "ccw is not installed; freshness check skipped")
        return 0

    try:
        result = subprocess.run(
            [executable, "doctor"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report("error", f"{executable} doctor did not run: {type(exc).__name__}: {exc}")
        return 0

    uncaptured = extract_uncaptured(result.stdout)
    if result.returncode == 0:
        write_streak(STATE_PATH, 0)
        report("ok", f"uncaptured={uncaptured}")
    else:
        streak = read_streak(STATE_PATH) + 1
        write_streak(STATE_PATH, streak)
        message = freshness_message(streak, uncaptured)
        if message is not None:
            report("warn" if streak < _ALERT_AT else "alert", message)
            print(message)

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
