"""Oracle tests: `ccw doctor` (ticket 23, slice 23c).

Contract: DESIGN section 7 (`ccw doctor` row, added 2026-08-03) and section 15
entry "`ccw doctor`, AND WHY IT IS A VERB".

THE FAILURE IT EXISTS FOR. Capture stopped on 2026-07-24 and nobody found out
for ten days. Every link an operator would check looked healthy: the plugin was
enabled, its cached files were byte-identical to their repo copies, and the CLI
it delegated to existed and still exposed the verb being called. Nothing in the
product could say otherwise, because `ccw status` reads the catalog and a hook
that never runs writes no row and raises no error. Silence read as idleness.

TWO PROPERTIES THIS FILE PINS, and they pull against each other:

  1. doctor must FAIL when capture is broken, or it is decoration
  2. doctor must not cry wolf, or it gets ignored, which is the same thing

So the exit code keys on structural breakage (no hook, never fired) plus
OVERDUE sessions: uncaptured sessions whose own payload says they last did
anything more than a day ago. A session still being written is not overdue, so
running doctor mid-session is quiet. Staleness is read from the payload's last
timestamp, never from an mtime (R12).

READ-ONLY BY CONSTRUCTION, and proved by snapshot rather than asserted. Exit 0
plus output is not evidence that nothing happened (2026-08-01).
"""

import json
from pathlib import Path

from conftest import (
    basic_session,
    entry,
    jsonl,
    run_ccw,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
OLD = "2020-01-01T00:00:00.000Z"


def configure(env: dict[str, str], archive_root: Path | None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def install_hook(env: dict[str, str], *, command: str = "ccw hook") -> None:
    """A SessionEnd hook in settings.json, the shape Claude Code reads."""
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": command}]}]}}
        ),
        encoding="utf-8",
    )


def stale_session(session_id: str) -> bytes:
    """A session whose own payload says it last did anything in 2020."""
    return jsonl(
        entry("user", "hello", OLD, session_id=session_id),
        entry("assistant", "hi", OLD, session_id=session_id),
    )


# ---------------------------------------------------------------------------
# read-only
# ---------------------------------------------------------------------------


