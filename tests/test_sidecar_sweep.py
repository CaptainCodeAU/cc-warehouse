"""Oracle tests: the sweep's third pass over sidecars (ticket 38, slice 38d).

WHY A THIRD PASS AND NOT A BRANCH IN THE FIRST. A sidecar can arrive AFTER the
last capture with the transcript's hash unchanged - Claude Code writes a tool
result during the session and the session may never be re-captured. The sweep's
cheap pre-filter reports such a session `skipped_unchanged` and never opens it
again, so a pass that only looked at newly stored sessions would never see the
file. Pass three therefore runs for EVERY session path the walk yields, including
the skipped ones.

WHY IT RUNS LAST. A sidecar nests inside its session's folder, so the folder has
to exist first. Sessions, then sub-agents, then sidecars.

Contract: R5, R9, R10, R14; FINDINGS F1, F6, F9; section 15 ruling (d).
"""

import json
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    settle_render,
    subagent_session,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
PARENT = "d3111111-2222-3333-4444-555555555551"
STRANDED = "99999999-0000-0000-0000-000000000000"
ENCODED = "-home-alice-projects-widget"
STDOUT_NAME = "hook-9c2f1a7b-3d4e-5f60-8a91-b2c3d4e5f607-stdout.txt"
STDOUT_BYTES = b"Output too large (132.9KB). Full output saved to: /home/alice/x\n"


