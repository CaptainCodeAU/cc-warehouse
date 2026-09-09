"""Shared fixtures and black-box helpers for the cc-warehouse oracle suite.

Oracle tests are derived from SPEC (KEEP column), DESIGN (rules R1-R14), and
FINDINGS (F1-F10 verification hooks) per HARNESS section 5. They are written
BEFORE the implementation and are expected to be red for the right reason
(missing implementation) until the corresponding slice lands. Tests invoke ccw
verbs (in-process via cc_warehouse.cli.main, or as subprocesses where process
boundaries matter) and the public module API only; never private helpers, and
nothing is ported from the specimen suite (FINDINGS F6).
"""

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "cc_warehouse"
TESTS_ROOT = Path(__file__).resolve().parent

DEFAULT_UUID = "11111111-2222-3333-4444-555555555555"
DEFAULT_CWD = "/home/alice/projects/widget"

# A pid far above any real pid_max, used to fabricate stale locks.
DEAD_PID = 999_999_999

# ---------------------------------------------------------------------------
# Audit-hook file-open counter (FINDINGS F5). Audit hooks cannot be removed,
# so one process-global hook dispatches to whichever recorders are active.
# ---------------------------------------------------------------------------

_OPEN_RECORDERS: list[tuple[str, list[str]]] = []


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event != "open" or not _OPEN_RECORDERS:
        return
    path = str(args[0])
    for prefix, sink in list(_OPEN_RECORDERS):
        if path.startswith(prefix):
            sink.append(path)


sys.addaudithook(_audit)


@contextlib.contextmanager
def record_opens(prefix: Path) -> Generator[list[str]]:
    """Record every file open under `prefix` for the duration of the block."""
    sink: list[str] = []
    rec = (str(prefix), sink)
    _OPEN_RECORDERS.append(rec)
    try:
        yield sink
    finally:
        _OPEN_RECORDERS.remove(rec)


# ---------------------------------------------------------------------------
# CLI invocation helpers
# ---------------------------------------------------------------------------

_CCW_SHIM = "import sys; from cc_warehouse.cli import main; sys.exit(main())"


@dataclass(frozen=True)
class CliResult:
    code: int
    out: str
    err: str


