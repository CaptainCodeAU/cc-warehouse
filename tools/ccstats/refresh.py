#!/usr/bin/env python3
"""Rebuild the live ccstats dashboard end to end, unattended.

WHY THIS EXISTS. `/dashboard` (the slash command in `.claude/commands/`) is the
operator-facing path: it asks whether to refresh, shows the saved project-exclude
list, and serves the built page over loopback HTTP because the agent's browser
tool refuses `file://`. None of that is needed by a scheduled job. Stripped of
the questions and the throwaway web server, the whole command is two calls:

    collect.py --quiet      # scan transcripts -> <out>/sessions.sqlite
    dashboard.py            # that db -> <out>/claude-code-dashboard-live.html

This script is those two calls plus a log line, so `launchd` has one program to
start instead of two.

NO FLAG PLUMBING, ON PURPOSE. `dashboard.py` already reads the saved
`dashboard-defaults.json` itself when no `--include`/`--exclude` is passed (see
its `load_default_filters`), so this script deliberately passes neither. Adding
a copy of that logic here is exactly the drift that function was written to
close.

OUTPUT CONVENTION, matching the ccw-sweep / ccw-repair jobs: `--quiet` prints
nothing when everything worked, and prints the full run on any failure. An empty
log is therefore the healthy state, and a non-empty log always means something
needs a look.

DEGRADED BUILD, ON PURPOSE. If the scan fails, the page is still rebuilt from
whatever `sessions.sqlite` already holds - a slightly stale dashboard beats no
dashboard - but the exit code is still non-zero so the failure is recorded.

Writes nothing itself. Both children resolve their own output root the usual way
(`CCSTATS_OUT`, else `~/.cc-warehouse/stats`), and `common.resolve_out` already
refuses a root inside this repo, `~/.claude`, the archive or the warehouse data
root.

    uv run python3 tools/ccstats/refresh.py [--quiet] [--skip-collect]
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_PYTHON = (3, 12)
FLAGS = {"--quiet", "--skip-collect", "-h", "--help"}
USAGE = "uv run python3 tools/ccstats/refresh.py [--quiet] [--skip-collect]"


def _run(script: str, args: list[str], log: list[str]) -> bool:
    """Run one sibling script with THIS interpreter. True if it exited 0.

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
        return False
    return True


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

    if sys.version_info < MIN_PYTHON:
        want = ".".join(str(n) for n in MIN_PYTHON)
        print(
            f"error: needs Python {want}+, running {sys.version.split()[0]} ({sys.executable})",
            file=sys.stderr,
        )
        return 2

    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    log: list[str] = [f"ccstats refresh {stamp}"]
    ok = True

    if skip_collect:
        log.append("  --skip-collect: reusing the existing sessions.sqlite")
    else:
        log.append("collect")
        if not _run("collect.py", ["--quiet"], log):
            log.append("  scan failed; building the page from the existing database anyway")
            ok = False

    log.append("dashboard")
    if not _run("dashboard.py", [], log):
        ok = False

    if not ok or not quiet:
        print("\n".join(log))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
