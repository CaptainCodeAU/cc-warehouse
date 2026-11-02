"""Oracle tests: a project's Claude Code memory is kept in the archive (2026-11-02).

    <root>/<label>/
        <stamp>_<uuid>/ ...                      the sessions, unchanged
        project.json
        _memory/<path>                           LATEST copy of each memory file
        _memory-history/<path>/<sha12><suffix>   EVERY version ever seen

Claude Code keeps per-project memory at `~/.claude/projects/<dir>/memory/`
(`MEMORY.md` plus topic files). Until today the sweep skipped it on purpose and
nothing else copied it: 1,200 files across 43 projects with no second copy.

THE PRINCIPAL'S RULING, Q4 option 1 and his own words: keep the latest AND every
earlier version, and "if ever a memory file is deleted, then it should not be
removed from the archive. Or for that matter, if the entire memory folder were
to be deleted, it should not be deleted from the archive." So nothing here ever
deletes, and an overwrite of the latest copy only happens after the bytes it
replaces are already safe in the history.

UNDERSCORE NAMES, because every plain folder inside a label folder is read as a
session folder; `_memory` and `_memory-history` are reserved the same way
`_not-sessions` is reserved one level up.

THE LABEL COMES FROM THE CATALOG, from the sessions in the same project dir,
never from the dir's encoded name, which derives a different label entirely.

Contract: R2, R4, R5, R9, R10; FINDINGS F1, F6.
"""

import hashlib
from pathlib import Path

