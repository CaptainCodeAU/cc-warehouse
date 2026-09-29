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
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cc_warehouse import archive, doctor
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    entry,
    jsonl,
    mark_archive,
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
    if archive_root is not None:
        mark_archive(archive_root, ZONE)


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
    _write_enabled_plugins(ccw_env, {"p@mp": True})

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


def _write_plugin_hook(env: dict[str, str], marketplace: str, plugin: str, version: str) -> None:
    root = (
        Path(env["HOME"]) / ".claude" / "plugins" / "cache" / marketplace / plugin / version
    )
    (root / "hooks").mkdir(parents=True)
    (root / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "hooks" / "ccw-hook.py").write_text(
        "import subprocess\nsubprocess.run(['ccw', 'hook'])\n", encoding="utf-8"
    )


def _write_enabled_plugins(env: dict[str, str], enabled: dict[str, bool]) -> None:
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"enabledPlugins": enabled}), encoding="utf-8")


def test_a_retired_plugins_leftover_cache_is_not_claimed_as_the_hook(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE REAL MISTAKE THIS PINS (found 2026-08-23): a plugin's cached
    hooks.json can outlive its removal from Claude Code entirely. Ticket 28.19
    moved capture from `claude-transcript-exporter@gz-claude-code-plugins`
    into `cc-capture@cc-warehouse`; the old plugin's cache directory can stay
    on disk with a perfectly valid ccw-calling hooks.json, byte-identical in
    shape to a real one, while `~/.claude/settings.json`'s `enabledPlugins`
    carries no entry for it at all - Claude Code will never invoke it. Before
    this fix, `_hook_commands` globbed the cache blind to `enabledPlugins`
    and would have reported this orphaned plugin as a working capture hook."""
    configure(ccw_env, tmp_path / "archive")
    _write_plugin_hook(ccw_env, "gz-claude-code-plugins", "claude-transcript-exporter", "old1")
    _write_enabled_plugins(ccw_env, {})  # the retired plugin has NO entry at all

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "NO capture hook" in hook_line, (
        f"an unenabled plugin's leftover cache was counted as the hook: {hook_line!r}"
    )


def test_an_explicitly_disabled_plugins_cache_is_not_claimed_as_the_hook(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The other half: an explicit `false`, not just an absent key."""
    configure(ccw_env, tmp_path / "archive")
    _write_plugin_hook(ccw_env, "mp", "old-capture", "v1")
    _write_enabled_plugins(ccw_env, {"old-capture@mp": False})

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "NO capture hook" in hook_line, (
        f"an explicitly disabled plugin's cache was counted as the hook: {hook_line!r}"
    )


def test_an_enabled_plugins_cache_is_still_claimed_as_the_hook(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The positive case, so the fix above cannot be satisfied by rejecting
    every plugin-sourced hook: a real, currently-enabled plugin still counts."""
    configure(ccw_env, tmp_path / "archive")
    _write_plugin_hook(ccw_env, "cc-warehouse", "cc-capture", "abc123")
    _write_enabled_plugins(ccw_env, {"cc-capture@cc-warehouse": True})

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "NO capture hook" not in hook_line, (
        f"an enabled plugin's hook was not recognized: {hook_line!r}"
    )
    assert "cc-capture@cc-warehouse" in hook_line, (
        f"doctor found the hook but did not name which plugin serves it: {hook_line!r}"
    )


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


# ---------------------------------------------------------------------------
# desync (ticket 31.5): a cheap check for exactly the failure the daily sweep
# hit once (JSONL archived, catalog row/render/notification never happened)
# ---------------------------------------------------------------------------


def _tamper(folder: Path) -> None:
    """Break one archive folder's JSONL-vs-manifest agreement (a real desync)."""
    jsonl_path = next(folder.glob("*.jsonl"))
    jsonl_path.write_bytes(jsonl_path.read_bytes() + b'{"type":"other","extra":true}\n')


def test_a_tampered_archive_folder_fails_doctor_without_a_full_verify(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`verify_folder`'s exact check ("JSONL does not match manifest source_hash") found
    the ticket 31 folder immediately once run by hand; this pins that doctor now runs it
    itself, at SessionStart, with no operator having to think to ask for it."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    folder = next(archive.walk_folders(archive_root))
    _tamper(folder)

    result = run_ccw(["doctor"], ccw_env)

    assert result.code != 0, f"a tampered archive folder exited 0: {result.out!r}"
    assert "desync" in result.out.lower(), result.out
    assert folder.name in result.out, result.out


def test_desync_check_is_bounded_to_the_recent_sample(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELIBERATE SCOPE (recorded in `_desync`'s docstring): the sample is the most
    RECENTLY STARTED folders, so an old, long-standing desync outside it is invisible to
    this check on purpose -- catching it is `ccw archive --verify`'s job, not doctor's.
    Pinned directly against `doctor._desync` (in-process) because the sample size is a
    module constant, not a flag a subprocess run can override."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    write_transcript(ccw_env, basic_session(session_id=UUID_B), session_id=UUID_B)
    assert run_ccw(["sweep"], ccw_env).code == 0

    folders = {f.name.rpartition("_")[2]: f for f in archive.walk_folders(archive_root)}
    _tamper(folders[UUID_A])  # the OLDER (2020) session -- outside a sample of 1

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    monkeypatch.setattr(doctor, "_DESYNC_SAMPLE", 1)
    checked, problems, _pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1, "sample size was not respected"
    assert problems == 0, "an out-of-sample desync was caught; the scope decision changed"

    monkeypatch.setattr(doctor, "_DESYNC_SAMPLE", 25)
    checked, problems, _pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 2
    assert problems >= 1, "the same desync, back in-sample, was missed"
    assert first is not None and UUID_A in first


# ---------------------------------------------------------------------------
# Ticket 34: pending (still rendering) vs. a genuine problem
# ---------------------------------------------------------------------------


def _age_capture(env: dict[str, str], uuid: str, *, seconds_ago: int) -> None:
    """Move a catalog row's captured_at into the past (test-only, scratch catalog)."""
    import sqlite3

    stamp = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    conn = sqlite3.connect(warehouse_root(env) / "catalog.sqlite")
    try:
        with conn:
            conn.execute("UPDATE session SET captured_at = ? WHERE session_uuid = ?", (stamp, uuid))
    finally:
        conn.close()


def _break_render(folder: Path) -> None:
    """Simulate a folder whose generated pages have not landed yet: the JSONL
    arrives (the hook's synchronous, safe half); none of the five generated
    files do (the render half, whether still queued or genuinely failed)."""
    for name in archive.GENERATED_NAMES:
        path = folder / name
        if path.exists():
            path.unlink()


def test_an_old_missing_render_with_no_batch_running_is_still_a_real_problem(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Negative case, the one that matters most: a genuinely broken folder
    (old capture, no sweep/build lock held) must still fail doctor. Proves the
    pending carve-out did not quietly widen into "any missing render passes"."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)
    # Ticket 44c: "old" means CAPTURED long ago, not "a session that happened long
    # ago". The grace window is measured from the catalog's captured_at, so a 2020
    # session swept just now would legitimately be pending; age the capture itself.
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert pending == 0, "an old, genuinely broken folder was wrongly excused as pending"
    assert problems >= 1, "a real desync was suppressed"
    assert first is not None and folder.name in first


def fresh_session(session_id: str) -> bytes:
    """A session whose own payload timestamp is close to actual wall-clock
    now, unlike `basic_session` (fixed at 2026-01-05, long outside any grace
    window by the time this suite runs) -- needed to exercise the grace-window
    carve-out, which keys on real elapsed time, not a small fixed test date."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return jsonl(
        entry("user", "hello", now, session_id=session_id),
        entry("assistant", "hi", now, session_id=session_id),
    )


def test_a_freshly_captured_missing_render_is_pending_not_a_problem(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The grace-window carve-out: a folder captured moments ago (payload
    timestamp near now, not backdated like `stale_session`) with no render
    files yet must not fail doctor -- it is still inside the live hook's own
    single-session render window, no lock involved at all."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)  # so only the desync check under test can fail report.ok
    write_transcript(ccw_env, fresh_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    checked, problems, pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert problems == 0, "a freshly-captured, still-rendering folder tripped the alarm"
    assert pending == len(archive.GENERATED_NAMES), "the pending files were not counted"

    report = doctor.diagnose(config)
    assert report.ok, "pending alone must not flip doctor's overall exit code"
    detail = next(c.detail for c in report.checks if c.name == "desync")
    assert "pending" in detail, detail


def test_a_missing_render_is_pending_while_a_batch_lock_is_held(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The lock-aware carve-out, isolated from recency: an OLD folder (well
    outside the grace window) with missing render files must still read as
    pending while `ccw sweep`/`ccw build`'s own lock is held by a live
    process -- proving the lock signal, not just elapsed time, is doing the
    work. Uses this test's own pid as the "live" holder, matching how
    `store.lock_is_held` defines liveness (`os.kill(pid, 0)`)."""
    from cc_warehouse import store

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)
    # Ticket 44c: the grace window keys on captured_at, so "old" is an old CAPTURE.
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)

    root = warehouse_root(ccw_env)
    assert store.acquire_lock(root, "build")
    try:
        config = Config(root=root, archive_root=archive_root, archive_timezone=ZONE)
        checked, problems, pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
        assert checked == 1
        assert problems == 0, "a batch-in-progress folder tripped the alarm"
        assert pending == len(archive.GENERATED_NAMES)
    finally:
        store.release_lock(root, "build")

    # Same folder, same problems, lock released: must revert to a real problem.
    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert problems >= 1, "the desync was not reinstated once the batch lock was released"
    assert first is not None and folder.name in first


def _sweep_rewrites_after_manifest(folder: Path) -> None:
    """Simulate `ccw sweep` mid-run, measured live 2026-09-29: it replaced the
    folder's JSONL with a larger payload and split `prompts.jsonl` into it, and
    its own `build.build()` had not yet rewritten the manifest. Both files end
    up NEWER than `manifest.json`, which is the one thing that tells this shape
    apart from a file altered after its manifest was last written."""
    jsonl_path = archive.sole_jsonl(folder)
    assert jsonl_path is not None
    jsonl_path.write_bytes(jsonl_path.read_bytes() + b'{"type":"other","extra":true}\n')
    (folder / archive.PROMPTS_FILE).write_bytes(b'{"display":"hi"}\n')
    manifest = folder / "manifest.json"
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(manifest, (old, old))


def test_a_stale_manifest_is_pending_while_a_batch_lock_is_held(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The live false alarm of 2026-09-29: a hand-run sweep held the build lock
    for over an hour, and doctor FAILed on 5 folders whose JSONL and
    `prompts.jsonl` the sweep itself had written after their manifests. Those
    are "not yet re-rendered", the same state ticket 34 already excuses for a
    missing generated file, so they read as pending while the lock is held and
    revert to real problems once it is released."""
    from cc_warehouse import store

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)

    root = warehouse_root(ccw_env)
    config = Config(root=root, archive_root=archive_root, archive_timezone=ZONE)

    # W-20260929-A82 item 2: a batch's own writes come AFTER it took its lock;
    # only those are excused (test_repair_sendback.py has the "before" case).
    assert store.acquire_lock(root, "build")
    try:
        _sweep_rewrites_after_manifest(folder)
        shapes = {p.problem for p in archive.verify_folder(folder, ZONE)}
        assert shapes == {
            "JSONL does not match manifest source_hash",
            "prompts.jsonl exists but the manifest says none",
        }, shapes
        checked, problems, pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
        assert checked == 1
        assert problems == 0, "a sweep's own not-yet-rendered writes tripped the alarm"
        assert pending == 2
    finally:
        store.release_lock(root, "build")

    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert pending == 0
    assert problems == 2, "the stale manifest was not reinstated once the lock was released"
    assert first is not None and folder.name in first


def test_a_file_older_than_its_manifest_is_never_pending_under_a_lock(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The narrowing: a live lock alone excuses nothing. A mismatched JSONL that
    is OLDER than its manifest was not written by the running batch, so it is
    a real problem even while that batch holds its lock."""
    from cc_warehouse import store

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)
    _tamper(folder)
    jsonl_path = archive.sole_jsonl(folder)
    assert jsonl_path is not None
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(jsonl_path, (old, old))

    root = warehouse_root(ccw_env)
    config = Config(root=root, archive_root=archive_root, archive_timezone=ZONE)
    assert store.acquire_lock(root, "build")
    try:
        checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    finally:
        store.release_lock(root, "build")
    assert checked == 1
    assert pending == 0, "a mismatch older than its manifest was excused by the lock"
    assert problems >= 1
    assert first is not None and folder.name in first


def test_a_tampered_folder_is_never_pending_even_inside_the_grace_window(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The narrowing that matters most: `_tamper` (JSONL vs. manifest hash
    mismatch) on a FRESHLY captured folder must still fail doctor. A hash
    mismatch describes real corruption, not "still queued", so it must never
    be excused by recency or a live batch lock -- unlike a plain missing-file
    problem, which the two tests above prove IS excused in the same
    circumstances."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _tamper(folder)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert pending == 0, "a hash-mismatch problem was wrongly excused as pending"
    assert problems >= 1, "tampering inside the grace window was not caught"
    assert first is not None and folder.name in first


def _recapture(env: dict[str, str], config: Config, session_uuid: str) -> str:
    """A resumed session's re-capture, the way `ccw hook` does it: the transcript
    grows, `capture_transcript` writes the new JSONL into the folder and a new
    catalog row, and the render that rewrites the manifest has not run yet."""
    from cc_warehouse import capture

    later = "2020-01-01T00:05:00.000Z"
    resumed = jsonl(entry("user", "resumed", later, session_id=session_uuid))
    path = write_transcript(env, stale_session(session_uuid) + resumed, session_id=session_uuid)
    result = capture.capture_transcript(
        config, path, session_id=session_uuid, cwd=None, defer_companions=True
    )
    assert result.action == "stored", result
    return result.short


def test_a_recapture_inside_the_grace_window_is_pending_with_no_lock(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """W-20260929-A62 (ruling: Gavin, 2026-09-29, option B). Since 78daa4f the
    hook's render waits for the companions copy, so a resumed session's
    re-capture leaves its new JSONL newer than the old manifest for the
    copy-plus-render time. The hook holds no batch lock, so only the
    capture-time grace can excuse it."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)  # so only the desync check under test can fail report.ok
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    _recapture(ccw_env, config, UUID_A)
    shapes = {p.problem for p in archive.verify_folder(folder, ZONE)}
    assert shapes == {"JSONL does not match manifest source_hash"}, shapes

    checked, problems, pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert problems == 0, "a re-capture still inside its grace window tripped the alarm"
    assert pending == 1
    assert doctor.diagnose(config).ok


def test_a_recapture_outside_the_grace_window_still_fails(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The same folder, captured longer ago than the grace: a real problem."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    _recapture(ccw_env, config, UUID_A)
    _age_capture(ccw_env, UUID_A, seconds_ago=doctor._PENDING_GRACE_SECONDS + 60)  # pyright: ignore[reportPrivateUsage]

    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert pending == 0
    assert problems == 1, "a stale manifest outside the grace window was excused"
    assert first is not None and folder.name in first


def test_a_file_older_than_its_manifest_is_never_pending_inside_the_grace_window(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Tamper stays red: inside the grace, with no lock, a mismatched JSONL OLDER
    than its manifest was not written by the capture that is still rendering."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _age_capture(ccw_env, UUID_A, seconds_ago=30)
    _tamper(folder)
    jsonl_path = archive.sole_jsonl(folder)
    assert jsonl_path is not None
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(jsonl_path, (old, old))

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert pending == 0, "a mismatch older than its manifest was excused by the grace"
    assert problems >= 1
    assert first is not None and folder.name in first


# ---------------------------------------------------------------------------
# W-20260929-A62 rework (ruling: Gavin, 2026-09-29, option 2: "hash check plus the
# clock starts when the save finishes")
# ---------------------------------------------------------------------------
#
# The hook's pipeline already writes its progress into logs/capture.jsonl: the
# hook's own `ok`/"captured" line, then the companions child's `companions-started`
# and `companions-done`. The render child now adds `render-done`. A hash-matching
# re-capture reads as pending while its pipeline is still moving, with the last
# progress line under `_COMPANIONS_GRACE_SECONDS` old, instead of a fixed 120 s
# from `captured_at`. Log times are compared only with `now`, never with mtimes.


def _append_aged(env: dict[str, str], write: Callable[[], None], *, seconds_ago: int) -> None:
    """Run a REAL capture.jsonl writer, then move the line it wrote into the past."""
    write()
    path = warehouse_root(env) / "logs" / "capture.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    record["at"] = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    lines[-1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hook_line(config: Config, short: str) -> Callable[[], None]:
    from cc_warehouse import notify

    return lambda: notify.report(
        config, notify.NotifyEvent("ok", short, None, "captured", 12)
    )


def _companions_line(config: Config, short: str, status: str) -> Callable[[], None]:
    from cc_warehouse import cli

    message = "started" if status == "companions-started" else "archived"
    return lambda: cli._log_companions(config, status, short, message, None)  # pyright: ignore[reportPrivateUsage]


def _render_done_line(config: Config, short: str) -> Callable[[], None]:
    from cc_warehouse import cli

    return lambda: cli._log_render_done(config, short, 900)  # pyright: ignore[reportPrivateUsage]


def _recapture_scene(
    env: dict[str, str], tmp_path: Path, *, captured_ago: int
) -> tuple[Config, Path, str]:
    archive_root = tmp_path / "archive"
    configure(env, archive_root)
    install_hook(env)  # so only the desync check under test can fail report.ok
    write_transcript(env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], env).code == 0
    folder = next(archive.walk_folders(archive_root))
    config = Config(root=warehouse_root(env), archive_root=archive_root, archive_timezone=ZONE)
    short = _recapture(env, config, UUID_A)
    _age_capture(env, UUID_A, seconds_ago=captured_ago)
    return config, folder, short


def test_the_render_child_logs_render_done(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Part 4: the clock's end signal comes from the real render verb, in the same
    six-field shape as the companions pair."""
    from conftest import run_cli

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    short = _recapture(ccw_env, config, UUID_A)

    result = run_cli(["render", "--session", f"s:{short}"])

    assert result.code == 0, result.err
    lines = (warehouse_root(ccw_env) / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    done = [r for r in map(json.loads, lines.splitlines()) if r.get("status") == "render-done"]
    assert len(done) == 1, done
    assert set(done[0]) == {"at", "status", "session", "project", "message", "elapsed_ms"}
    assert done[0]["session"] == short
    assert str(done[0]["message"]).startswith("render: ")


def test_a_recapture_still_rendering_past_120s_is_pending(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The slow-share case: captured 200 s ago, the copy finished 150 s ago, the
    render has not reported yet. Past the old 120 s grace, inside the ceiling."""
    config, _folder, short = _recapture_scene(ccw_env, tmp_path, captured_ago=200)
    _append_aged(ccw_env, _hook_line(config, short), seconds_ago=200)
    _append_aged(ccw_env, _companions_line(config, short, "companions-started"), seconds_ago=199)
    _append_aged(ccw_env, _companions_line(config, short, "companions-done"), seconds_ago=150)

    checked, problems, pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert checked == 1
    assert problems == 0, "a render still inside its pipeline window tripped the alarm"
    assert pending == 1
    assert doctor.diagnose(config).ok


def test_a_recapture_past_the_ceiling_with_no_render_done_fails(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A dead render child: the last progress line is older than the ceiling."""
    config, folder, short = _recapture_scene(ccw_env, tmp_path, captured_ago=500)
    _append_aged(ccw_env, _hook_line(config, short), seconds_ago=500)
    _append_aged(ccw_env, _companions_line(config, short, "companions-started"), seconds_ago=499)
    ceiling = doctor._COMPANIONS_GRACE_SECONDS  # pyright: ignore[reportPrivateUsage]
    _append_aged(
        ccw_env, _companions_line(config, short, "companions-done"), seconds_ago=ceiling + 30
    )

    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert checked == 1
    assert pending == 0, "a pipeline silent past its ceiling was still excused"
    assert problems == 1
    assert first is not None and folder.name in first


def test_a_mismatch_after_render_done_fails_at_once(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The render reported done and the folder still disagrees: nothing is still
    coming, so even a capture 30 s old is a real problem."""
    config, folder, short = _recapture_scene(ccw_env, tmp_path, captured_ago=30)
    _append_aged(ccw_env, _hook_line(config, short), seconds_ago=30)
    _append_aged(ccw_env, _companions_line(config, short, "companions-started"), seconds_ago=29)
    _append_aged(ccw_env, _companions_line(config, short, "companions-done"), seconds_ago=20)
    _append_aged(ccw_env, _render_done_line(config, short), seconds_ago=10)

    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert checked == 1
    assert pending == 0, "a mismatch that outlived its own render was excused"
    assert problems == 1
    assert first is not None and folder.name in first


def test_a_tampered_recapture_inside_the_pipeline_window_fails(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Part 1 kept: a live pipeline excuses only the bytes the catalog recorded."""
    config, folder, short = _recapture_scene(ccw_env, tmp_path, captured_ago=30)
    _append_aged(ccw_env, _hook_line(config, short), seconds_ago=30)
    _append_aged(ccw_env, _companions_line(config, short, "companions-started"), seconds_ago=29)
    _tamper(folder)

    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert checked == 1
    assert pending == 0, "a JSONL the catalog never recorded was excused"
    assert problems == 1
    assert first is not None and folder.name in first


def test_a_newer_prompts_file_with_no_lock_fails_even_inside_the_grace(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Part 2: the only writer of prompts.jsonl is sweep, under the sweep lock, so
    with no lock a newer prompts.jsonl was written by something else."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _age_capture(ccw_env, UUID_A, seconds_ago=30)
    (folder / archive.PROMPTS_FILE).write_bytes(b'{"display":"hi"}\n')
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(folder / "manifest.json", (old, old))

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert checked == 1
    assert pending == 0, "a newer prompts.jsonl was excused with no lock held"
    assert problems == 1
    assert first is not None and folder.name in first


@pytest.mark.parametrize("lock", ["import", "migrate", "relocate", "archive"])
def test_every_batch_writer_lock_excuses_its_own_writes(
    ccw_env: dict[str, str], tmp_path: Path, lock: str
) -> None:
    """Part 3: import, migrate, relocate and `archive --to` also write a JSONL and
    then its manifest under their own lock, so doctor treats them as a batch."""
    from cc_warehouse import store

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _age_capture(ccw_env, UUID_A, seconds_ago=3600)
    root = warehouse_root(ccw_env)
    config = Config(root=root, archive_root=archive_root, archive_timezone=ZONE)

    assert store.acquire_lock(root, lock)
    try:
        _sweep_rewrites_after_manifest(folder)  # after the lock (A82 item 2)
        _checked, problems, pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    finally:
        store.release_lock(root, lock)

    assert problems == 0, f"a live {lock} batch's own writes tripped the alarm"
    assert pending == 2


def test_doctor_knows_every_batch_lock_the_code_takes() -> None:
    """The pin `_BATCH_LOCK_NAMES`'s comment promised and that did not exist:
    every `store.acquire_lock(<root>, <module constant>)` call site in src,
    resolved to the constant's value, must be in doctor's list. The one call
    site with a computed name is capture's per-hash lock, named here so a new
    computed lock cannot slip past unseen."""
    import ast

    src = Path(doctor.__file__).parent
    batch: set[str] = set()
    computed: set[str] = set()
    for path in sorted(src.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "acquire_lock"
                and len(node.args) == 2
            ):
                name = node.args[1]
                if isinstance(name, ast.Name) and name.id in constants:
                    batch.add(constants[name.id])
                else:
                    computed.add(path.name)
    assert computed == {"capture.py"}, computed
    assert batch == {"sweep", "build", "import", "migrate", "relocate", "archive"}, batch
    assert set(doctor._BATCH_LOCK_NAMES) == batch  # pyright: ignore[reportPrivateUsage]


def test_a_registered_hook_whose_script_is_gone_is_not_reported_ok(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE FALSE GREEN THIS PINS (found 2026-09-07, by the fifty-shades-of-dotfiles
    session red-teaming its own watcher, then proved here by execution).

    The plugin runs from a CACHED clone at a recorded installPath. If that
    directory goes missing, `enabledPlugins` still says true, the hooks.json entry
    is still there, nothing errors, and capture is dead.

    `_mentions_ccw` had two paths and only the second touched the filesystem. The
    first returned True as soon as the command STRING contained "ccw", and our own
    registration is `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py` - where "ccw"
    is in the FILENAME. So the string path fired and returned before the is_file()
    check on the second path was ever reached, and the `hook` line stayed green for
    a plugin root that did not exist.

    That is a false green in the tool whose whole job is to stop a broken thing
    looking healthy, and it is the same shape 0.1.2 fixed one instance of.
    """
    configure(ccw_env, tmp_path / "archive")
    plugin = (
        Path(ccw_env["HOME"]) / ".claude" / "plugins" / "cache" / "mp" / "p" / "v1"
    )
    (plugin / "hooks").mkdir(parents=True)
    # hooks.json exists and registers our real command shape. The script does NOT.
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _write_enabled_plugins(ccw_env, {"p@mp": True})

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert not hook_line.strip().startswith("ok"), (
        f"doctor called a missing hook script ok: {hook_line!r}"
    )
    assert result.code != 0, f"a missing hook script exited 0: {result.out!r}"


def test_the_missing_script_is_named_as_such_not_as_nothing_registered(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """"Registered but its file is gone" and "nothing is registered at all" are
    different problems with different fixes. The first is repaired by a `/plugin`
    update; the second by registering a hook. Reporting the first as the second
    sends the reader to the wrong repair."""
    configure(ccw_env, tmp_path / "archive")
    plugin = (
        Path(ccw_env["HOME"]) / ".claude" / "plugins" / "cache" / "mp" / "p" / "v1"
    )
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    _write_enabled_plugins(ccw_env, {"p@mp": True})

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "missing" in hook_line.lower(), (
        f"the detail did not say the script is missing: {hook_line!r}"
    )
    assert "ccw-hook.py" in hook_line, (
        f"the detail did not name the file that is gone: {hook_line!r}"
    )


def test_a_bare_ccw_hook_command_is_still_accepted(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE REGRESSION THE FIX ABOVE COULD EASILY CAUSE. Requiring a file
    unconditionally would break a legitimate registration: `ccw hook` in
    settings.json names NO script path at all, because the command resolves from
    PATH. The string-match branch exists precisely to accept that form, and the
    new rule must only bite when the command actually names a script."""
    configure(ccw_env, tmp_path / "archive")
    settings = Path(ccw_env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionEnd": [
                        {"hooks": [{"type": "command", "command": "ccw hook"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_ccw(["doctor"], ccw_env)
    hook_line = next((ln for ln in result.out.splitlines() if " hook " in ln), "")

    assert "NO capture hook" not in hook_line, (
        f"a bare `ccw hook` registration was rejected: {hook_line!r}"
    )


# ---------------------------------------------------------------------------
# Ticket 39c: the `history.jsonl` snapshot staleness line
# ---------------------------------------------------------------------------

HISTORY_BYTES = b'{"display":"fix the flux capacitor","sessionId":"aaaa"}\n'


def test_no_archive_configured_is_not_an_alarm(tmp_path: Path) -> None:
    config = Config(root=tmp_path / "warehouse")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "history.jsonl").write_bytes(HISTORY_BYTES)
    ok, detail = doctor._history_staleness(config, home)  # pyright: ignore[reportPrivateUsage]
    assert ok is True
    assert "no archive configured" in detail


def test_no_history_file_on_this_machine_is_not_an_alarm(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    config = Config(root=tmp_path / "warehouse", archive_root=archive_root, archive_timezone=ZONE)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    ok, detail = doctor._history_staleness(config, home)  # pyright: ignore[reportPrivateUsage]
    assert ok is True
    assert "no history.jsonl" in detail


def test_an_unsnapshotted_history_file_is_reported_stale(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    config = Config(root=tmp_path / "warehouse", archive_root=archive_root, archive_timezone=ZONE)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "history.jsonl").write_bytes(HISTORY_BYTES)

    ok, detail = doctor._history_staleness(config, home)  # pyright: ignore[reportPrivateUsage]
    assert ok is False
    assert "not yet snapshotted" in detail


def test_a_snapshotted_history_file_reports_up_to_date(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    config = Config(root=tmp_path / "warehouse", archive_root=archive_root, archive_timezone=ZONE)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "history.jsonl").write_bytes(HISTORY_BYTES)
    archive.write_history_snapshot(archive_root, HISTORY_BYTES)

    ok, detail = doctor._history_staleness(config, home)  # pyright: ignore[reportPrivateUsage]
    assert ok is True
    assert "up to date" in detail


def test_a_stale_history_snapshot_never_flips_doctors_exit_code(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """NEVER BLOCKING (same posture as the `sidecars` check, ticket 38 ruling (e)):
    an unsnapshotted history file is worth knowing about, not a broken capture,
    and must not move the exit code `ccw-freshness-check.py` escalates on. A
    fully healthy install (hook registered, capture fired, nothing overdue) is
    built here so ONLY the check under test can fail `report.ok` -- the same
    isolation `install_hook` provides for the desync tests above."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, fresh_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    (Path(ccw_env["HOME"]) / ".claude" / "history.jsonl").write_bytes(HISTORY_BYTES)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    history_check = next(c for c in report.checks if c.name == "history")
    assert history_check.ok is False
    assert history_check.blocking is False
    assert report.ok, "a stale history snapshot alone must not fail doctor"


# ---------------------------------------------------------------------------
# Ticket 42 #5: the reconcile check reads only the cheap dedup ledger
# ---------------------------------------------------------------------------


def _append_capture_log(env: dict[str, str], **fields: object) -> None:
    record: dict[str, object] = {
        "at": "2026-01-01T00:00:00+00:00",
        "status": "error",
        "session": None,
        "project": None,
        "message": "(no detail)",
        "elapsed_ms": None,
    }
    record.update(fields)
    log_dir = warehouse_root(env) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "capture.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def test_reconcile_line_reads_zero_before_repair_has_ever_run(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A raw `error` record on its own is NOT a KNOWN loss -- only `ccw repair`
    confirming it (the expensive cross-check) and writing the dedup record makes
    it one. Before that, the line reads 0, meaning "not yet checked", the same
    "never fired" vs "fired, but not recently" distinction `_last_capture` draws."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    _append_capture_log(
        ccw_env, session_uuid=UUID_A, message=f"unreadable transcript /x/{UUID_A}.jsonl: boom"
    )

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "reconcile")
    assert "0 session" in check.detail, check.detail


def test_reconcile_line_reports_a_known_loss(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    _append_capture_log(
        ccw_env,
        status="unrecoverable",
        session_uuid=UUID_A,
        message="confirmed unrecoverable",
        at="2026-05-01T00:00:00+00:00",
    )

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "reconcile")
    assert "1 session" in check.detail, check.detail
    assert "2026-05-01" in check.detail, check.detail


def test_reconcile_line_never_blocks_doctors_exit_code(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """NEVER BLOCKING (same posture as sidecars/history/prompts/companions): a
    known permanent loss already happened and this line cannot undo it, so it
    must not fail an otherwise-healthy `ccw doctor`."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    _append_capture_log(
        ccw_env, status="unrecoverable", session_uuid=UUID_B, message="confirmed unrecoverable"
    )

    result = run_ccw(["doctor"], ccw_env)

    assert result.code == 0, f"a known-unrecoverable session alone failed doctor: {result.out}"


def test_reconcile_line_never_walks_the_archive(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE COST GUARANTEE: `ccw doctor` runs on every SessionStart
    (ccw-freshness-check.py), and ticket 41 Finding 1 already caused a real
    SessionStart timeout once, from an unrelated bug. Proven by making the
    expensive cross-check explode if `diagnose` ever reaches for it -- the
    reconcile line must read ONLY the dedup ledger. In-process (not `run_ccw`,
    a subprocess the monkeypatch below cannot reach)."""
    from cc_warehouse import reconcile

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    _append_capture_log(
        ccw_env, session_uuid=UUID_A, message=f"unreadable transcript /x/{UUID_A}.jsonl: boom"
    )

    def _boom(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        raise AssertionError("doctor's reconcile check ran the expensive cross-check")

    monkeypatch.setattr(reconcile, "find_unrecoverable", _boom)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))

    assert next(c for c in report.checks if c.name == "reconcile").detail


# ---------------------------------------------------------------------------
# Ticket 42 #6: the dispatch check -- "did Claude Code even try to tell us"
# ---------------------------------------------------------------------------


def session_at(session_id: str, moment: datetime) -> bytes:
    """A session whose own payload timestamp sits at a caller-chosen real
    moment, needed to exercise `_DISPATCH_GRACE_SECONDS`/`_DISPATCH_WINDOW`
    against actual wall-clock time (same reasoning as `fresh_session` above,
    generalised to an arbitrary offset rather than only "now")."""
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return jsonl(
        entry("user", "hello", stamp, session_id=session_id),
        entry("assistant", "hi", stamp, session_id=session_id),
    )


def append_hook_log(
    env: dict[str, str], session_id: str, *, status: str = "started", moment: datetime | None = None
) -> None:
    """A `ccw-hook.log` line in `ccw-hook.py`'s own `report()` shape."""
    record = {
        "ts": (moment or datetime.now(UTC)).isoformat(timespec="seconds"),
        "source": "ccw-hook",
        "python": "3.12.0 /usr/bin/python3",
        "session": session_id,
        "status": status,
        "detail": "",
    }
    log_dir = Path(env["HOME"]) / ".claude" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "ccw-hook.log").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def test_a_session_with_a_started_line_is_not_a_dispatch_gap(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The hook plainly ran; a slow sweep behind it is `_overdue`'s question,
    not this one's."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    old_enough = datetime.now(UTC) - timedelta(hours=1)
    write_transcript(ccw_env, session_at(UUID_A, old_enough), session_id=UUID_A)
    append_hook_log(ccw_env, UUID_A, moment=old_enough)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "dispatch")
    assert check.ok is True, check.detail


def test_a_stale_session_with_no_started_line_is_a_dispatch_gap(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The exact ticket 41 Finding 4 mechanism: a session that ended a while
    ago and has zero entries anywhere in `ccw-hook.log` -- unlike an entirely
    MISSING log (a different, "cannot answer yet" case below), the log here
    exists and has entries, just none for this session's own uuid."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    old_enough = datetime.now(UTC) - timedelta(hours=1)
    write_transcript(ccw_env, session_at(UUID_A, old_enough), session_id=UUID_A)
    append_hook_log(ccw_env, UUID_B, moment=old_enough)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "dispatch")
    assert check.ok is False
    assert UUID_A in check.detail, check.detail


def test_a_freshly_ended_session_is_not_flagged_yet(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Inside `_DISPATCH_GRACE_SECONDS`: the session may simply not have
    reached the hook yet. Flagging it here would just be a faster-firing
    version of the exact false-alarm class `_overdue` already avoids."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, fresh_session(UUID_A), session_id=UUID_A)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "dispatch")
    assert check.ok is True, check.detail


def test_an_archived_session_is_never_flagged_even_with_no_started_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`ccw sweep` does not depend on the hook ever having fired (ticket 41):
    a session captured that way, with nothing to show in `ccw-hook.log`, is
    working as designed, not a gap."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    old_enough = datetime.now(UTC) - timedelta(hours=1)
    write_transcript(ccw_env, session_at(UUID_A, old_enough), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "dispatch")
    assert check.ok is True, check.detail


def test_a_gap_older_than_the_window_is_not_re_alarmed_forever(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Bounded recency, same posture as `_COMPANIONS_WINDOW`: a long-past gap
    is `ccw reconcile`'s permanent record to keep, not this SessionStart-cheap
    line's to re-surface on every run."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, stale_session(UUID_A), session_id=UUID_A)  # 2020, no hook line

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "dispatch")
    assert check.ok is True, check.detail


def test_no_ccw_hook_log_on_this_machine_is_not_an_alarm(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    check = next(c for c in report.checks if c.name == "dispatch")
    assert check.ok is True
    assert "no ccw-hook.log" in check.detail


def test_dispatch_check_never_blocks_doctors_exit_code(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """NEVER BLOCKING (same posture as sidecars/history/prompts/companions/
    reconcile): root cause lives outside this repo (ticket 41's addendum), and
    sweep does not depend on the hook ever having fired, so a dispatch gap
    alone must not fail an otherwise-healthy `ccw doctor`."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, fresh_session(UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    old_enough = datetime.now(UTC) - timedelta(hours=1)
    write_transcript(ccw_env, session_at(UUID_B, old_enough), session_id=UUID_B)
    append_hook_log(ccw_env, "some-unrelated-uuid", moment=old_enough)
    # A FINISHED run: since W-20260929-A105 a `started` with nothing after it is a
    # dead hook, which fails doctor on its own; this test is about the dispatch gap.
    append_hook_log(ccw_env, "some-unrelated-uuid", status="ok", moment=old_enough)

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    dispatch_check = next(
        c for c in doctor.diagnose(config, home=Path(ccw_env["HOME"])).checks
        if c.name == "dispatch"
    )
    assert dispatch_check.ok is False, "test setup did not actually produce a dispatch gap"

    result = run_ccw(["doctor"], ccw_env)

    assert result.code == 0, f"a dispatch gap alone failed doctor: {result.out}"
    assert "dispatch" in result.out, result.out
