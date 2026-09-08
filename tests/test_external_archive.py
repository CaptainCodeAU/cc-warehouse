"""Oracle tests: file-history and todos inside their session folder (39b).

    <root>/<label>/<stamp>_<uuid>/
        <uuid>.jsonl   ...   manifest.json
        tool-results/       (ticket 38)
        workflows/          (ticket 38)
        file-history/       THIS SLICE - <hash>@vN, flat mirror
        todos/              THIS SLICE - the session's own todo files

THE SAME COPIER, deliberately. `file-history/` is a flat directory of versioned
snapshots, which is mechanically what `tool-results/` already was, so this slice
adds two NAMES and one file-level writer rather than a second copying mechanism.
That is what "39 reuses 38's primitives" has to mean in practice: if this had
grown its own `_mirror_tree`, the two would have drifted the first time either was
touched (C12's whole argument).

WHY IT MATTERS MORE THAN ITS LINE COUNT. 929,845,225 bytes measured 2026-09-08,
and sampling 23 snapshots across 12 sessions found the first 200 bytes of each in
that session's own transcript ZERO times. Nothing else holds this.

Contract: DESIGN 6 (new top-level manifest keys, never `loss` amendments), R2, R4
as amended, R5, R9; FINDINGS F1, F4, F6.
"""

import ast
import json
from pathlib import Path
from typing import cast

from cc_warehouse import archive, external, store
from cc_warehouse.render import RenderOptions
from conftest import DEFAULT_UUID, SRC_ROOT, basic_session

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
SNAP = "23527e7c@v1"
SNAP_BYTES = b"--- a/widget.py\n+++ b/widget.py\n@@ -1 +1 @@\n-old\n+new\n"


def parent_folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE
    ).directory


def source_history(tmp_path: Path) -> Path:
    src = tmp_path / ".claude" / "file-history" / DEFAULT_UUID
    src.mkdir(parents=True)
    (src / SNAP).write_bytes(SNAP_BYTES)
    (src / "23527e7c@v2").write_bytes(b"a later version\n")
    (src / ".DS_Store").write_bytes(b"\x00")
    return src


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def listed(folder: Path, key: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], manifest_of(folder)[key])


def rebuild(root: Path) -> None:
    archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )


# ---------------------------------------------------------------------------
# The fence: one list of companion directories, and every name has a copier
# ---------------------------------------------------------------------------


def test_every_external_store_is_a_known_companion_directory() -> None:
    """Ticket 38's fence, extended rather than duplicated. A store `external.py`
    names but `archive.py` cannot write is the "parses, is tested, does nothing"
    shape that fence exists to forbid."""
    assert external.SESSION_STORES <= set(archive.COMPANION_MANIFEST_KEYS)


def test_the_companion_key_set_is_exactly_the_five_names() -> None:
    """39e widens this to a fifth name, `pastes` - see test_paste_cache_archive.py
    for that companion's own dedicated coverage."""
    assert set(archive.COMPANION_MANIFEST_KEYS) == {
        "tool-results",
        "workflows",
        "file-history",
        "todos",
        "pastes",
    }


def test_no_companion_name_is_a_generated_file(tmp_path: Path) -> None:
    """`GENERATED_NAMES` drives what the rebuild module may delete. A copied
    snapshot is not regenerable from the payload and is not the rebuilder's to
    remove (R4)."""
    assert not set(archive.COMPANION_MANIFEST_KEYS) & set(archive.GENERATED_NAMES)


# ---------------------------------------------------------------------------
# The copy
# ---------------------------------------------------------------------------


def test_a_snapshot_lands_under_the_session_folder_with_its_original_bytes(
    tmp_path: Path,
) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    assert (folder / "file-history" / SNAP).read_bytes() == SNAP_BYTES


def test_every_version_of_a_snapshot_is_kept(tmp_path: Path) -> None:
    """`@v1..@vN` are different files, not revisions of one. The live store has
    versions up to @v8; keeping only the newest would discard the history that is
    the entire point of the directory."""
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    names = sorted(p.name for p in (folder / "file-history").iterdir())
    assert names == ["23527e7c@v1", "23527e7c@v2"]


