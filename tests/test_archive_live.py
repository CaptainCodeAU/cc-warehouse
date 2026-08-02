"""Oracle tests: the capture path keeps the archive current (ticket 19, slice 19i).

Everything built before this slice made the archive an EXPORT: `ccw archive`
filled a tree once and nothing kept it there, so every new session landed in the
old store and the tree drifted from the moment the command finished. This is the
slice that makes it a mirror instead of a photograph.

DUAL-WRITE, opt-in. `archive_root` unset means the capture path behaves exactly
as it does today, byte for byte, so this slice cannot regress a live warehouse
by existing. Set it and the hook's own detached render child writes the archive
folder alongside the projection it already writes. Both trees stay current until
the swap, which is what makes the swap a decision rather than a leap.

Contract: DESIGN section 4 (capture, and the detached render child as the last
surviving failure signal); DESIGN 15 2026-08-02 (archive-first); R9 (the SAME
naming and folder-writing functions as `ccw archive`, never a second copy); R5 /
DESIGN 12 (a child failure never turns a stored capture into a lost one).
"""

import json
from pathlib import Path
from typing import cast

from cc_warehouse import archive
from conftest import (
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "c9111111-2222-3333-4444-555555555551"
UUID_B = "c9111111-2222-3333-4444-555555555552"
CWD = "/home/alice/projects/widget"


def session(uuid: str, prompt: str = "Do the thing", extra: bytes = b"") -> bytes:
    return (
        jsonl(
            entry(
                "user",
                prompt,
                "2026-05-07T03:47:45.000Z",
                session_id=uuid,
                cwd=CWD,
                gitBranch="main",
                version="2.1.220",
            ),
            entry(
                "assistant",
                [{"type": "text", "text": "Done."}],
                "2026-05-07T03:47:50.000Z",
                session_id=uuid,
                cwd=CWD,
            ),
        )
        + extra
    )


def configure(env: dict[str, str], tmp_path: Path, archive_root: Path | None) -> None:
    """Write an XDG config, with or without `archive_root`."""
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(Path(env["HOME"]) / ".config")


def capture(env: dict[str, str], uuid: str, data: bytes) -> None:
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=CWD, session_id=uuid))
    assert result.code == 0, result.err
    # The hook spawns a DETACHED child; render synchronously so the assertions
    # below are about behaviour rather than about a race with a background pid.
    rendered = run_ccw(["render", "--session", f"s:{_short(env, uuid)}"], env)
    assert rendered.code == 0, rendered.err


def _short(env: dict[str, str], uuid: str) -> str:
    from conftest import catalog_rows

    # The HEAD of the uuid's chain: the row no other row supersedes. `session`
    # is keyed by hash and has no rowid ordering to lean on, and taking the
    # wrong version here would render a superseded payload and quietly make
    # every assertion below describe the wrong file.
    rows = catalog_rows(
        env,
        "SELECT short FROM session WHERE session_uuid = ?"
        " AND hash NOT IN (SELECT supersedes FROM session WHERE supersedes IS NOT NULL)",
        (uuid,),
    )
    assert rows, f"fixture did not store {uuid}; every assertion below is vacuous"
    assert len(rows) == 1, f"expected one head for {uuid}, got {len(rows)}"
    row = cast("tuple[str]", rows[0])
    return str(row[0])


# ---------------------------------------------------------------------------
# The opt-in: unset means nothing changes at all
# ---------------------------------------------------------------------------


def test_with_no_archive_root_the_capture_path_is_unchanged(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The safety property that lets this slice exist at all. A warehouse whose
    config says nothing about an archive must behave exactly as it did before
    the slice landed."""
    configure(ccw_env, tmp_path, None)
    capture(ccw_env, UUID_A, session(UUID_A))

    root = warehouse_root(ccw_env)
    assert (root / "projections").is_dir(), "the ordinary projection is still written"
    assert not (tmp_path / "archive").exists()
    # Nothing archive-shaped anywhere under the warehouse either.
    assert not list(root.glob("*/2026*_*"))


# ---------------------------------------------------------------------------
# Set it, and the archive keeps itself current
# ---------------------------------------------------------------------------


def test_a_captured_session_lands_in_the_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The whole point of the slice: no `ccw archive` run, and the folder is
    there."""
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))

    folders = list(archive.walk_folders(target))
    assert len(folders) == 1, folders
    names = {p.name for p in folders[0].iterdir()}
    assert f"{UUID_A}.jsonl" in names
    for generated in archive.GENERATED_NAMES:
        assert generated in names, generated


