"""Oracle tests: the hook and the sweep gather file-history and todos (39b).

TWO PRODUCERS, ONE MECHANISM, and the split is the same as ticket 38's. The hook
gathers for the session that just ended, which is what keeps a fresh session's
snapshots safe without waiting on a daily job. The sweep gathers for everything
else, including sessions it reports `skipped_unchanged` - a snapshot can be written
during a session whose transcript then never changes again, so a pass that only
looked at newly stored sessions would never see it.

NEVER FATAL (DESIGN 12). A session that is already stored must not become a
reported failure because a snapshot could not be copied.

Contract: DESIGN 12, R5, R9, R10; FINDINGS F6, F9; ticket 39's constraint that
nothing under `~/.claude` is ever written.
"""

import json
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
SNAP = "23527e7c@v1"
SNAP_BYTES = b"--- a/widget.py\n+++ b/widget.py\n@@ -1 +1 @@\n-old\n+new\n"


def configure(env: dict[str, str], archive_root: Path, *, file_history: bool | None = None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    if file_history is not None:
        lines.append(f"archive_file_history = {'true' if file_history else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def claude_home(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude"


def plant(env: dict[str, str], uuid: str = UUID_A) -> Path:
    transcript = write_transcript(env, basic_session(session_id=uuid), session_id=uuid)
    snaps = claude_home(env) / "file-history" / uuid
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / SNAP).write_bytes(SNAP_BYTES)
    (snaps / "23527e7c@v2").write_bytes(b"a later version\n")
    todos = claude_home(env) / "todos"
    todos.mkdir(parents=True, exist_ok=True)
    (todos / f"{uuid}-agent-{uuid}.json").write_bytes(b'[{"content":"do the thing"}]')
    return transcript


def fire_hook(env: dict[str, str], transcript: Path, uuid: str = UUID_A) -> None:
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=uuid))
    assert result.code == 0, result.err


def sweep(env: dict[str, str]) -> str:
    result = run_ccw(["sweep", "--quiet"], env)
    assert result.code == 0, result.err + result.out
    return result.out


def folder_of(archive_root: Path, uuid: str = UUID_A) -> Path:
    found = sorted(archive_root.glob(f"*/*_{uuid}"))
    assert len(found) == 1, f"expected one folder for {uuid}, got {found}"
    return found[0]


# ---------------------------------------------------------------------------
# The hook path
# ---------------------------------------------------------------------------


def test_the_hook_brings_the_sessions_file_history(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(ccw_env, plant(ccw_env))
    assert (folder_of(archive_root) / "file-history" / SNAP).read_bytes() == SNAP_BYTES


def test_the_hook_brings_the_sessions_todos(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(ccw_env, plant(ccw_env))
    landed = folder_of(archive_root) / "todos" / f"{UUID_A}-agent-{UUID_A}.json"
    assert landed.read_bytes() == b'[{"content":"do the thing"}]'


def test_only_this_sessions_snapshots_are_taken(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The store is shared by every session on the machine, so a copier that read
    the DIRECTORY rather than the session id would put one session's file history
    into another session's folder. 1,056 sessions' worth, on this machine."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env, UUID_A)
    other = claude_home(ccw_env) / "file-history" / UUID_B
    other.mkdir(parents=True)
    (other / "deadbeef@v1").write_bytes(b"someone else's file\n")
    fire_hook(ccw_env, transcript)
    names = sorted(p.name for p in (folder_of(archive_root) / "file-history").iterdir())
    assert names == [SNAP, "23527e7c@v2"]


def test_nothing_under_dot_claude_is_modified(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The operator's standing rule, verbatim 2026-08-04. Whole-tree byte snapshot
    of `~/.claude`, not a spot check, because a copier is exactly the shape that
    forgets (F9)."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    before = tree_snapshot(claude_home(ccw_env))
    fire_hook(ccw_env, transcript)
    assert tree_snapshot(claude_home(ccw_env)) == before


def test_the_switch_off_stops_the_gather(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, file_history=False)
    fire_hook(ccw_env, plant(ccw_env))
    assert not (folder_of(archive_root) / "file-history").exists()


def test_the_session_is_still_captured_when_the_switch_is_off(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, file_history=False)
    fire_hook(ccw_env, plant(ccw_env))
    assert (folder_of(archive_root) / f"{UUID_A}.jsonl").is_file()


def test_an_unreadable_store_never_costs_the_capture(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    blocked = claude_home(ccw_env) / "file-history" / UUID_A
    blocked.chmod(0o000)
    try:
        fire_hook(ccw_env, transcript)
    finally:
        blocked.chmod(0o700)
    assert (folder_of(archive_root) / f"{UUID_A}.jsonl").read_bytes() == basic_session(
        session_id=UUID_A
    )


# ---------------------------------------------------------------------------
# The sweep path
# ---------------------------------------------------------------------------


def test_a_sweep_backfills_a_session_it_already_archived(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The whole corpus is in this state: 1,014 sessions archived long ago whose
    snapshots were never copied. A back-fill that needed a re-capture would need
    1,014 transcripts to change, which they never will."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    fire_hook(ccw_env, transcript, UUID_A)
    snaps = claude_home(ccw_env) / "file-history" / UUID_A
    snaps.mkdir(parents=True)
    (snaps / SNAP).write_bytes(SNAP_BYTES)
    sweep(ccw_env)
    assert (folder_of(archive_root) / "file-history" / SNAP).read_bytes() == SNAP_BYTES


def test_a_second_sweep_writes_nothing_new(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    sweep(ccw_env)
    before = tree_snapshot(archive_root)
    mtimes = {
        str(p.relative_to(archive_root)): p.stat().st_mtime_ns
        for p in sorted(archive_root.rglob("*"))
        if p.is_file()
    }
    sweep(ccw_env)
    after_mtimes = {
        str(p.relative_to(archive_root)): p.stat().st_mtime_ns
        for p in sorted(archive_root.rglob("*"))
        if p.is_file()
    }
    assert tree_snapshot(archive_root) == before
    assert after_mtimes == mtimes


def test_a_snapshot_dir_whose_session_is_not_archived_lands_under_not_sessions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """42 of the live 1,056. Their session left `~/.claude/projects` before the
    archive ever saw it, so there is no folder to nest under."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    orphan = claude_home(ccw_env) / "file-history" / "99999999-0000-4000-8000-000000000000"
    orphan.mkdir(parents=True)
    (orphan / SNAP).write_bytes(b"nobody's snapshot\n")
    sweep(ccw_env)
    landed = (
        archive_root
        / "_not-sessions"
        / "stranded-file-history"
        / "99999999-0000-4000-8000-000000000000"
        / SNAP
    )
    assert landed.read_bytes() == b"nobody's snapshot\n"


def test_the_manifest_lists_the_snapshots_after_a_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The listing is the only thing that makes a later deletion detectable, so a
    gather that never reaches a manifest is half a feature."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    sweep(ccw_env)
    manifest = cast(
        dict[str, object],
        json.loads((folder_of(archive_root) / "manifest.json").read_text("utf-8")),
    )
    records = cast(list[dict[str, object]], manifest["file_history"])
    assert {r["name"] for r in records} == {SNAP, "23527e7c@v2"}


def test_the_source_tree_is_untouched_by_a_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    before = tree_snapshot(claude_home(ccw_env))
    sweep(ccw_env)
    assert tree_snapshot(claude_home(ccw_env)) == before


def test_a_dry_run_gathers_nothing(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The property `plan()` exists for: a rehearsal must not materialise the
    warehouse it is describing."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    result = run_ccw(["sweep", "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert not archive_root.exists()