def test_doctor_creates_no_warehouse(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """THE LOAD-BEARING TEST. doctor runs when things are broken, which is
    exactly when it must not make the mess worse by materialising a warehouse
    that was never there."""
    configure(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    root = warehouse_root(ccw_env)
    assert not root.exists(), "fixture precondition"

    run_ccw(["doctor"], ccw_env)

    assert not root.exists(), (
        f"doctor created the warehouse: {sorted(p.name for p in root.rglob('*'))}"
    )


def test_doctor_writes_nothing_anywhere(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Snapshot HOME, not just the warehouse: doctor reads settings.json and the
    source tree, and a diagnostic that edits what it inspects is worthless."""
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    home = Path(ccw_env["HOME"])
    before = tree_snapshot(home)

    run_ccw(["doctor"], ccw_env)

    assert tree_snapshot(home) == before, "doctor mutated something under HOME"


# ---------------------------------------------------------------------------
# it fails when capture is broken
# ---------------------------------------------------------------------------


def test_no_hook_registered_is_a_failure(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The state this machine was actually in: zero ccw references in
    settings.json, and every one of 13,836 sessions imported by hand."""
    configure(ccw_env, tmp_path / "archive")

    result = run_ccw(["doctor"], ccw_env)

    assert result.code != 0, f"a missing hook exited 0: {result.out!r}"
    assert "hook" in result.out.lower()


def test_a_registered_hook_is_reported_as_found(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)

    result = run_ccw(["doctor"], ccw_env)

    hook_line = next((ln for ln in result.out.splitlines() if "hook" in ln.lower()), "")
    assert "SessionEnd" in hook_line or "found" in hook_line.lower(), hook_line


def test_a_plugin_hook_that_calls_a_WRAPPER_is_still_found(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE FALSE ALARM THIS PREVENTS. A Claude Code plugin registers its hook as
    a command that runs a SCRIPT, so the string Claude Code stores is
    `python3 .../hooks/ccw-hook.py` and the word `ccw` may appear nowhere in it.

    Matching the command string alone made doctor report NO HOOK REGISTERED while
    capture was working perfectly. An instrument that cries wolf gets ignored,
    which is the same outcome as having no instrument, which is what this whole
    ticket exists to fix. So doctor follows the command to the script and reads
    it.
    """
    configure(ccw_env, tmp_path / "archive")
    plugin = (
        Path(ccw_env["HOME"]) / ".claude" / "plugins" / "cache" / "mp" / "p" / "v1"
    )
    (plugin / "hooks").mkdir(parents=True)
    wrapper = plugin / "hooks" / "some-wrapper.py"
    wrapper.write_text("import subprocess\nsubprocess.run(['ccw','hook'])\n", encoding="utf-8")
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {"hooks": [{"type": "command", "command": f"python3 {wrapper}"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "NO capture hook" not in hook_line, (
        f"a working plugin wrapper was reported as missing: {hook_line!r}"
    )


def test_a_ccw_looking_command_in_another_event_is_not_claimed_as_the_hook(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE REGRESSION THIS PINS (found 2026-08-18). `_hook_commands` used to
    walk every event key in settings.json, not just SessionEnd, and
    `diagnose()` labelled whatever it found FIRST as "the SessionEnd capture
    hook". A machine can have a legitimate, unrelated SessionStart command
    whose text merely CONTAINS "ccw" -- a monitoring script named
    `ccw-watch`, say -- and it outranked the real SessionEnd hook because
    settings.json's own key order put SessionStart first. Doctor then said ok
    for the wrong hook: a false green that would survive the real one being
    removed entirely.
    """
    configure(ccw_env, tmp_path / "archive")
    settings = Path(ccw_env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "ccw-watch"}]}
                    ],
                    "SessionEnd": [
                        {"hooks": [{"type": "command", "command": "ccw hook"}]}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "ccw-watch" not in hook_line, (
        f"a SessionStart command was reported as the SessionEnd hook: {hook_line!r}"
    )
    assert "ccw hook" in hook_line, hook_line


def test_an_unrelated_plugin_hook_is_not_claimed_as_ours(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The other half of the same property. Following the script must not turn
    every plugin on the machine into evidence that capture is configured."""
    configure(ccw_env, tmp_path / "archive")
    plugin = (
        Path(ccw_env["HOME"]) / ".claude" / "plugins" / "cache" / "other" / "p" / "v1"
    )
    (plugin / "hooks").mkdir(parents=True)
    wrapper = plugin / "hooks" / "lint.py"
    wrapper.write_text("print('tidying imports')\n", encoding="utf-8")
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {"hooks": [{"type": "command", "command": f"python3 {wrapper}"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_ccw(["doctor"], ccw_env)

    assert result.code != 0, "an unrelated plugin was counted as a capture hook"


def test_never_fired_is_distinct_from_fired_but_not_recently(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The 2026-07-24 failure LOOKED like the second and WAS the first. Reporting
    them the same way is how ten days passed."""
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)

    def fired_line(out: str) -> str:
        # The `fired` CHECK line only. Scanning the whole output would be fooled
        # by pytest's tmp_path, which contains this test's own name and therefore
        # the word "never" (found the hard way).
        return next((ln for ln in out.splitlines() if " fired " in ln), "")

    never = run_ccw(["doctor"], ccw_env)
    assert "never" in fired_line(never.out).lower(), never.out

    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    fired = run_ccw(["doctor"], ccw_env)

    assert "never" not in fired_line(fired.out).lower(), fired.out
    assert "last capture" in fired_line(fired.out).lower(), fired.out


def test_an_overdue_session_fails(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """A session whose payload says it last did anything in 2020 and which is
    still not archived is not 'about to be swept'. It was missed."""
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    write_transcript(ccw_env, stale_session(UUID_B), session_id=UUID_B)

    result = run_ccw(["doctor"], ccw_env)

    assert result.code != 0, f"an overdue session exited 0: {result.out!r}"
    assert "overdue" in result.out.lower(), result.out


# ---------------------------------------------------------------------------
# it does not cry wolf
# ---------------------------------------------------------------------------


def test_a_healthy_warehouse_exits_zero(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Hook registered, has fired, nothing overdue: quiet success. A check that
    fails constantly is one nobody reads."""
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    result = run_ccw(["doctor"], ccw_env)

    assert result.code == 0, f"healthy warehouse failed: {result.out}\n{result.err}"


def test_a_fresh_uncaptured_session_is_not_overdue(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Running doctor DURING a session must be quiet. basic_session carries a
    recent timestamp, so it is uncaptured but not yet missed."""
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    write_transcript(ccw_env, basic_session(session_id=UUID_B), session_id=UUID_B)

    result = run_ccw(["doctor"], ccw_env)

    assert result.code == 0, f"a fresh session was called overdue: {result.out}"


# ---------------------------------------------------------------------------
# what it reports
# ---------------------------------------------------------------------------


def test_doctor_names_the_resolved_ccw_and_the_effective_config(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """"Found" is not enough: the 2026-07-24 failure was a NAME resolving to the
    wrong program, so the path and the effective config both have to be shown."""
    archive = tmp_path / "archive"
    configure(ccw_env, archive)
    install_hook(ccw_env)

    result = run_ccw(["doctor"], ccw_env)

    assert str(archive) in result.out, f"archive_root not shown: {result.out!r}"
    assert str(warehouse_root(ccw_env)) in result.out, f"root not shown: {result.out!r}"


def test_doctor_reports_the_uncaptured_gap(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The same figure `status` prints, from the same function (R9)."""
    configure(ccw_env, tmp_path / "archive")
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)

    result = run_ccw(["doctor"], ccw_env)

    assert "uncaptured" in result.out.lower(), result.out
