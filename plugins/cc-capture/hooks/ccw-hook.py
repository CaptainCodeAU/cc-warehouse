#!/usr/bin/env python3
"""SessionEnd wrapper: hand the payload to `ccw hook` (cc-warehouse).

WHAT REPLACED WHAT. This delegated to `claude-code-transcripts` until 2026-08-03.
cc-warehouse supersedes that tool, and its CLI is `ccw`.

THE BUG THIS FILE EXISTS TO NOT REPEAT, measured 2026-08-03. The previous
version called:

    uv tool run claude-code-transcripts hook

Two different programs share that name. The operator's fork (installed as an
editable uv tool, argparse, has a `hook` verb) and Simon Willison's PyPI package
(Click, verbs local/all/json/web, NO `hook`). `uv tool run` resolves the name
from the index, so it got the PyPI one:

    $ uv tool run claude-code-transcripts hook
    Usage: claude-code-transcripts local [OPTIONS]
    Error: Got unexpected extra argument (hook)

and `check=False` threw the non-zero exit away. Capture stopped on 2026-07-24
and nobody found out for ten days.

SO TWO RULES, both load-bearing:

  1. NEVER resolve a bare package name here. The original reason was that
     `cc-warehouse` was unregistered, so `uv tool run cc-warehouse hook` worked
     only by luck and would have run a squatter's code with the session payload
     on stdin. That specific hole CLOSED on 2026-08-09, when the name was
     published to PyPI by its author.

     The rule stays, because the hole was an instance and the rule is the class.
     Resolving a name at hook time still means a network lookup and an index
     that can serve a different artifact than the one you tested, at session end,
     unattended, with a transcript on stdin. Resolve a real executable.

  2. A failure must be LOUD. The hook still exits 0, because blocking session
     end is worse than a missed capture (SPEC 2.6, never-raise), but every
     failure is reported through channels the operator already watches.
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
import shutil
import subprocess
import sys
import urllib.request
# `timezone.utc`, NOT `datetime.UTC`: the latter is 3.11+, and an ordinary
# import of a too-new NAME is not deferred by the __future__ line above. It
# passed every static fence in the test suite and still killed this file at
# import time under 3.9 (found 2026-09-07, after a commit claimed both hooks
# were 3.9-safe having tested only the other one).
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

LOG = Path.home() / ".claude" / "logs" / "ccw-hook.log"
VOICE_URL = "http://localhost:8888/notify"
VOICE_ID = "fTtv3eikoepIosk8dTZ5"


_session: str | None = None  # set once from the payload; carried by every line


def report(status: str, detail: str) -> None:
    """Say it out loud and write it down. Never raises: a reporting failure must
    not become the thing that breaks capture.

    Every line carries the session id (ticket 37), so `grep <id>` on the log
    shows that session's whole hook run, and a `started` with nothing after it
    is a hook that died. Concurrent session ends interleave lines, so pairing
    by position would be wrong; pairing by id is not."""
    record: dict[str, str | None] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "ccw-hook",
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
        "session": _session,
        "status": status,
        "detail": detail,
    }
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass
    if status in ("ok", "started"):
        return
    try:
        payload = json.dumps(
            {
                "message": f"Transcript capture failed. {detail}",
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
    """A REAL executable path, never a package name (rule 1 above).

    CCW_BIN wins so the operator can point at a specific build; then PATH; then
    the uv-tool shim, which is where `uv tool install` puts it.

    The shim fallback is load-bearing, not padding. Measured 2026-08-03: `ccw` is
    only on PATH because `~/.local/bin` is, and a hook subprocess does not
    reliably inherit an interactive shell's PATH. The operator's own session-start
    hooks already write `"$HOME/.local/bin/ci-watch"` in full for the same reason.
    """
    override = os.environ.get("CCW_BIN")
    if override and Path(override).is_file():
        return override
    found = shutil.which("ccw")
    # A `.venv` hit is this repo's own editable dev checkout, live-editable by
    # construction (see this repo's CLAUDE.md frozen-install rule) - never
    # what a hook should run. Confirmed live 2026-09-09 (ticket 41 Finding 1):
    # this repo's `.envrc` puts `.venv/bin` ahead of `~/.local/bin` on PATH for
    # any shell whose cwd is under the repo, so `shutil.which` picked the dev
    # copy instead of the frozen install and both hooks got slower/flakier.
    if found and "/.venv/" not in found:
        return found
    shim = Path.home() / ".local" / "bin" / "ccw"
    return str(shim) if shim.is_file() else None


def _started(payload: str) -> None:
    """Write `started` BEFORE anything that can die (ticket 37 part B).

    Measured 2026-09-06: a hook wrote the raw JSONL and 26 sub-agent folders
    into the archive, then was killed before the catalog row, the
    `capture.jsonl` line and this file's `ok` line. Every log said "no such
    capture" while the disk said "captured". This line is the trace that run
    did not leave: a `started` with no `ok`/`error` after it is a hook that
    died mid-run, and the session id says which one.

    Parses the payload defensively: a bad payload is one of the things this
    line exists to record, so it must not be the reason there is no line."""
    global _session
    transcript = ""
    try:
        data: object = json.loads(payload)
        if isinstance(data, dict):
            fields = cast("dict[object, object]", data)
            raw = fields.get("session_id")
            _session = str(raw) if raw is not None else None
            transcript = str(fields.get("transcript_path") or "")
    except (ValueError, TypeError):
        pass
    report("started", transcript)


def main() -> int:
    payload = sys.stdin.read()
    _started(payload)
    executable = find_ccw()
    if executable is None:
        report(
            "error",
            "ccw is not installed. Run `uv tool install cc-warehouse`, or from a"
            " checkout `uv tool install --force --reinstall .` (frozen, NOT"
            " --editable), or set CCW_BIN.",
        )
        return 0

    env = dict(os.environ)
    # Voice settings the operator already runs. NOT set here: CCW_OPEN_FOLDER.
    # The old plugin opened a Finder window per capture, which was tolerable when
    # capture was occasional; with the hook actually firing it is not (58 sessions
    # ended in one 2.6-hour stretch on 2026-08-03). Set CCW_OPEN_FOLDER=1 in the
    # environment to restore it.
    env.setdefault("CCW_VOICE_URL", VOICE_URL)
    env.setdefault("CCW_VOICE_ID", VOICE_ID)

    try:
        result = subprocess.run(
            [executable, "hook"],
            input=payload,
            text=True,
            env=env,
            capture_output=True,
            timeout=40,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report("error", f"{executable} hook did not run: {type(exc).__name__}: {exc}")
        return 0

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        report(
            "error",
            f"{executable} hook exited {result.returncode}: "
            f"{detail[-1] if detail else '(no output)'}",
        )
        return 0

    report("ok", (result.stdout or "").strip().splitlines()[-1] if result.stdout else "")
    return 0


if __name__ == "__main__":
    # The hook never fails the session end (SPEC 2.6). Everything above already
    # returns 0; this is the backstop for anything unforeseen, and it still
    # reports rather than dying quietly.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        report("error", f"wrapper crashed: {type(exc).__name__}: {exc}")
        sys.exit(0)