def test_ds_store_is_not_copied(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    assert not (folder / "file-history" / ".DS_Store").exists()


def test_a_second_copy_of_the_same_bytes_writes_nothing(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    src = source_history(tmp_path)
    archive.copy_companion_dir(folder, "file-history", src)
    again = archive.copy_companion_dir(folder, "file-history", src)
    assert (again.written, again.unchanged) == (0, 2)


def test_a_changed_snapshot_under_the_same_name_is_refused(tmp_path: Path) -> None:
    """R5, and it is not hypothetical: ticket 38's acceptance run hit exactly this
    on live data within twenty minutes. A snapshot is source-class data with no
    larger-is-better ordering, so the archived copy wins and the refusal is named."""
    folder = parent_folder(tmp_path)
    src = source_history(tmp_path)
    archive.copy_companion_dir(folder, "file-history", src)
    (src / SNAP).write_bytes(b"different content entirely")
    result = archive.copy_companion_dir(folder, "file-history", src)
    assert result.refused == (SNAP,)
    assert (folder / "file-history" / SNAP).read_bytes() == SNAP_BYTES


def test_a_todo_file_is_copied_by_name_into_the_todos_directory(tmp_path: Path) -> None:
    """`todos/` is loose FILES keyed by a name prefix, not a directory per session,
    so it uses the file-level writer rather than the tree mirror."""
    folder = parent_folder(tmp_path)
    src = tmp_path / ".claude" / "todos" / f"{DEFAULT_UUID}-agent-{DEFAULT_UUID}.json"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"[]")
    archive.write_companion_file(folder, "todos", Path(src.name), src.read_bytes())
    assert (folder / "todos" / src.name).read_bytes() == b"[]"


def test_writing_a_session_folder_alone_creates_no_companion_directory(
    tmp_path: Path,
) -> None:
    folder = parent_folder(tmp_path)
    assert not (folder / "file-history").exists()
    assert not (folder / "todos").exists()


def test_a_path_that_escapes_the_session_folder_is_refused(tmp_path: Path) -> None:
    """The names come from a directory tree this project does not own, so the
    guard is not theatre: a path that climbed out would write source-class data
    somewhere nobody would look for it (F9)."""
    folder = parent_folder(tmp_path)
    try:
        archive.write_companion_file(folder, "file-history", Path("../escaped"), b"x")
    except ValueError:
        return
    raise AssertionError("an escaping relative path must be refused")


# ---------------------------------------------------------------------------
# Manifest and verify
# ---------------------------------------------------------------------------


def test_the_manifest_lists_each_snapshot_with_its_hash_and_size(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    rebuild(tmp_path)
    records = listed(folder, "file_history")
    assert {r["name"] for r in records} == {SNAP, "23527e7c@v2"}
    first = next(r for r in records if r["name"] == SNAP)
    assert first["sha256"] == store.sha256_hex(SNAP_BYTES)
    assert first["bytes"] == len(SNAP_BYTES)


def test_both_new_keys_are_empty_lists_when_a_session_has_neither(tmp_path: Path) -> None:
    """F6: `[]` says "none", a missing key says "this manifest predates the
    feature". Every one of ~29,600 existing folders is in the second state until
    the next full rebuild reaches it."""
    manifest = manifest_of(parent_folder(tmp_path))
    assert manifest["file_history"] == []
    assert manifest["todos"] == []


def test_a_folder_stops_being_current_once_a_snapshot_is_added(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    assert archive.folder_is_current(folder, digest, OPTS) is True
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    assert archive.folder_is_current(folder, digest, OPTS) is False


def test_verify_reports_a_snapshot_that_has_been_deleted(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    rebuild(tmp_path)
    (folder / "file-history" / SNAP).unlink()
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert f"file-history entry {SNAP} is missing" in problems, problems


def test_verify_reports_a_snapshot_whose_bytes_changed(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    rebuild(tmp_path)
    (folder / "file-history" / SNAP).write_bytes(b"tampered")
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert any("does not match its hash" in p for p in problems), problems


def test_no_companion_problem_string_starts_with_the_word_missing(tmp_path: Path) -> None:
    """`doctor._desync` reclassifies a folder whose problems ALL start with
    `missing ` as "still queued behind a render" (ticket 34). A snapshot is never
    queued behind anything, so borrowing the word would hide a real loss forever."""
    folder = parent_folder(tmp_path)
    archive.copy_companion_dir(folder, "file-history", source_history(tmp_path))
    rebuild(tmp_path)
    (folder / "file-history" / SNAP).unlink()
    named = [p.problem for p in archive.verify_folder(folder, ZONE) if "file-history" in p.problem]
    assert named
    assert not any(p.startswith("missing ") for p in named)


def test_a_manifest_written_before_this_slice_raises_no_new_problems(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    manifest = manifest_of(folder)
    del manifest["file_history"]
    del manifest["todos"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert archive.verify_folder(folder, ZONE) == []


# ---------------------------------------------------------------------------
# Stranded snapshots (42 of the live 1,056)
# ---------------------------------------------------------------------------


def test_a_stranded_snapshot_dir_is_copied_under_not_sessions(tmp_path: Path) -> None:
    """Its session is not in the archive, so there is no folder to nest under. The
    directory name is recorded as a LABEL and never used to invent one (F4), the
    same call ticket 38's ruling (d) made for stranded sidecars."""
    src = tmp_path / ".claude" / "file-history" / "99999999-0000-4000-8000-000000000000"
    src.mkdir(parents=True)
    (src / SNAP).write_bytes(SNAP_BYTES)
    archive.write_stranded_file_history(tmp_path, src)
    landed = (
        tmp_path
        / "_not-sessions"
        / "stranded-file-history"
        / "99999999-0000-4000-8000-000000000000"
        / SNAP
    )
    assert landed.read_bytes() == SNAP_BYTES


def test_a_stranded_snapshot_copy_records_why_it_is_there(tmp_path: Path) -> None:
    src = tmp_path / ".claude" / "file-history" / "99999999-0000-4000-8000-000000000000"
    src.mkdir(parents=True)
    (src / SNAP).write_bytes(SNAP_BYTES)
    archive.write_stranded_file_history(tmp_path, src)
    note = json.loads(
        (
            tmp_path
            / "_not-sessions"
            / "stranded-file-history"
            / "99999999-0000-4000-8000-000000000000"
            / "stranded.json"
        ).read_text("utf-8")
    )
    assert note["dir_name"] == "99999999-0000-4000-8000-000000000000"
    assert note["reason"] == "no archived session holds this id"


# ---------------------------------------------------------------------------
# R4 re-asserted: this slice added writers and still no deleter
# ---------------------------------------------------------------------------


def test_neither_module_has_a_deletion_primitive() -> None:
    for name in ("archive.py", "external.py"):
        tree = ast.parse((SRC_ROOT / name).read_text(encoding="utf-8"))
        offenders = [
            f"{name}:{node.lineno} .{node.func.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"unlink", "rmdir", "rmtree", "remove", "removedirs"}
        ]
        assert not offenders, f"deletion primitives (R4): {offenders}"
