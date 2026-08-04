"""Oracle tests: the `ccw reindex` verb (ticket 27, slices 27.1 and 27.2).

`archive.read_projects` has reconstructed every project label and alias from the
tree since slice 19f, and until now NOTHING CALLED IT. DESIGN 15 says the
catalog is a DISPOSABLE INDEX; without a verb that rebuilds it, that is a claim
the product cannot demonstrate, which is the F6 class ("the code overclaims its
own guarantees") this project exists to eliminate.

These tests were written before the verb existed and were seen RED first.

Contract: DESIGN 7 (the verb table and `-h` semantics), DESIGN 15 ruling (c)
and the archive-first entry (the catalog is disposable), R2 (every write is
tmp-file plus os.replace), R4 (no deletes outside the rebuild module), R5 and
R10 (skip, name it, carry on), F4 (path is never identity), F6, F9.

TWO THINGS THE TREE CANNOT GIVE BACK, asserted here so a future change cannot
quietly start pretending otherwise:

  - `capture_event` history. The archive never held it.
  - superseded VERSIONS. An archive folder is keyed by uuid plus start time, so
    one uuid maps to one folder and the older copies of a grown session are not
    in the tree at all. A rebuild therefore yields one row per uuid.

Both are REPORTED by the verb rather than left for a reader to discover.
"""

import json
import sqlite3
from pathlib import Path
from typing import cast

from conftest import (
    catalog_path,
    catalog_rows,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    run_cli,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "a1111111-2222-3333-4444-555555555551"
UUID_B = "a1111111-2222-3333-4444-555555555552"
CWD_A = "/home/alice/CODE/alpha"
CWD_B = "/home/alice/CODE/beta"


def session(uuid: str, cwd: str, prompt: str = "Do the thing") -> bytes:
    return jsonl(
        entry(
            "user",
            prompt,
            "2026-05-07T03:47:45.000Z",
            session_id=uuid,
            cwd=cwd,
            gitBranch="main",
            version="2.0.0",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Done."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
            cwd=cwd,
        ),
    )


def capture(env: dict[str, str], uuid: str, data: bytes, cwd: str) -> None:
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=cwd, session_id=uuid))
    assert result.code == 0, result.err


def populated(env: dict[str, str], tmp_path: Path) -> Path:
    """Two sessions in two projects, archived. Returns the archive root."""
    capture(env, UUID_A, session(UUID_A, CWD_A), CWD_A)
    capture(env, UUID_B, session(UUID_B, CWD_B, prompt="Second thing"), CWD_B)
    target = tmp_path / "archive"
    result = run_ccw(["archive", "--to", str(target)], env)
    assert result.code == 0, result.err
    return target


def rows(env: dict[str, str], sql: str) -> list[object]:
    return catalog_rows(env, sql)


def count(env: dict[str, str], sql: str) -> int:
    """`catalog_rows` returns whole ROWS, so a COUNT(*) arrives as `(2,)`."""
    return int(cast("tuple[int, ...]", catalog_rows(env, sql)[0])[0])


def column(env: dict[str, str], sql: str) -> list[str]:
    """One column of a query, unwrapped from its single-element row tuples."""
    return [str(cast("tuple[object, ...]", row)[0]) for row in catalog_rows(env, sql)]


# ---------------------------------------------------------------------------
# The verb exists, is listed, and its help does nothing
# ---------------------------------------------------------------------------


def test_reindex_is_listed_in_the_top_level_help() -> None:
    """DESIGN 7: a verb that works but is not listed is a verb nobody finds."""
    assert "reindex" in run_cli(["-h"]).out