from cc_warehouse import archive, build
from conftest import (
    basic_session,
    hook_payload,
    mark_archive,
    run_ccw,
    settle_companions,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
PARENT = "d3111111-2222-3333-4444-555555555551"
ENCODED = "-home-alice-projects-widget"
INDEX = b"# Memory index\n- [notes](notes.md)\n"
NOTES_A = b"first version of the notes\n"
NOTES_B = b"second version of the notes, longer\n"


def configure(env: dict[str, str], archive_root: Path, *, memory: bool | None = None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    if memory is not None:
        lines.append(f"archive_project_memory = {'true' if memory else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    mark_archive(archive_root, ZONE)


def project_dir(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects" / ENCODED


def memory_dir(env: dict[str, str]) -> Path:
    return project_dir(env) / "memory"


def plant_memory(env: dict[str, str], notes: bytes = NOTES_A) -> None:
    mem = memory_dir(env)
    (mem / "topics").mkdir(parents=True, exist_ok=True)
    (mem / "MEMORY.md").write_bytes(INDEX)
    (mem / "notes.md").write_bytes(notes)
    (mem / "topics" / "deep.md").write_bytes(b"nested topic\n")


def captured(env: dict[str, str], archive_root: Path) -> Path:
    """One session captured, so the catalog knows this project's label. Returns
    the label folder in the archive."""
    configure(env, archive_root)
    transcript = write_transcript(
        env, basic_session(session_id=PARENT), session_id=PARENT, name=f"{PARENT}.jsonl"
    )
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=PARENT))
    assert result.code == 0, result.err
    settle_companions(env)
    folders = sorted(archive_root.glob(f"*/*_{PARENT}"))
    assert len(folders) == 1, folders
    return folders[0].parent


def sweep(env: dict[str, str], *extra: str) -> str:
    result = run_ccw(["sweep", *extra], env)
    assert result.code == 0, result.err + result.out
    return result.out


def history_of(label_dir: Path, rel: str) -> dict[str, bytes]:
    where = label_dir / "_memory-history" / rel
    return {p.name: p.read_bytes() for p in sorted(where.iterdir())} if where.is_dir() else {}


def version_name(data: bytes, suffix: str = ".md") -> str:
    return hashlib.sha256(data).hexdigest()[:12] + suffix


# ---------------------------------------------------------------------------
# The copy
# ---------------------------------------------------------------------------


def test_a_sweep_copies_every_memory_file_into_the_project_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    latest = label_dir / "_memory"
    assert (latest / "MEMORY.md").read_bytes() == INDEX
    assert (latest / "notes.md").read_bytes() == NOTES_A
    assert (latest / "topics" / "deep.md").read_bytes() == b"nested topic\n"


def test_every_copied_version_is_also_kept_in_the_history(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    assert history_of(label_dir, "notes.md") == {version_name(NOTES_A): NOTES_A}
    assert history_of(label_dir, "topics/deep.md") == {
        version_name(b"nested topic\n"): b"nested topic\n"
    }


def test_an_edited_file_updates_the_latest_and_keeps_both_versions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env, NOTES_A)
    sweep(ccw_env)
    (memory_dir(ccw_env) / "notes.md").write_bytes(NOTES_B)
    sweep(ccw_env)
    assert (label_dir / "_memory" / "notes.md").read_bytes() == NOTES_B
    assert history_of(label_dir, "notes.md") == {
        version_name(NOTES_A): NOTES_A,
        version_name(NOTES_B): NOTES_B,
    }


def test_a_file_edited_back_to_an_old_version_loses_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env, NOTES_A)
    sweep(ccw_env)
    (memory_dir(ccw_env) / "notes.md").write_bytes(NOTES_B)
    sweep(ccw_env)
    (memory_dir(ccw_env) / "notes.md").write_bytes(NOTES_A)
    sweep(ccw_env)
    assert (label_dir / "_memory" / "notes.md").read_bytes() == NOTES_A
    assert len(history_of(label_dir, "notes.md")) == 2


# ---------------------------------------------------------------------------
# The ruling: a deletion at the source never reaches the archive
# ---------------------------------------------------------------------------


def test_a_memory_file_deleted_at_the_source_stays_in_the_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    (memory_dir(ccw_env) / "notes.md").unlink()
    sweep(ccw_env)
    assert (label_dir / "_memory" / "notes.md").read_bytes() == NOTES_A
    assert history_of(label_dir, "notes.md") == {version_name(NOTES_A): NOTES_A}


def test_a_whole_memory_folder_deleted_at_the_source_stays_in_the_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    mem = memory_dir(ccw_env)
    for path in sorted(mem.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    mem.rmdir()
    sweep(ccw_env)
    latest = label_dir / "_memory"
    assert (latest / "MEMORY.md").read_bytes() == INDEX
    assert (latest / "notes.md").read_bytes() == NOTES_A
    assert (latest / "topics" / "deep.md").read_bytes() == b"nested topic\n"


# ---------------------------------------------------------------------------
# It is not a session, and nothing mistakes it for one
# ---------------------------------------------------------------------------


def test_both_memory_names_are_reserved_inside_a_label_folder() -> None:
    assert archive.MEMORY_LATEST_DIR == "_memory"
    assert archive.MEMORY_HISTORY_DIR == "_memory-history"
    assert {"_memory", "_memory-history"} <= build.RESERVED_IN_LABEL


def test_the_archive_walk_never_yields_a_memory_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    names = [p.name for p in archive.walk_folders(archive_root)]
    assert names and not [n for n in names if n.startswith("_memory")]


def test_archive_verify_reports_no_problem_for_the_memory_folders(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    result = run_ccw(["archive", "--to", str(archive_root), "--verify"], ccw_env)
    assert result.code == 0, result.err + result.out
    assert "0 problems" in result.out + result.err


# ---------------------------------------------------------------------------
# The edges
# ---------------------------------------------------------------------------


def test_a_second_sweep_with_nothing_changed_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    before = {p: p.stat().st_mtime_ns for p in label_dir.rglob("*") if "_memory" in p.parts[-4:]}
    sweep(ccw_env)
    after = {p: p.stat().st_mtime_ns for p in label_dir.rglob("*") if "_memory" in p.parts[-4:]}
    assert before == after


def test_finder_files_are_not_copied(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    (memory_dir(ccw_env) / ".DS_Store").write_bytes(b"finder")
    sweep(ccw_env)
    assert not (label_dir / "_memory" / ".DS_Store").exists()


def test_the_source_memory_files_are_not_touched(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    before = {p: p.read_bytes() for p in memory_dir(ccw_env).rglob("*") if p.is_file()}
    sweep(ccw_env)
    after = {p: p.read_bytes() for p in memory_dir(ccw_env).rglob("*") if p.is_file()}
    assert before == after


def test_the_switch_off_copies_no_memory(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    configure(ccw_env, archive_root, memory=False)
    plant_memory(ccw_env)
    sweep(ccw_env)
    assert not (label_dir / "_memory").exists()


def test_a_project_unknown_to_the_catalog_is_kept_under_not_sessions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """No catalog row names this project's label, so its memory is NOT guessed
    into a label folder (R5) and NOT left uncopied either: it goes under
    `_not-sessions/memory/<source dir name>/`, the drawer for things with no
    session to belong to."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_memory(ccw_env)
    sweep(ccw_env)
    assert not list(archive_root.glob("*/_memory"))
    kept = archive_root / "_not-sessions" / "memory" / ENCODED / "_memory"
    assert (kept / "MEMORY.md").read_bytes() == INDEX


def test_a_project_whose_transcripts_are_gone_is_found_by_its_working_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Measured 2026-11-02: 5 real projects hold memory and no transcript at
    all. The catalog still records each session's working folder, and Claude
    Code's project dir name is that folder with every non-alphanumeric
    character made a dash, so the label is still knowable."""
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    (project_dir(ccw_env) / f"{PARENT}.jsonl").unlink()
    plant_memory(ccw_env)
    sweep(ccw_env)
    assert (label_dir / "_memory" / "MEMORY.md").read_bytes() == INDEX


OTHER = "-home-alice-projects-widget-old"
OTHER_UUID = "d3111111-2222-3333-4444-555555555552"
THIRD_UUID = "d3111111-2222-3333-4444-555555555553"


def test_two_project_dirs_sharing_one_label_never_overwrite_each_other(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Measured 2026-11-02: two real project dirs map to one label (a renamed
    project). One `_memory/` for both made their same-named files overwrite
    each other's latest copy on every sweep. The dir with the most sessions
    keeps the plain `_memory/`; each other one gets `_memory/_from-<dir>/`."""
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    for uuid, encoded in ((THIRD_UUID, ENCODED), (OTHER_UUID, OTHER)):
        transcript = write_transcript(
            ccw_env, basic_session(session_id=uuid), session_id=uuid, encoded_dir=encoded
        )
        result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=uuid))
        assert result.code == 0, result.err
    settle_companions(ccw_env)
    plant_memory(ccw_env, NOTES_A)
    other_mem = project_dir(ccw_env).parent / OTHER / "memory"
    other_mem.mkdir(parents=True)
    (other_mem / "notes.md").write_bytes(NOTES_B)
    sweep(ccw_env)
    assert (label_dir / "_memory" / "notes.md").read_bytes() == NOTES_A
    assert (label_dir / "_memory" / f"_from-{OTHER}" / "notes.md").read_bytes() == NOTES_B
    before = {p: p.stat().st_mtime_ns for p in label_dir.rglob("*") if "_memory" in p.parts}
    sweep(ccw_env)
    after = {p: p.stat().st_mtime_ns for p in label_dir.rglob("*") if "_memory" in p.parts}
    assert before == after


def test_a_memory_file_whose_name_starts_with_an_underscore_is_copied(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Found on the real share: 11 files named `_index-*.md` failed, because the
    temp file became `._index-...` and Samba refuses names starting `._`."""
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    (memory_dir(ccw_env) / "_index-boxes.md").write_bytes(b"boxes\n")
    sweep(ccw_env)
    assert (label_dir / "_memory" / "_index-boxes.md").read_bytes() == b"boxes\n"


def test_a_dry_run_names_the_memory_it_would_copy_and_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    label_dir = captured(ccw_env, archive_root)
    plant_memory(ccw_env)
    out = sweep(ccw_env, "--dry-run")
    assert "would-archive-memory" in out
    assert not (label_dir / "_memory").exists()