def configure(env: dict[str, str], archive_root: Path, *, tool_results: bool | None = None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    if tool_results is not None:
        lines.append(f"archive_tool_results = {'true' if tool_results else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def projects(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects" / ENCODED


def plant_session(env: dict[str, str]) -> Path:
    return write_transcript(
        env, basic_session(session_id=PARENT), session_id=PARENT, name=f"{PARENT}.jsonl"
    )


def plant_tool_result(
    env: dict[str, str], *, name: str = STDOUT_NAME, data: bytes = STDOUT_BYTES
) -> None:
    where = projects(env) / PARENT / "tool-results"
    where.mkdir(parents=True, exist_ok=True)
    (where / name).write_bytes(data)


def sweep(env: dict[str, str], *extra: str) -> str:
    result = run_ccw(["sweep", *extra], env)
    assert result.code == 0, result.err + result.out
    return result.out


def session_folder(archive_root: Path) -> Path:
    folders = sorted(archive_root.glob(f"*/*_{PARENT}"))
    assert len(folders) == 1, f"expected one session folder, got {folders}"
    return folders[0]


def log_lines(env: dict[str, str], status: str) -> list[dict[str, object]]:
    log = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log.is_file():
        return []
    out: list[dict[str, object]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        record = cast(object, json.loads(line))
        if isinstance(record, dict):
            typed = cast(dict[str, object], record)
            if typed.get("status") == status:
                out.append(typed)
    return out


# ---------------------------------------------------------------------------
# The back-fill: what this ticket actually has to do to 1,067 existing sessions
# ---------------------------------------------------------------------------


def test_a_sweep_backfills_sidecars_for_a_session_it_already_archived(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The whole corpus is in this state: archived long ago, sidecars never
    copied. If the back-fill needed a re-capture, 1,067 sessions would need their
    transcripts to change, which they never will."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=PARENT))
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    assert (session_folder(archive_root) / "tool-results" / STDOUT_NAME).read_bytes() == (
        STDOUT_BYTES
    )


def test_the_backfilled_session_is_reported_skipped_unchanged_not_stored(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F6: a session whose transcript did not change must not read as stored just
    because a sidecar arrived. The two are different facts."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=PARENT))
    plant_tool_result(ccw_env)
    assert "0 stored" in sweep(ccw_env)


def test_a_second_sweep_writes_nothing_anywhere_in_the_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ticket 37 Part A, generalised. Every byte in the archive must be able to
    keep the mtime of the day it arrived, or a backup tool sees the whole tree
    change nightly. Whole-tree snapshot, not a spot check."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    before = tree_snapshot(archive_root)
    mtimes_before = {
        str(p.relative_to(archive_root)): p.stat().st_mtime_ns
        for p in sorted(archive_root.rglob("*"))
        if p.is_file()
    }
    sweep(ccw_env)
    mtimes_after = {
        str(p.relative_to(archive_root)): p.stat().st_mtime_ns
        for p in sorted(archive_root.rglob("*"))
        if p.is_file()
    }
    assert tree_snapshot(archive_root) == before
    assert mtimes_after == mtimes_before


def test_a_file_added_after_capture_is_picked_up_by_the_next_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    plant_tool_result(ccw_env, name="mcp-widget-lookup-1757000000.txt", data=b"late arrival\n")
    sweep(ccw_env)
    landed = session_folder(archive_root) / "tool-results" / "mcp-widget-lookup-1757000000.txt"
    assert landed.read_bytes() == b"late arrival\n"


def test_the_switch_off_stops_the_sweep_copying(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, tool_results=False)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    assert not (session_folder(archive_root) / "tool-results").exists()


def test_the_source_tree_is_untouched_by_a_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9, and worth its own test on this path: the third pass reads a tree the
    project has a standing rule never to write to."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    before = tree_snapshot(projects(ccw_env))
    sweep(ccw_env)
    assert tree_snapshot(projects(ccw_env)) == before


# ---------------------------------------------------------------------------
# Ordering, refusal, and the no-parent case
# ---------------------------------------------------------------------------


def test_a_sidecar_is_never_written_before_its_parent_folder_exists(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ticket 21.4's lesson, one level out. A single pass in filename order files
    most nested things as orphans purely because they sorted earlier."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    folder = session_folder(archive_root)
    assert (folder / f"{PARENT}.jsonl").is_file()
    assert (folder / "tool-results" / STDOUT_NAME).is_file()


def test_a_same_name_different_bytes_file_is_refused_and_reported(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    plant_tool_result(ccw_env, data=b"a completely different capture")
    sweep(ccw_env)
    notice = json.loads((session_folder(archive_root) / "sidecars.json").read_text("utf-8"))
    assert notice["refused"] == [f"tool-results/{STDOUT_NAME}"]
    assert (session_folder(archive_root) / "tool-results" / STDOUT_NAME).read_bytes() == (
        STDOUT_BYTES
    )


def test_an_unknown_sibling_found_by_the_sweep_is_logged_once_across_two_runs(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    (projects(ccw_env) / PARENT / "zzz-probe").mkdir(parents=True)
    sweep(ccw_env)
    sweep(ccw_env)
    assert len(log_lines(ccw_env, "unarchived-sibling")) == 1


# ---------------------------------------------------------------------------
# Stranded dirs (ruling (d))
# ---------------------------------------------------------------------------


def test_a_stranded_sidecar_dir_is_copied_under_not_sessions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    orphan = projects(ccw_env) / STRANDED / "tool-results"
    orphan.mkdir(parents=True)
    (orphan / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    sweep(ccw_env)
    landed = (
        archive_root / "_not-sessions" / "stranded-sidecars" / STRANDED
        / "tool-results" / STDOUT_NAME
    )
    assert landed.read_bytes() == STDOUT_BYTES


def test_a_stranded_dir_whose_session_is_already_archived_goes_to_its_real_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """REFINEMENT OF RULING (d), found by execution. "No transcript BESIDE this
    dir" is not "no transcript anywhere": 4 of the 39 real stranded dirs have a
    session folder in the archive already. Filing those under `_not-sessions/`
    would put a KNOWN session's data in the drawer reserved for unknowns."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    # The transcript goes away, leaving its sidecar dir with nothing beside it.
    transcript.unlink()
    plant_tool_result(ccw_env, name="late.txt", data=b"arrived after the transcript left\n")
    sweep(ccw_env)
    assert (session_folder(archive_root) / "tool-results" / "late.txt").is_file()
    assert not (archive_root / "_not-sessions" / "stranded-sidecars" / PARENT).exists()


# ---------------------------------------------------------------------------
# The rehearsal must still change nothing (`--dry-run`)
# ---------------------------------------------------------------------------


def test_a_dry_run_reports_the_sidecars_it_would_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    result = run_ccw(["sweep", "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert "would-archive-sidecars" in result.out


def test_a_dry_run_creates_nothing_on_a_fresh_root(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE PROPERTY the whole `plan()` function exists for: a rehearsal must not
    materialise the warehouse it is describing."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    run_ccw(["sweep", "--dry-run"], ccw_env)
    assert not archive_root.exists()
    assert not (warehouse_root(ccw_env) / "catalog.sqlite").exists()


# ---------------------------------------------------------------------------
# The build has to run even when nothing was "stored"
# ---------------------------------------------------------------------------


def test_a_sweep_that_only_archived_sidecars_still_rebuilds_the_manifest(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`cli.py` only ran `build.build` `if stored:`, and a back-fill stores 0. The
    manifest would then never list the file that was just copied, which is the
    only thing that makes its later deletion detectable.

    Waits for the hook's own detached render child (ticket 37 Part B added a
    SECOND detached child per hook fire, `ccw companions`, which raised the
    odds of hitting this pre-existing race enough to surface it in CI): that
    child writes its OWN manifest.json, built before `plant_tool_result` below
    ever ran, so without the wait it can land AFTER the sweep's own build and
    silently revert this test's very assertion."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant_session(ccw_env)
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=PARENT))
    settle_render(warehouse_root(ccw_env), expected=1)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    manifest = json.loads((session_folder(archive_root) / "manifest.json").read_text("utf-8"))
    listed = cast(list[dict[str, object]], manifest["tool_results"])
    assert [r["name"] for r in listed] == [STDOUT_NAME]


def test_the_archive_verifies_clean_after_a_backfill(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    result = run_ccw(["archive", "--to", str(archive_root), "--verify"], ccw_env)
    assert result.code == 0, result.out + result.err
    assert "0 problems" in result.out


# ---------------------------------------------------------------------------
# The shared walk contract nothing may break
# ---------------------------------------------------------------------------


def test_source_transcripts_still_returns_exactly_two_lists() -> None:
    """`status.uncaptured_gap` and `doctor._overdue` both unpack this 2-tuple. A
    third element would be a silent break in two health checks at once."""
    from cc_warehouse import sweep as sweep_module

    sessions, subagents = sweep_module.source_transcripts(Path("/nonexistent"))
    assert sessions == []
    assert subagents == []


def test_a_workflow_tool_subagent_is_archived_by_the_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The sweep's os.walk already reached these; this pins it so the hook-side
    fix in 38c cannot be mistaken for the only route."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    nested = projects(ccw_env) / PARENT / "subagents" / "workflows" / "wf_abc"
    nested.mkdir(parents=True)
    (nested / "agent-b7c2e9f10a3b4c5d6.jsonl").write_bytes(
        subagent_session(agent_id="b7c2e9f10a3b4c5d6", parent_uuid=PARENT)
    )
    sweep(ccw_env)
    landed = sorted(session_folder(archive_root).glob("subagents/*_b7c2e9f10a3b4c5d6"))
    assert len(landed) == 1, landed


def test_a_sweep_refusal_reaches_the_audit_log_like_the_hooks_does(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """FOUND BY WATCHING THE REAL LOG, 2026-09-08, right after shipping.

    The hook path logs every refusal through `_log_sidecar_trouble`. The sweep
    path recorded it in the report and in `sidecars.json` and wrote NO log line at
    all, so the one real refusal on this machine left the audit log with nothing in
    it. Proved with a control before believing the zero: `"status": "ok"` matched
    669 lines in the same file, `refused` matched none.

    That split matters because the two records answer different questions. The
    notice says what is true NOW for one session; the log says what HAPPENED and
    when, across all of them, and it is the only one a later reader can count.
    A refusal visible in one and not the other is the F6 shape this ticket exists
    to remove, shipped inside the ticket that removes it."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_session(ccw_env)
    plant_tool_result(ccw_env)
    sweep(ccw_env)
    plant_tool_result(ccw_env, data=b"a completely different capture")
    sweep(ccw_env)
    records = log_lines(ccw_env, "refused")
    assert len(records) == 1, records
    assert STDOUT_NAME in str(records[0]["message"])
    assert set(records[0]) == {"at", "status", "session", "project", "message", "elapsed_ms"}
