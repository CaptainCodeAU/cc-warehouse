#!/usr/bin/env python3
"""Rebuild the live ccstats dashboard end to end, unattended.

WHY THIS EXISTS. `/dashboard` (the slash command in `.claude/commands/`) is the
operator-facing path: it asks whether to refresh, shows the saved project-exclude
list, and serves the built page over loopback HTTP because the agent's browser
tool refuses `file://`. None of that is needed by a scheduled job. Stripped of
the questions and the throwaway web server, the whole command is two calls:

    collect.py --quiet      # scan transcripts -> <out>/sessions.sqlite
    dashboard.py            # that db -> <out>/claude-code-dashboard-live.html
                            #            + <out>/dashboard-data.json
    export.py               # that db -> <out>/stats-facts.json

This script is those three calls plus a log line and a macOS dialog box, so
`launchd` has one program to start instead of three.

THE PAGE IS FOR A PERSON; THE TWO JSON FILES ARE FOR A PROGRAM. `dashboard.py`
writes its own payload out beside the page (the SAME string it embeds, so a
fetcher and a reader can never see different numbers), and `export.py` writes a
few kilobytes of top-line numbers. `export.py` runs LAST because it is the least
important of the three: if it fails, the run is reported as failed but nobody
loses the page.

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

Day to day operation - run it now, read the log, change the time, turn it off -
is in CHEATSHEET.md, beside this file.
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
DATA_NAME = "dashboard-data.json"
FACTS_NAME = "stats-facts.json"
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


def _path_named(stdout: str, filename: str) -> str | None:
    """The absolute path of `filename` out of a child's own success line.

    Every one of these lines is `<path>  (<parenthetical>)`, so the path is
    everything before the two spaces that open it. Returns None rather than
    guessing if no line names that file, or the line has been reshaped - a box
    that names no file is honest, one that names the wrong file is not.

    Matching on the FILENAME, not on line position, is what lets `dashboard.py`
    print a second path line without this reading back the wrong one.
    """
    for line in stdout.splitlines():
        if filename in line:
            return line.split("  (")[0].strip() or None
    return None


def page_path(dashboard_stdout: str) -> str | None:
    """The page path out of `dashboard.py`'s stdout. Read by `ccw`-adjacent
    callers and by this script's own dialog, so it keeps its own name."""
    return _path_named(dashboard_stdout, PAGE_NAME)



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


def notify(title: str, message: str, page: str | None, log: list[str]) -> bool:
    """Open one dialog box reporting the run, and act on the button. Never raises.

    True when the box actually appeared. The caller needs that answer because
    the whole point of the box is to be the only visible sign a scheduled job
    ran; a box that silently failed to appear looks exactly like a job that
    never fired, and under `--quiet` the log line saying so would never be
    printed. It is deliberately NOT part of the exit status: a notifier that can
    take down the job it reports on is worse than no notifier.

    Every failure here is logged and swallowed. Every binary is called by
    absolute path because launchd's PATH is near-empty.

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
        return False
    if proc.returncode != 0:
        log.append(f"  ! dialog not shown: osascript exited {proc.returncode}")
        for line in proc.stderr.splitlines():
            log.append(f"  ! {line}")
        return False

    pressed = _button_pressed(proc.stdout)
    log.append(f"  dialog: {pressed or 'closed itself'}")
    _act_on(pressed, page, log)
    return True


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

    shown = True  # nothing to show is not a failure to show
    started = time.monotonic()
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    log: list[str] = [f"ccstats refresh {stamp}"]
    scan_failed = False

    if skip_collect:
        log.append("  --skip-collect: reusing the existing sessions.sqlite")
    else:
        log.append("collect")
        if not _run("collect.py", ["--quiet"], log)[0]:
            log.append("  scan failed; building the page from the existing database anyway")
            scan_failed = True

    log.append("dashboard")
    built, dashboard_stdout = _run("dashboard.py", [], log)
    page = page_path(dashboard_stdout)
    data = _path_named(dashboard_stdout, DATA_NAME)

    # Last, and with no flags, for the same anti-drift reason `dashboard.py` gets
    # none: it resolves its own output root and its own window.
    log.append("export")
    exported, export_stdout = _run("export.py", [], log)
    card = _path_named(export_stdout, FACTS_NAME)

    # ONE definition, not a boolean mutated at four sites. The exit status and
    # the dialog below are then visibly reading the same three facts, and a
    # future fourth child cannot be added while forgetting to flip a flag.
    ok = built and exported and not scan_failed

    if want_notify:
        elapsed = f"{time.monotonic() - started:.0f}s"
        # Every failure NAMED, not just the worst one. An if/elif ladder
        # ordered by severity silently drops the others: the first version of
        # this said "STALE" for a run where the scan AND the export had both
        # failed, and the export was never mentioned anywhere in the title.
        #
        # STALE still means "the data was not refreshed", which is what a failed
        # SCAN means; an export failure keeps its own word, so nobody goes
        # reading the collector for a fault that is not there.
        faults = []
        if not built:
            faults.append("PAGE FAILED")
        if scan_failed:
            faults.append("STALE")
        if not exported:
            faults.append("EXPORT FAILED")
        what = ", ".join(faults) if faults else "rebuilt"
        title = f"ccstats dashboard {what} ({elapsed})"
        # Program then artefacts, each on its own line and each in full: the box
        # is often the only place any of these paths is ever seen.
        lines = [
            "Program that ran:",
            str(ME),
            "",
            "Page written:",
            page or "none - no page was written",
            "",
            "Data written:",
            data or "none - no payload file was written",
            card or "none - no facts card was written",
        ]
        if scan_failed:
            lines += ["", "The scan failed, so the data was not refreshed."]
        if not built:
            lines += ["", "dashboard.py failed. See this job's log."]
        if not exported:
            # Only `stats-facts.json` is export.py's; `dashboard-data.json` was
            # written by dashboard.py and is as fresh as the page beside it.
            lines += ["", "export.py failed, so stats-facts.json may be stale."]
        shown = notify(title, "\n".join(lines), page, log)

    # A dialog that failed to appear breaks the quiet convention on purpose.
    # An empty log means "ran fine", and the box is the only other evidence the
    # job ran at all - so losing both at once must never be silent. It still
    # does not change the exit status.
    if not ok or not quiet or not shown:
        print("\n".join(log))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
