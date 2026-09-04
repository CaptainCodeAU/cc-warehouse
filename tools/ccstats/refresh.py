#!/usr/bin/env python3
"""Rebuild the live ccstats dashboard end to end, unattended.

WHY THIS EXISTS. `/dashboard` (the slash command in `.claude/commands/`) is the
operator-facing path: it asks whether to refresh, shows the saved project-exclude
list, and serves the built page over loopback HTTP because the agent's browser
tool refuses `file://`. None of that is needed by a scheduled job. Stripped of
the questions and the throwaway web server, the whole command is two calls:

    collect.py --quiet      # scan transcripts -> <out>/sessions.sqlite
    dashboard.py            # that db -> <out>/claude-code-dashboard-live.html

This script is those two calls plus a log line and a macOS dialog box, so
`launchd` has one program to start instead of two.

NO FLAG PLUMBING, ON PURPOSE. `dashboard.py` already reads the saved
`dashboard-defaults.json` itself when no `--include`/`--exclude` is passed (see
its `load_default_filters`), so this script deliberately passes neither. Adding
a copy of that logic here is exactly the drift that function was written to
close.

OUTPUT CONVENTION, matching the ccw-sweep / ccw-repair jobs: `--quiet` prints
nothing when everything worked, and prints the full run on any failure. An empty
log is therefore the healthy state, and a non-empty log always means something
needs a look.

THE DIALOG IS THE POINT OF A SCHEDULED JOB YOU CANNOT SEE. A `launchd` job
leaves no trace on screen, and this one's healthy log is deliberately empty, so
without something on screen there is no way to tell "ran fine at 13:00" from
"never fired at all". Every completion opens one dialog box, success or failure,
naming the program that ran and the full path of the page it wrote, with
buttons that open the page, reveal the page's folder, or reveal this script.
`--no-notify` turns it off for a hand run.

THREE BUTTONS IS AN APPLESCRIPT CEILING, not a choice. `display dialog` accepts
no more, which is why there is no separate Dismiss button on a successful run:
any button closes the box, and an unattended one closes itself.

A BOX, NOT A BANNER, by the operator's explicit choice (2026-09-04): a banner
was built first and rejected in favour of something with a button to press. The
cost of that choice is stated rather than hidden - a dialog is modal and
transient, so a run nobody is sitting in front of goes unseen, where a banner
would have waited in Notification Centre.

IT MUST NEVER BLOCK FOREVER. A modal dialog holds this process open until
someone clicks, which for an unattended 13:00 job could be days. `giving up
after` caps that at DIALOG_TIMEOUT_SECONDS, after which the box closes itself
and the run finishes normally.

THE PAGE PATH IS READ BACK FROM THE CHILD, not recomputed here. `dashboard.py`
prints the absolute path it actually wrote; parsing that line means the banner
can never name a file a different output root would have produced.

DEGRADED BUILD, ON PURPOSE. If the scan fails, the page is still rebuilt from
whatever `sessions.sqlite` already holds - a slightly stale dashboard beats no
dashboard - but the exit code is still non-zero so the failure is recorded.

Writes nothing itself. Both children resolve their own output root the usual way
(`CCSTATS_OUT`, else `~/.cc-warehouse/stats`), and `common.resolve_out` already
refuses a root inside this repo, `~/.claude`, the archive or the warehouse data
root.

    uv run python3 tools/ccstats/refresh.py [--quiet] [--skip-collect] [--no-notify]
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ME = Path(__file__).resolve()
MIN_PYTHON = (3, 12)
FLAGS = {"--quiet", "--skip-collect", "--no-notify", "-h", "--help"}
USAGE = "uv run python3 tools/ccstats/refresh.py [--quiet] [--skip-collect] [--no-notify]"

PAGE_NAME = "claude-code-dashboard-live.html"
OSASCRIPT = "/usr/bin/osascript"
OPEN = "/usr/bin/open"

# How long the box waits before closing itself. Long enough to notice, short
# enough that an unattended run does not leave a process parked for days.
DIALOG_TIMEOUT_SECONDS = 300

# AppleScript's `display dialog` accepts AT MOST THREE buttons. That hard cap,
# not a design preference, is why there is no separate Dismiss: every button
# closes the box, and an unattended box closes itself on the timeout anyway.
OPEN_PAGE = "Open page"
SHOW_FOLDER = "Show page folder"
SHOW_SCRIPT = "Show script"
DISMISS = "Dismiss"


def _run(script: str, args: list[str], log: list[str]) -> tuple[bool, str]:
    """Run one sibling script with THIS interpreter. (exited-zero, its stdout).

    `sys.executable` rather than a bare `python3`: the whole point of naming a
    known-good interpreter in the launchd plist is that the children inherit it,
    instead of re-resolving `python3` against launchd's near-empty PATH (where on
    macOS it would find the 3.9 system build and fail on `tomllib`).
    """
    cmd = [sys.executable, str(HERE / script), *args]
    log.append(f"  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    for stream in (proc.stdout, proc.stderr):
        for line in stream.splitlines():
            log.append(f"  | {line}")
    if proc.returncode != 0:
        log.append(f"  ! {script} exited {proc.returncode}")
        return False, proc.stdout
    return True, proc.stdout


def page_path(dashboard_stdout: str) -> str | None:
    """The absolute page path out of `dashboard.py`'s own success line.

    That line is `<path>  (<bytes> bytes, <n> sessions, <window>)`, so the path
    is everything before the two spaces that open the parenthetical. Returns
    None rather than guessing if the line is absent or reshaped - a banner that
    names no file is honest, one that names the wrong file is not.
    """
    for line in dashboard_stdout.splitlines():
        if PAGE_NAME in line:
            return line.split("  (")[0].strip() or None
    return None


def _applescript_string(value: str) -> str:
    """`value` as an AppleScript string literal.

    Backslash first, or the escapes introduced below would be escaped again.
    Real newlines become `\\n` because an AppleScript literal cannot carry one,
    and this dialog is deliberately multi-line: a full path is unreadable when
    it is wrapped into a paragraph with other text.
    """
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n")
    return '"' + out + '"'


def notify(title: str, message: str, page: str | None, log: list[str]) -> None:
    """Open one dialog box reporting the run, and act on the button. Never raises.

    A notifier that can take down the job it reports on is worse than no
    notifier, so every failure here is logged and swallowed. Every binary is
    called by absolute path because launchd's PATH is near-empty.

    The two page buttons are offered only when a page was actually written, so
    the box can never hand out a button that opens nothing.
    """
    if page:
        buttons = [SHOW_SCRIPT, SHOW_FOLDER, OPEN_PAGE]
    else:
        buttons = [SHOW_SCRIPT, DISMISS]
    button_list = ", ".join(_applescript_string(b) for b in buttons)
    script = (
        f"display dialog {_applescript_string(message)} "
        f"with title {_applescript_string(title)} "
        f"buttons {{{button_list}}} "
        f"default button {_applescript_string(buttons[-1])} "
        f"with icon {'note' if page else 'caution'} "
        f"giving up after {DIALOG_TIMEOUT_SECONDS}"
    )
    try:
        proc = subprocess.run(
            [OSASCRIPT, "-e", script], capture_output=True, text=True, check=False
        )
    except OSError as exc:
        log.append(f"  ! dialog not shown: {exc}")
        return
    if proc.returncode != 0:
        log.append(f"  ! dialog not shown: osascript exited {proc.returncode}")
        for line in proc.stderr.splitlines():
            log.append(f"  ! {line}")
        return

    pressed = _button_pressed(proc.stdout)
    log.append(f"  dialog: {pressed or 'closed itself'}")
    _act_on(pressed, page, log)


def _act_on(pressed: str | None, page: str | None, log: list[str]) -> None:
    """Do what the pressed button says. Unknown, absent or Dismiss does nothing.

    `open -R` rather than `open` for the two "show me where it lives" buttons:
    it opens the enclosing folder AND selects the file inside it, which is what
    "take me to it" means. `open` on the page itself hands it to the browser.
    """
    if pressed == OPEN_PAGE and page:
        _open([page], log)
    elif pressed == SHOW_FOLDER and page:
        _open(["-R", page], log)
    elif pressed == SHOW_SCRIPT:
        _open(["-R", str(ME)], log)


def _open(args: list[str], log: list[str]) -> None:
    """`/usr/bin/open`, failing quietly into the log like everything else here."""
    try:
        proc = subprocess.run([OPEN, *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        log.append(f"  ! open {args} failed: {exc}")
        return
    if proc.returncode != 0:
        log.append(f"  ! open {args} exited {proc.returncode}")
        for line in proc.stderr.splitlines():
            log.append(f"  ! {line}")


def _button_pressed(osascript_stdout: str) -> str | None:
    """The button name out of `button returned:X, gave up:false`.

    None when the box closed itself on the timeout, which is not a failure and
    must not read as one.
    """
    text = osascript_stdout.strip()
    marker = "button returned:"
    if marker not in text:
        return None
    after = text.split(marker, 1)[1]
    name = after.split(", gave up:", 1)[0].strip()
    return name or None


def main(argv: list[str]) -> int:
    unknown = [a for a in argv if a not in FLAGS]
    if unknown:
        print(f"error: unknown argument(s): {unknown!r}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if "-h" in argv or "--help" in argv:
        print((__doc__ or USAGE).strip())
        return 0

    quiet = "--quiet" in argv
    skip_collect = "--skip-collect" in argv
    want_notify = "--no-notify" not in argv

    if sys.version_info < MIN_PYTHON:
        want = ".".join(str(n) for n in MIN_PYTHON)
        print(
            f"error: needs Python {want}+, running {sys.version.split()[0]} ({sys.executable})",
            file=sys.stderr,
        )
        return 2

    started = time.monotonic()
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    log: list[str] = [f"ccstats refresh {stamp}"]
    ok = True
    scan_failed = False

    if skip_collect:
        log.append("  --skip-collect: reusing the existing sessions.sqlite")
    else:
        log.append("collect")
        if not _run("collect.py", ["--quiet"], log)[0]:
            log.append("  scan failed; building the page from the existing database anyway")
            ok = False
            scan_failed = True

    log.append("dashboard")
    built, dashboard_stdout = _run("dashboard.py", [], log)
    if not built:
        ok = False
    page = page_path(dashboard_stdout)

    if want_notify:
        elapsed = f"{time.monotonic() - started:.0f}s"
        if ok:
            title = f"ccstats dashboard rebuilt ({elapsed})"
        elif built:
            title = f"ccstats dashboard STALE ({elapsed})"
        else:
            title = f"ccstats dashboard FAILED ({elapsed})"
        # Program then artefact, each on its own line and each in full: the box
        # is often the only place either path is ever seen.
        lines = [
            "Program that ran:",
            str(ME),
            "",
            "Page written:",
            page or "none - no page was written",
        ]
        if scan_failed:
            lines += ["", "The scan failed, so the data was not refreshed."]
        if not built:
            lines += ["", "dashboard.py failed. See this job's log."]
        notify(title, "\n".join(lines), page, log)

    if not ok or not quiet:
        print("\n".join(log))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