def test_the_archived_jsonl_matches_the_captured_source(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    data = session(UUID_A)
    capture(ccw_env, UUID_A, data)
    folder = next(archive.walk_folders(target))
    assert (folder / f"{UUID_A}.jsonl").read_bytes() == data


def test_the_hook_and_the_verb_agree_on_the_folder_name(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R9. The capture path and `ccw archive` must call the SAME naming function,
    or a session captured live and the same session migrated would sit in two
    different folders and the tree would silently double."""
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))
    live = next(archive.walk_folders(target)).name

    from cc_warehouse.build import archive_folder_name

    assert live == archive_folder_name("2026-05-07T03:47:45.000Z", UUID_A, ZONE)


def test_the_old_projection_is_still_written(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DUAL-write, not a cutover. Until the swap both trees must stay current,
    because the old one is the live warehouse and the new one is unproven."""
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))

    projections = warehouse_root(ccw_env) / "projections"
    dirs = [p for p in projections.glob("*/*") if p.is_dir()]
    assert len(dirs) == 1, dirs
    assert (dirs[0] / "transcript.md").is_file()


def test_two_captures_produce_two_archive_folders(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))
    capture(ccw_env, UUID_B, session(UUID_B, prompt="Second thing"))
    assert len(list(archive.walk_folders(target))) == 2


def test_re_capturing_the_same_session_is_idempotent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A re-render must not churn the tree: a backup tool that sees every folder
    change on every session is a backup tool nobody runs."""
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))
    before = tree_snapshot(target)
    run_ccw(["render", "--session", f"s:{_short(ccw_env, UUID_A)}"], ccw_env)
    assert tree_snapshot(target) == before


def test_a_grown_session_replaces_in_place(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Start-keyed names are immutable, so a session that continues lands in the
    folder it already occupies instead of sprouting a second one."""
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))
    grown = session(UUID_A) + jsonl(
        entry(
            "assistant",
            [{"type": "text", "text": "GROWNMARKER and more."}],
            "2026-05-07T04:00:00.000Z",
            session_id=UUID_A,
            cwd=CWD,
        )
    )
    capture(ccw_env, UUID_A, grown)

    folders = list(archive.walk_folders(target))
    assert len(folders) == 1, "a continued session created a second folder"
    assert b"GROWNMARKER" in (folders[0] / f"{UUID_A}.jsonl").read_bytes()
    assert "GROWNMARKER" in (folders[0] / "transcript.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Failure never costs the capture
# ---------------------------------------------------------------------------


def test_an_unwritable_archive_root_does_not_lose_the_capture(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN 12 / R5: the detached child's failures must never turn a STORED
    capture into a lost one. The session is already in the store by the time the
    archive write is attempted, and it must stay there."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("this is a file, so mkdir under it must fail", encoding="utf-8")
    configure(ccw_env, tmp_path, blocker / "archive")

    transcript = write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    result = run_ccw(
        ["hook"], ccw_env, stdin=hook_payload(transcript, cwd=CWD, session_id=UUID_A)
    )
    assert result.code == 0, "an archive problem must not fail the capture"

    from conftest import session_count

    assert session_count(ccw_env) == 1, "the session was not stored"


def test_the_ordinary_projection_survives_an_archive_failure(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The archive is the NEW tree and the projections are the LIVE one. An
    archive problem must not cost the tree the operator actually uses today."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    configure(ccw_env, tmp_path, blocker / "archive")
    transcript = write_transcript(ccw_env, session(UUID_A), session_id=UUID_A)
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=CWD, session_id=UUID_A))
    run_ccw(["render", "--session", f"s:{_short(ccw_env, UUID_A)}"], ccw_env)

    dirs = [p for p in (warehouse_root(ccw_env) / "projections").glob("*/*") if p.is_dir()]
    assert len(dirs) == 1
    assert (dirs[0] / "transcript.md").is_file()


# ---------------------------------------------------------------------------
# What lands is the same thing `ccw archive` would have written
# ---------------------------------------------------------------------------


def test_the_live_folder_passes_the_same_integrity_check(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))
    folder = next(archive.walk_folders(target))
    assert archive.verify_folder(folder, ZONE) == []


def test_the_live_manifest_carries_the_same_keys(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, tmp_path, target)
    capture(ccw_env, UUID_A, session(UUID_A))
    folder = next(archive.walk_folders(target))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["unrecognised"] == {"count": 0, "types": []}
    assert manifest["withheld"] == {"thinking_blocks": 0}
    assert set(manifest["loss"]) == {
        "skipped_lines",
        "truncated_blocks",
        "truncated_chars",
        "unencodable_chars",
    }