def run_ccw(
    args: Sequence[str],
    env: Mapping[str, str],
    stdin: str | None = None,
    timeout: float = 60,
) -> CliResult:
    """Run one ccw invocation as a real subprocess (process boundary matters)."""
    proc = subprocess.run(
        [sys.executable, "-c", _CCW_SHIM, *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=dict(env),
        timeout=timeout,
    )
    return CliResult(proc.returncode, proc.stdout, proc.stderr)


def spawn_ccw(
    args: Sequence[str],
    env: Mapping[str, str],
    stdin: str,
) -> subprocess.Popen[str]:
    """Start one ccw invocation without waiting (concurrency tests, F3)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _CCW_SHIM, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(env),
    )
    assert proc.stdin is not None
    proc.stdin.write(stdin)
    proc.stdin.close()
    return proc


def run_cli(args: Sequence[str], stdin: str | None = None) -> CliResult:
    """Run one ccw invocation in-process (enables monkeypatching and audit hooks)."""
    from cc_warehouse.cli import main

    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(list(args))
            except SystemExit as exc:  # argparse usage errors and passthroughs
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        sys.stdin = old_stdin
    return CliResult(code, out.getvalue(), err.getvalue())


# ---------------------------------------------------------------------------
# Sandboxed environment: nothing a test does may touch the real account
# ---------------------------------------------------------------------------


@pytest.fixture()
def ccw_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Sandboxed HOME, USER, and warehouse root, applied to this process and
    returned as the full environment for subprocess invocations.

    `CCW_DESKTOP_ALERTS=0` is set here for every test, real leak found and fixed
    2026-09-09: `notify.alert` fires a REAL macOS notification whenever
    `config.desktop_alerts` is true (the default) and `sys.platform == "darwin"`
    (real, on this machine) - and a `config.toml` a test writes for its OWN
    purposes never mentions this key, so the true default silently applied. Two
    fixture UUIDs/names this suite already used everywhere
    (`d3111111-2222-3333-4444-555555555551`, `zzz-probe`) leaked as two live
    desktop popups mid-session, confirmed by reading the exact code that builds
    both message strings (`capture.announce_sidecar_anomaly`). An env var
    override survives regardless of what any test's own `config.toml` says
    (env beats file, DESIGN section 8's own precedence order), which a
    same-shaped fix scoped to this fixture's own config.toml write could not:
    a per-file/per-test monkeypatch was tried first and rejected, because
    `run_ccw`-based tests spawn a REAL subprocess and an in-process monkeypatch
    cannot reach across that boundary - confirmed live by finding a THIRD,
    unmocked leak inside `test_sidecar_signal.py` itself, a file that already
    mocks `notify.alert` carefully for its OTHER (in-process, `run_cli`) tests.
    A test that wants the REAL alert behavior still can: `test_sidecar_signal.py`'s
    own `alert()` unit tests construct `Config(...)` directly, bypassing
    `load_config()` and this env var entirely, and its dedup tests monkeypatch
    `notify.alert` itself, which never reads this flag either way."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    root = tmp_path / "warehouse"
    env = {
        "HOME": str(home),
        "USER": "alice",
        "PATH": os.environ.get("PATH", ""),
        "CCW_ROOT": str(root),
        "CCW_DESKTOP_ALERTS": "0",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CCW_SKIP_HOOK", raising=False)
    # An ambient XDG_CONFIG_HOME (real machines rarely set one; GitHub's
    # ubuntu-latest runner does) would otherwise outrank config.py's own
    # $HOME/.config fallback for every in-process run_cli() call, sending it
    # to a real directory instead of this sandbox's. The ~23 test helpers
    # across this suite that write a config.toml under $HOME/.config and set
    # env["XDG_CONFIG_HOME"] to match are all trying to guarantee exactly
    # this - they set it on a subprocess-only dict, never on the real
    # process env, so it silently never took effect for run_cli() at all.
    # Found 2026-09-06: 22 tests failed only on GitHub CI for this reason.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return env


def warehouse_root(env: Mapping[str, str]) -> Path:
    return Path(env["CCW_ROOT"])


def claude_projects(env: Mapping[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects"


# ---------------------------------------------------------------------------
# Session payload builders (Claude Code JSONL shapes)
# ---------------------------------------------------------------------------


def entry(
    kind: str,
    content: object,
    ts: str,
    *,
    session_id: str = DEFAULT_UUID,
    cwd: str | None = DEFAULT_CWD,
    **extra: object,
) -> dict[str, object]:
    e: dict[str, object] = {
        "type": kind,
        "timestamp": ts,
        "sessionId": session_id,
        "message": {"role": kind, "content": content},
    }
    if cwd is not None:
        e["cwd"] = cwd
    e.update(extra)
    return e


def jsonl(*entries: Mapping[str, object] | str) -> bytes:
    """Serialize entries to JSONL; a plain string is emitted verbatim (malformed lines)."""
    out = b""
    for e in entries:
        if isinstance(e, str):
            out += e.encode() + b"\n"
        else:
            out += json.dumps(e).encode() + b"\n"
    return out


def basic_session(
    cwd: str = DEFAULT_CWD,
    session_id: str = DEFAULT_UUID,
    prompt: str = "Please fix the flux capacitor",
) -> bytes:
    return jsonl(
        entry(
            "user",
            prompt,
            "2026-01-05T10:00:00.000Z",
            session_id=session_id,
            cwd=cwd,
            gitBranch="main",
            slug="fix-flux",
            version="2.0.0",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done. The capacitor now fluxes."}],
            "2026-01-05T10:00:05.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
    )


def rich_session(cwd: str = DEFAULT_CWD, session_id: str = DEFAULT_UUID) -> bytes:
    """A session exercising the full render surface: thinking, tools, commits,
    system reminders, task notifications, compact continuation, stop-hook prompt."""
    reminder = "<system-reminder>secret internal reminder text</system-reminder>"
    return jsonl(
        entry(
            "user",
            f"First real prompt about widgets\n{reminder}",
            "2026-01-05T10:00:00.000Z",
            session_id=session_id,
            cwd=cwd,
            gitBranch="main",
            slug="widget-work",
            version="2.0.0",
        ),
        entry(
            "assistant",
            [
                {"type": "thinking", "thinking": "deep thoughts about widgets"},
                {"type": "text", "text": "Working on it."},
                {
                    "type": "tool_use",
                    "id": "tu1",
                    "name": "Bash",
                    "input": {"command": "git commit -m widget", "description": "Commit"},
                },
            ],
            "2026-01-05T10:00:05.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "user",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu1",
                    "content": "[main abc1234] add widget frobnicator\n 1 file changed",
                }
            ],
            "2026-01-05T10:00:06.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "assistant",
            [
                {
                    "type": "tool_use",
                    "id": "tu2",
                    "name": "Edit",
                    "input": {
                        "file_path": "/home/alice/projects/widget/w.py",
                        "old_string": "old_widget()",
                        "new_string": "new_widget()",
                    },
                },
            ],
            "2026-01-05T10:00:06.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "user",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu2",
                    "content": (
                        "remote: Create a pull request for 'main' on GitHub by visiting:\n"
                        "remote:   https://github.com/alice/widget/pull/new/main"
                    ),
                }
            ],
            "2026-01-05T10:00:07.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "user",
            "<task-notification>background task finished</task-notification>",
            "2026-01-05T10:00:08.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "user",
            "Stop hook feedback: some hook output",
            "2026-01-05T10:00:09.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "user",
            "Continued conversation summary here",
            "2026-01-05T10:00:10.000Z",
            session_id=session_id,
            cwd=cwd,
            isCompactSummary=True,
        ),
        entry(
            "user",
            "Second real prompt: now document it\nwith a list:\n- alpha\n- beta",
            "2026-01-05T10:01:00.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Documented. Trailing fence follows:\n```"}],
            "2026-01-05T10:01:05.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
    )


def matrix_session(cwd: str = DEFAULT_CWD, session_id: str = DEFAULT_UUID) -> bytes:
    """A session carrying one block of EVERY per-variant content class (slice 14).

    rich_session covers thinking, tools, commits and reminders but emits no
    sub-agent, attachment, command or extra block, so it cannot exercise the
    variant x toggle matrix. Each class here carries a unique marker string, so a
    test asserts on presence rather than on layout, and the four rendered files
    are the byte-identical regression anchor for the whole v1.1 flag-group run
    (DESIGN section 15, 2026-08-01, shared rule b).
    """

    def raw(kind: str, ts: str, **extra: object) -> dict[str, object]:
        record: dict[str, object] = {
            "type": kind,
            "timestamp": ts,
            "sessionId": session_id,
            "cwd": cwd,
        }
        record.update(extra)
        return record

    return jsonl(
        entry(
            "user",
            "Prompt about widgets",
            "2026-01-05T10:00:00.000Z",
            session_id=session_id,
            cwd=cwd,
            gitBranch="main",
            slug="widget-work",
            version="2.0.0",
        ),
        entry(
            "assistant",
            [
                {"type": "thinking", "thinking": "deep thoughts about widgets"},
                {"type": "text", "text": "Working on it."},
                {
                    "type": "tool_use",
                    "id": "tu1",
                    "name": "Bash",
                    "input": {"command": "ls widgets", "description": "List widgets"},
                },
            ],
            "2026-01-05T10:00:05.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
        entry(
            "user",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu1",
                    "content": "TOOLRAWMARKER alpha beta",
                }
            ],
            "2026-01-05T10:00:06.000Z",
            session_id=session_id,
            cwd=cwd,
            # The structured payload matters: the unsuffixed `tool_output` key
            # chooses between THIS rendering and the raw text fence above, so a
            # fixture without it cannot observe that key at all.
            toolUseResult={"stdout": "TOOLSTDOUTMARKER alpha", "stderr": "TOOLSTDERRMARKER"},
        ),
        raw(
            "user",
            "2026-01-05T10:00:07.000Z",
            isSidechain=True,
            agentId="scout",
            message={"role": "user", "content": "SUBAGENTMARKER investigate the widget"},
        ),
        raw(
            "assistant",
            "2026-01-05T10:00:08.000Z",
            isSidechain=True,
            agentId="scout",
            message={
                "role": "assistant",
                "content": [{"type": "text", "text": "SUBAGENTREPLY found it"}],
            },
        ),
        raw(
            "attachment",
            "2026-01-05T10:00:09.000Z",
            attachment={
                "type": "file",
                "filename": "ATTACHMARKER.txt",
                "content": {"file": {"content": "attachment body line"}},
            },
        ),
        raw(
            "system",
            "2026-01-05T10:00:10.000Z",
            subtype="local_command",
            content="/COMMANDMARKER --flag",
        ),
        raw("agent-name", "2026-01-05T10:00:11.000Z", agentName="EXTRAMARKER"),
        entry(
            "assistant",
            [{"type": "text", "text": "All done."}],
            "2026-01-05T10:00:12.000Z",
            session_id=session_id,
            cwd=cwd,
        ),
    )


def subagent_session(
    agent_id: str = "a94d30c1d877f964d",
    parent_uuid: str = DEFAULT_UUID,
    cwd: str = DEFAULT_CWD,
    prompt: str = "You are a REUSE-focused reviewer. Review ONLY the diff below.",
) -> bytes:
    """A sub-agent transcript, in the shape real ones have (measured 2026-08-03).

    THE FIELD THAT MATTERS: `sessionId` is the PARENT'S uuid, not the agent's.
    All 1,420 real sub-agent files carry one, so the ruling-(a) test "a file is a
    session if any entry carries a sessionId" says YES to every one of them. That
    is why identity has to key on `agentId`, and why feeding one of these to the
    session writer would land it in the parent's folder under the parent's name.

    `parentUuid`, `agentId`, `timestamp`, `cwd`, `gitBranch` and `version` are
    all present on every entry in the real files.
    """

    def line(role: str, content: object, ts: str) -> dict[str, object]:
        return {
            "type": role,
            "timestamp": ts,
            "sessionId": parent_uuid,  # the PARENT's, deliberately
            "parentUuid": parent_uuid,
            "agentId": agent_id,
            "cwd": cwd,
            "gitBranch": "main",
            "version": "2.1.220",
            "message": {"role": role, "content": content},
        }

    return jsonl(
        line("user", prompt, "2026-05-07T04:00:00.000Z"),
        line(
            "assistant",
            [
                {"type": "text", "text": "I'll analyze this diff for reuse opportunities."},
                {"type": "tool_use", "id": "t1", "name": "Grep", "input": {"pattern": "escape"}},
            ],
            "2026-05-07T04:00:05.000Z",
        ),
        line(
            "user",
            [{"type": "tool_result", "tool_use_id": "t1", "content": "AGENTTOOLRESULT"}],
            "2026-05-07T04:00:06.000Z",
        ),
        line(
            "assistant",
            [{"type": "text", "text": "AGENTFINDING three helpers already exist."}],
            "2026-05-07T04:00:10.000Z",
        ),
    )


def subagent_meta(
    agent_type: str = "Explore", description: str = "Inspect verify hook + reparse path"
) -> bytes:
    """The `.meta.json` Claude Code writes beside each sub-agent transcript. It is
    the ONLY record of what the agent was, so it travels with the payload."""
    return json.dumps(
        {"agentType": agent_type, "description": description, "toolUseId": "toolu_01Ngfw"},
        indent=2,
    ).encode("utf-8") + b"\n"


def write_transcript(
    env: Mapping[str, str],
    data: bytes,
    *,
    session_id: str = DEFAULT_UUID,
    encoded_dir: str = "-home-alice-projects-widget",
    name: str | None = None,
) -> Path:
    """Place a transcript where Claude Code would: ~/.claude/projects/<encoded>/<uuid>.jsonl."""
    project_dir = claude_projects(env) / encoded_dir
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / (name if name is not None else f"{session_id}.jsonl")
    path.write_bytes(data)
    return path


def hook_payload(
    transcript: Path,
    cwd: str | None = DEFAULT_CWD,
    session_id: str = DEFAULT_UUID,
) -> str:
    payload: dict[str, object] = {
        "session_id": session_id,
        "transcript_path": str(transcript),
    }
    if cwd is not None:
        payload["cwd"] = cwd
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Catalog access (reading the SQLite file directly is the black-box read path)
# ---------------------------------------------------------------------------


def catalog_path(env: Mapping[str, str]) -> Path:
    return warehouse_root(env) / "catalog.sqlite"


def catalog_rows(env: Mapping[str, str], sql: str, params: Sequence[object] = ()) -> list[object]:
    db = catalog_path(env)
    assert db.exists(), f"catalog missing at {db}"
    with sqlite3.connect(db) as conn:
        return list(conn.execute(sql, tuple(params)).fetchall())


def session_count(env: Mapping[str, str]) -> int:
    if not catalog_path(env).exists():
        return 0
    rows = catalog_rows(env, "SELECT COUNT(*) FROM session")
    first = cast(tuple[int], rows[0])
    return first[0]


# ---------------------------------------------------------------------------
# Filesystem snapshots (read-only-source proofs, F9)
# ---------------------------------------------------------------------------


def settle_render(root: Path, expected: int, timeout: float = 30.0) -> None:
    """Wait until `expected` capture hooks' DETACHED RENDER CHILDREN have finished.

    THE RACE THIS CLOSES, measured 2026-09-08 rather than reasoned about. The hook
    renders in a detached child (SPEC 2.5/5), so `ccw hook` returns BEFORE any
    projection exists. Probed directly: 0 files under `projections/` the instant
    the hook returned, 7 files five seconds later. Any test that snapshots the
    warehouse right after a capture is therefore comparing against a tree that is
    still being written, and the second snapshot legitimately has MORE in it.

    It is not a new race and it is not about anything ticket 38 changed: the same
    probe showed `ccw archive --to` leaving the source warehouse byte-identical.
    It was simply always won locally and always lost on a slower CI runner once
    capture got a little slower. A sleep would trade one flake for another, so
    this polls for the actual finished state and fails loudly on a timeout rather
    than letting a genuinely stuck child pass as "settled".

    TWO CONDITIONS, because neither alone is enough. `expected` is a FLOOR, not a
    count: two payloads carrying the same `sessionId` render into ONE folder, so a
    caller cannot always know the exact number, but it always knows at least one
    must appear. That floor rules out "settled" firing before any child has
    started. The quiet period then rules out stopping between two children.
    """
    deadline = time.monotonic() + timeout
    projections = root / "projections"
    quiet_for = 0.5
    stable_since: float | None = None
    seen: set[str] = set()
    while time.monotonic() < deadline:
        folders = {
            str(d)
            for d in projections.glob("*/*")
            if d.is_dir() and (d / "manifest.json").is_file()
        }
        if folders != seen:
            seen = folders
            stable_since = None
        elif stable_since is None:
            stable_since = time.monotonic()
        if (
            len(seen) >= expected
            and stable_since is not None
            and time.monotonic() - stable_since >= quiet_for
        ):
            return
        time.sleep(0.05)
    raise AssertionError(
        f"render children did not settle within {timeout}s under {projections}"
        f" (saw {len(seen)} folder(s), wanted at least {expected})"
    )


def settle_companions(env: Mapping[str, str], expected: int = 1, timeout: float = 30.0) -> None:
    """Wait until `expected` capture hooks' DETACHED COMPANIONS CHILDREN have finished.

    Ticket 37 Part B moved companion-copying (sub-agents, tool-results/workflows
    sidecars, file-history/todos, the unknown-sibling notice) out of the hook and
    into a detached child, the same shape `settle_render` above already waits
    for. `ccw hook` returns before that child has written anything, so a test
    that fires the hook and immediately reads archived companion content is
    racing a process that has not started yet.

    No quiet period is needed here, unlike `settle_render`: each companions
    child writes exactly one `companions-done` line to `logs/capture.jsonl`
    when it finishes (`cli._log_companions`), and that line is a genuine
    terminal signal rather than a filesystem snapshot that can catch a child
    mid-write. `expected` is a floor on how many hook fires should have spawned
    a fresh companions child - a fire on unchanged transcript bytes is skipped
    before it ever reaches `archive_companions`, so it spawns none and does not
    count.
    """
    log = warehouse_root(env) / "logs" / "capture.jsonl"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.is_file():
            done = 0
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    record = cast(object, json.loads(line))
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    typed = cast(dict[str, object], record)
                    if typed.get("status") == "companions-done":
                        done += 1
            if done >= expected:
                return
        time.sleep(0.05)
    raise AssertionError(
        f"companions children did not settle within {timeout}s under {log}"
        f" (wanted at least {expected} 'companions-done' line(s))"
    )


def tree_snapshot(root: Path) -> dict[str, bytes]:
    """Every file under root with its exact bytes; directory set included as keys."""
    snap: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir():
            snap[rel + "/"] = b""
        elif path.is_file():
            snap[rel] = path.read_bytes()
    return snap


# ---------------------------------------------------------------------------
# Plugin hook scripts (plugins/cc-capture/hooks/*.py are standalone scripts,
# not a package, so tests import them by path)
# ---------------------------------------------------------------------------

HOOKS_DIR = REPO_ROOT / "plugins" / "cc-capture" / "hooks"


class UrlopenStub:
    """Stands in for the object `urllib.request.urlopen` returns. Both hooks
    report trouble with `urlopen(request, timeout=3).close()` and nothing
    else, so `.close()` is the whole contract. Shared rather than copied:
    the two hook test files each grew their own identical copy, and if a hook
    ever starts reading the response body they must not drift apart."""

    def close(self) -> None:
        return None


def load_hook_module(name: str, filename: str) -> ModuleType:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
