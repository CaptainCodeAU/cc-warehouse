"""Oracle tests: the SessionEnd wrapper hands `ccw hook` to a DETACHED runner and
returns at once (W-20261001-A65, folding in W-20260929-A127).

THE KILL THIS CLOSES, measured 2026-10-01 with a `claude -p` probe on Claude
Code 2.1.286: a PLUGIN hook's `timeout` does not raise Claude Code's SessionEnd
budget; only a settings-file hook's does. Outside a pj session the budget is
about 1.5 s; in one it is 10 s (pj's own settings-file hook asks for 10). Then
SIGTERM goes to the hook's process group, and `ccw hook` dies with it. Two live
sessions that night reached the archive in full and were killed before the
catalog row, leaving a `started` with nothing after it.

So these tests run the wrapper as a REAL process, the way Claude Code does, and
fake only `ccw` (CCW_BIN) and the voice server (CCW_VOICE_URL). HOME points into
the test's scratch dir, so the log is never the real `~/.claude/logs`.
"""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from conftest import HOOKS_DIR

WRAPPER = HOOKS_DIR / "ccw-hook.py"
SESSION = "detach-0001"


def _home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _log(tmp_path: Path) -> Path:
    return _home(tmp_path) / ".claude" / "logs" / "ccw-hook.log"


def _lines(tmp_path: Path) -> list[dict[str, object]]:
    path = _log(tmp_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _statuses(tmp_path: Path, session: str = SESSION) -> list[object]:
    return [line["status"] for line in _lines(tmp_path) if line["session"] == session]


def _fake_ccw(tmp_path: Path, body: str) -> Path:
    """A `ccw` that copies its stdin to `payload-<pid>` beside itself, then runs
    `body` (sh). `marker` is where a completed run says so."""
    fake = tmp_path / "ccw"
    fake.write_text(
        "#!/bin/sh\n"
        f'cat > "{tmp_path}/payload-$$"\n'
        f"{body}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def _env(tmp_path: Path, ccw: Path | None) -> dict[str, str]:
    env = {
        "HOME": str(_home(tmp_path)),
        "PATH": "/usr/bin:/bin",
        "CCW_VOICE_URL": "http://127.0.0.1:9/never",
    }
    if ccw is not None:
        env["CCW_BIN"] = str(ccw)
    return env


def _payload(session: str = SESSION, reason: str = "prompt_input_exit") -> str:
    return json.dumps(
        {
            "session_id": session,
            "transcript_path": f"/x/{session}.jsonl",
            "hook_event_name": "SessionEnd",
            "reason": reason,
        }
    )


def _wait_for(predicate: Callable[[], bool], seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_the_wrapper_returns_in_under_a_second_while_ccw_takes_five(tmp_path: Path) -> None:
    ccw = _fake_ccw(tmp_path, f'sleep 5\ntouch "{tmp_path}/marker"\necho "ok: captured"')
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(WRAPPER)],
        input=_payload(),
        text=True,
        env=_env(tmp_path, ccw),
        capture_output=True,
        timeout=30,
        check=False,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert elapsed < 1.0, f"wrapper took {elapsed:.2f}s; Claude Code kills it at ~1.5s"
    # And the work still happens, after the wrapper has gone.
    assert _wait_for(lambda: (tmp_path / "marker").exists())
    assert _wait_for(lambda: "ok" in _statuses(tmp_path))


def test_sigterm_to_the_hooks_process_group_does_not_stop_the_capture(tmp_path: Path) -> None:
    """What Claude Code does at its SessionEnd budget: SIGTERM to the hook's
    process group (the hook is its own group leader, pgid == pid, measured
    2026-10-01). The wrapper is started the same way here, and the group is
    killed at 1.5 s whether or not the wrapper has returned by then."""
    ccw = _fake_ccw(tmp_path, f'sleep 2\ntouch "{tmp_path}/marker"\necho "ok: captured"')
    hook = subprocess.Popen(
        [sys.executable, str(WRAPPER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=_env(tmp_path, ccw),
        start_new_session=True,
    )
    assert hook.stdin is not None
    hook.stdin.write(_payload())
    hook.stdin.close()
    try:
        hook.wait(timeout=1.5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(hook.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # the whole group has already gone, which is the point
    hook.wait(timeout=5)

    assert _wait_for(lambda: (tmp_path / "marker").exists()), "ccw hook was killed with the group"
    assert _wait_for(lambda: "ok" in _statuses(tmp_path))


def test_the_runner_does_not_hold_the_hooks_stdout_or_stderr_open(tmp_path: Path) -> None:
    """Claude Code reads the hook's stdout and stderr. A runner that inherited
    them would keep both pipes open for as long as `ccw hook` runs, so EOF on
    them must arrive as soon as the wrapper itself exits."""
    ccw = _fake_ccw(tmp_path, f'sleep 5\ntouch "{tmp_path}/marker"\necho "ok: captured"')
    hook = subprocess.Popen(
        [sys.executable, str(WRAPPER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(tmp_path, ccw),
    )
    started = time.monotonic()
    hook.communicate(_payload().encode("utf-8"), timeout=30)  # returns at EOF on both pipes
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, f"the hook's pipes stayed open {elapsed:.2f}s"
    assert _wait_for(lambda: (tmp_path / "marker").exists())