def test_reindex_help_prints_options_and_rebuilds_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The 2026-08-01 lesson: asking a tool for help must not make it act.
    Exit 0 plus output is NOT evidence that nothing happened, so this asks
    whether the world changed."""
    archive_dir = populated(ccw_env, tmp_path)
    before = tree_snapshot(warehouse_root(ccw_env))

    result = run_cli(["reindex", "--from", str(archive_dir), "-h"])

    assert result.code == 0
    assert "--from" in result.out
    assert tree_snapshot(warehouse_root(ccw_env)) == before, "help rebuilt the catalog"


# ---------------------------------------------------------------------------
# The round trip: delete the catalog, rebuild it from the tree alone
# ---------------------------------------------------------------------------


def test_reindex_restores_projects_and_aliases_from_the_tree_alone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """27.2. The fixture is asserted NON-EMPTY first, because a round trip over
    an empty set passes for the wrong reason (ticket 19f's lesson)."""
    archive_dir = populated(ccw_env, tmp_path)
    projects_before = rows(ccw_env, "SELECT label FROM project ORDER BY label")
    aliases_before = rows(
        ccw_env, "SELECT p.label, a.path, a.kind FROM project_alias a"
        " JOIN project p ON p.id = a.project_id ORDER BY p.label, a.kind, a.path"
    )
    assert projects_before, "fixture stored no projects, the round trip would prove nothing"
    assert aliases_before, "fixture stored no aliases, the round trip would prove nothing"

    catalog_path(ccw_env).unlink()
    result = run_ccw(["reindex", "--from", str(archive_dir)], ccw_env)

    assert result.code == 0, result.err
    assert rows(ccw_env, "SELECT label FROM project ORDER BY label") == projects_before
    assert (
        rows(
            ccw_env,
            "SELECT p.label, a.path, a.kind FROM project_alias a"
            " JOIN project p ON p.id = a.project_id ORDER BY p.label, a.kind, a.path",
        )
        == aliases_before
    )


def test_reindex_restores_the_payloads_own_facts(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R12/F4: identity and timestamps come from the payload, never from a path."""
    archive_dir = populated(ccw_env, tmp_path)
    before = rows(
        ccw_env,
        "SELECT hash, session_uuid, first_ts, last_ts, size_bytes, line_count, summary"
        " FROM session ORDER BY hash",
    )
    assert before

    catalog_path(ccw_env).unlink()
    assert run_ccw(["reindex", "--from", str(archive_dir)], ccw_env).code == 0

    assert (
        rows(
            ccw_env,
            "SELECT hash, session_uuid, first_ts, last_ts, size_bytes, line_count, summary"
            " FROM session ORDER BY hash",
        )
        == before
    )


def test_reindex_is_idempotent(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Run it twice against the same tree and the catalog says the same thing."""
    archive_dir = populated(ccw_env, tmp_path)
    catalog_path(ccw_env).unlink()

    assert run_ccw(["reindex", "--from", str(archive_dir)], ccw_env).code == 0
    once = rows(ccw_env, "SELECT hash, session_uuid FROM session ORDER BY hash")
    projects_once = rows(ccw_env, "SELECT label FROM project ORDER BY label")

    assert run_ccw(["reindex", "--from", str(archive_dir)], ccw_env).code == 0

    assert rows(ccw_env, "SELECT hash, session_uuid FROM session ORDER BY hash") == once
    assert rows(ccw_env, "SELECT label FROM project ORDER BY label") == projects_once


# ---------------------------------------------------------------------------
# Degraded trees: skip, name it, carry on (R5 / R10)
# ---------------------------------------------------------------------------


def test_a_corrupt_project_json_is_skipped_and_named_not_fatal(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R5: a rescan that dies on the first gap is a rescan nobody can run on a
    real archive. The project still exists, from its folder name; only its
    aliases are lost, and the loss is announced."""
    archive_dir = populated(ccw_env, tmp_path)
    sidecars = sorted(archive_dir.glob("*/project.json"))
    assert sidecars, "fixture wrote no project.json"
    sidecars[0].write_text("{ not json at all", encoding="utf-8")

    catalog_path(ccw_env).unlink()
    result = run_ccw(["reindex", "--from", str(archive_dir)], ccw_env)

    assert result.code == 0, result.err
    assert sidecars[0].parent.name in (result.out + result.err)
    assert count(ccw_env, "SELECT COUNT(*) FROM session") == 2


def test_a_label_dir_with_no_sidecar_still_becomes_a_project(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ticket 28.21. `read_projects` SKIPS a folder with no sidecar, but its
    sessions still need a project_id, so skipping it here would orphan them.
    The label falls back to the folder name and the gap is counted in the
    report rather than passing silently."""
    archive_dir = populated(ccw_env, tmp_path)
    sidecars = sorted(archive_dir.glob("*/project.json"))
    assert sidecars
    orphaned_label_dir = sidecars[0].parent.name
    sidecars[0].unlink()

    catalog_path(ccw_env).unlink()
    result = run_ccw(["reindex", "--from", str(archive_dir)], ccw_env)

    assert result.code == 0, result.err
    labels = column(ccw_env, "SELECT label FROM project ORDER BY label")
    assert orphaned_label_dir in labels
    assert count(ccw_env, "SELECT COUNT(*) FROM session") == 2
    assert "no project.json" in (result.out + result.err)


def test_an_unreadable_session_jsonl_is_named_and_the_batch_continues(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R10: name the failed item and carry on. Aborting on the first bad folder
    is what made the 2026-08-01 lone-surrogate failure diagnosable when it did
    NOT abort."""
    archive_dir = populated(ccw_env, tmp_path)
    victims = sorted(archive_dir.glob("*/*/*.jsonl"))
    assert victims
    victims[0].write_bytes(b"\x00\x01 not a transcript\n")

    catalog_path(ccw_env).unlink()
    result = run_ccw(["reindex", "--from", str(archive_dir)], ccw_env)

    assert victims[0].parent.name in (result.out + result.err)
    assert count(ccw_env, "SELECT COUNT(*) FROM session") >= 1


def test_a_tree_with_no_sessions_is_refused_not_written_empty(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Rebuilding nothing and exiting 0 is the failure mode that reads as
    success, exactly as `archive --verify` refuses an empty tree."""
    empty = tmp_path / "empty-archive"
    empty.mkdir()

    result = run_ccw(["reindex", "--from", str(empty)], ccw_env)

    assert result.code == 2
    assert "no session folders" in result.err


def test_reindex_refuses_a_source_that_does_not_exist(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Validated up front, before any work, the way `archive --to` is."""
    result = run_ccw(["reindex", "--from", str(tmp_path / "nope")], ccw_env)
    assert result.code == 2
    assert "no archive" in result.err


# ---------------------------------------------------------------------------
# It must not damage what it reads, and it must not lie about what it lost
# ---------------------------------------------------------------------------


def test_reindex_never_alters_the_tree_it_reads(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9/R4: the archive is the deliverable. A rebuild reads it and nothing
    more. Proved by snapshotting the whole tree, not by inspection."""
    archive_dir = populated(ccw_env, tmp_path)
    before = tree_snapshot(archive_dir)

    catalog_path(ccw_env).unlink()
    assert run_ccw(["reindex", "--from", str(archive_dir)], ccw_env).code == 0

    assert tree_snapshot(archive_dir) == before


def test_dry_run_reports_and_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ticket 23's precedent: a rehearsal that changes the world is not a
    rehearsal. The catalog is deleted first so its absence afterwards is the
    proof, not merely an unchanged mtime."""
    archive_dir = populated(ccw_env, tmp_path)
    catalog_path(ccw_env).unlink()
    before = tree_snapshot(warehouse_root(ccw_env))

    result = run_ccw(
        ["reindex", "--from", str(archive_dir), "--dry-run"], ccw_env
    )

    assert result.code == 0, result.err
    assert not catalog_path(ccw_env).exists(), "a dry run wrote a catalog"
    assert tree_snapshot(warehouse_root(ccw_env)) == before
    assert "would" in result.out


def test_reindex_says_what_it_cannot_recover(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F6: the tree never held capture_event history, and an archive folder is
    keyed by uuid so superseded versions are not in it either. Saying so is the
    difference between a rebuild and a rebuild that pretends to be complete."""
    archive_dir = populated(ccw_env, tmp_path)
    catalog_path(ccw_env).unlink()

    result = run_ccw(["reindex", "--from", str(archive_dir)], ccw_env)

    assert result.code == 0, result.err
    assert "capture_event" in result.out


def test_reindex_writes_the_catalog_atomically(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R2: every file write is tmp-file plus os.replace, so a half-built index
    is never observable. Asserted by leaving no temp file behind."""
    archive_dir = populated(ccw_env, tmp_path)
    catalog_path(ccw_env).unlink()

    assert run_ccw(["reindex", "--from", str(archive_dir)], ccw_env).code == 0

    leftovers = [p.name for p in warehouse_root(ccw_env).glob("*.tmp*")]
    assert leftovers == []
    assert catalog_path(ccw_env).is_file()


def test_the_newest_version_of_a_uuid_is_the_head_after_reindex(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ticket 29 mechanism 1 makes the newest INSERT the head regardless of the
    payload's own time, so a rebuild that walked the tree in directory order
    would make an arbitrary copy current. reindex sorts by payload time and
    inserts oldest first, which sidesteps the open defect rather than depending
    on it being fixed."""
    archive_dir = populated(ccw_env, tmp_path)
    catalog_path(ccw_env).unlink()
    assert run_ccw(["reindex", "--from", str(archive_dir)], ccw_env).code == 0

    heads = column(
        ccw_env,
        "SELECT session_uuid FROM session WHERE hash NOT IN"
        " (SELECT supersedes FROM session WHERE supersedes IS NOT NULL)"
        " ORDER BY session_uuid",
    )
    assert heads == sorted([UUID_A, UUID_B])


def test_to_targets_a_different_root_and_leaves_the_original_alone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`--to` is what lets 27.2's proof run against the REAL archive without
    rebuilding the catalog a live hook is writing to."""
    archive_dir = populated(ccw_env, tmp_path)
    before = tree_snapshot(warehouse_root(ccw_env))
    elsewhere = tmp_path / "rebuilt"

    result = run_ccw(
        ["reindex", "--from", str(archive_dir), "--to", str(elsewhere)],
        ccw_env,
    )

    assert result.code == 0, result.err
    assert tree_snapshot(warehouse_root(ccw_env)) == before, "--to wrote to the live root"
    conn = sqlite3.connect(elsewhere / "catalog.sqlite")
    try:
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 2
    finally:
        conn.close()


def test_a_sidecar_that_is_json_but_not_a_project_is_skipped(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Valid JSON of the wrong shape is the case a `try: json.loads` guard
    misses. `read_projects` already handles it; reindex must not undo that."""
    archive_dir = populated(ccw_env, tmp_path)
    sidecars = sorted(archive_dir.glob("*/project.json"))
    sidecars[0].write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")

    catalog_path(ccw_env).unlink()
    result = run_ccw(["reindex", "--from", str(archive_dir)], ccw_env)

    assert result.code == 0, result.err
    assert count(ccw_env, "SELECT COUNT(*) FROM session") == 2
