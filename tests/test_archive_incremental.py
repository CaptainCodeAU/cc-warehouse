"""Oracle tests: incremental archive rebuild (ticket 30).

`ccw archive`'s weekly run redid all ~20,000+ session folders on every pass -
4 documents plus a manifest each, ~40 minutes at ~90% CPU on a real machine
(measured 2026-08-18) - even though almost nothing had changed since the last
run. `archive.folder_is_current` answers "would rebuilding this folder produce
byte-identical output" from `manifest.json` alone, and both `write_session_folder`
and `_migrate_locked` skip the read-parse-render path entirely when it says yes.

Contract: DESIGN section 6 (the manifest's frozen `source_hash`/`config` keys,
now joined by `renderer_version`), section 15 2026-08-18 (the decision); R5 (any
doubt is the conservative branch); R9 (one predicate, not two copies of this
truth); F6 (a skip must never make a stale folder look current).

THE TWO HAZARDS THAT MAKE THIS MORE THAN A CACHE. Skipping the render is
strictly stronger than `ccw build`'s existing incrementality (`build.
_write_if_changed`, which always renders and only skips the WRITE after a full
byte-compare). Two things a byte-compare-after-render would have caught for
free had to be checked explicitly instead:

  1. A `ccw` upgrade that changes rendered output must still reach every
     existing folder eventually - `renderer_version` in the manifest is what
     makes an old folder "not current" after an upgrade, not just after a
     content change.
  2. A sub-agent captured after its parent's last render must still force a
     rebuild, or its parent's manifest never lists it and a later deletion of
     that sub-agent's folder becomes undetectable by `ccw archive --verify`
     (`subagent_records`' own docstring: "the most dangerous kind of green").
"""

import json
from pathlib import Path
from typing import cast

from cc_warehouse import __version__, archive, build, store
from cc_warehouse.render import RenderOptions
from conftest import (
    DEFAULT_UUID,
    basic_session,
    catalog_rows,
    entry,
    hook_payload,
    jsonl,
    run_ccw,
    run_cli,
    subagent_meta,
    subagent_session,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
UUID_A = "d0111111-2222-3333-4444-555555555551"
UUID_B = "d0111111-2222-3333-4444-555555555552"
_MANIFEST = archive.GENERATED_NAMES[-1]
_RENDERED = archive.GENERATED_NAMES[:-1]


def session(uuid: str = UUID_A, prompt: str = "Do the thing") -> bytes:
    return jsonl(
        entry("user", prompt, "2026-05-07T03:47:45.000Z", session_id=uuid, gitBranch="main",
              version="2.0.0"),
        entry("assistant", [{"type": "text", "text": "Done."}],
              "2026-05-07T03:47:50.000Z", session_id=uuid),
    )


def manifest_of(directory: Path) -> dict[str, object]:
    return json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))


def mtimes_of(directory: Path) -> dict[str, int]:
    return {name: (directory / name).stat().st_mtime_ns for name in archive.GENERATED_NAMES}


# ---------------------------------------------------------------------------
# folder_is_current: the predicate, in isolation
# ---------------------------------------------------------------------------


def test_folder_is_current_true_when_everything_matches(tmp_path: Path) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    assert archive.folder_is_current(result.directory, store.sha256_hex(session()), OPTS)


def test_folder_is_current_false_with_no_manifest(tmp_path: Path) -> None:
    empty = tmp_path / "nothing-here"
    empty.mkdir()
    assert not archive.folder_is_current(empty, store.sha256_hex(session()), OPTS)


def test_folder_is_current_false_with_a_corrupt_manifest(tmp_path: Path) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    (result.directory / _MANIFEST).write_text("not json{{{", encoding="utf-8")
    assert not archive.folder_is_current(result.directory, store.sha256_hex(session()), OPTS)


def test_folder_is_current_false_on_a_hash_mismatch(tmp_path: Path) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    assert not archive.folder_is_current(result.directory, "0" * 64, OPTS)


def test_folder_is_current_false_on_a_config_mismatch(tmp_path: Path) -> None:
    result = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    changed = RenderOptions(thinking_withheld="marker")
    assert not archive.folder_is_current(
        result.directory, store.sha256_hex(session()), changed
    )


def test_folder_is_current_false_on_a_renderer_version_mismatch(tmp_path: Path) -> None:
    """H1. Without this, a `ccw` upgrade that changes rendered output would
    leave every existing folder frozen at the old format forever."""
    result = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    manifest = manifest_of(result.directory)
    assert manifest["renderer_version"] == __version__  # the fixture assumption
    manifest["renderer_version"] = "0.0.0-older"
    (result.directory / _MANIFEST).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    assert not archive.folder_is_current(
        result.directory, store.sha256_hex(session()), OPTS
    )


def test_folder_is_current_false_when_a_generated_file_is_missing(tmp_path: Path) -> None:
    """Regression (found live, 2026-08-18, running this ticket's own test suite):
    a manifest that still looks current says nothing about its four siblings. A
    deleted `transcript.md` beside an otherwise-untouched manifest must still be
    read as \"rebuild\", or `ccw build --rebuild`'s existing self-healing quietly
    stops working the moment this skip exists."""
    result = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    (result.directory / "transcript.md").unlink()
    assert not archive.folder_is_current(
        result.directory, store.sha256_hex(session()), OPTS
    )


def test_a_deleted_generated_file_is_restored_by_a_later_write(tmp_path: Path) -> None:
    first = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    (first.directory / "transcript.md").unlink()
    second = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    assert not second.skipped_current
    assert (second.directory / "transcript.md").is_file()


def test_folder_is_current_false_on_a_stale_subagent_list(tmp_path: Path) -> None:
    """H2. A sub-agent folder existing on disk but absent from the manifest's
    `subagents` list must force a rebuild, or the list never catches up."""
    result = archive.write_session_folder(
        tmp_path, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE
    )
    assert manifest_of(result.directory)["subagents"] == []
    archive.write_subagent(
        tmp_path, LABEL, subagent_session(parent_uuid=DEFAULT_UUID), ZONE,
        meta=subagent_meta(),
    )
    source_hash = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    assert not archive.folder_is_current(result.directory, source_hash, OPTS)


# ---------------------------------------------------------------------------
# write_session_folder: the skip, end to end
# ---------------------------------------------------------------------------


def test_an_unchanged_session_is_skipped_and_nothing_moves(tmp_path: Path) -> None:
    first = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    assert not first.skipped_current
    before = mtimes_of(first.directory)

    second = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    assert second.skipped_current
    assert second.wrote_projections
    assert mtimes_of(second.directory) == before, "an unchanged folder was rewritten"


def test_a_changed_payload_forces_a_rebuild(tmp_path: Path) -> None:
    first = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    original_hash = manifest_of(first.directory)["source_hash"]

    changed = session() + jsonl(
        entry("assistant", [{"type": "text", "text": "One more thing."}],
              "2026-05-07T03:48:00.000Z", session_id=UUID_A),
    )
    second = archive.write_session_folder(tmp_path, LABEL, changed, OPTS, ZONE)
    assert not second.skipped_current
    assert second.directory == first.directory  # same session, same folder
    assert manifest_of(second.directory)["source_hash"] == store.sha256_hex(changed)
    assert manifest_of(second.directory)["source_hash"] != original_hash


def test_rebuild_flag_bypasses_the_skip_even_when_current(tmp_path: Path) -> None:
    first = archive.write_session_folder(tmp_path, LABEL, session(), OPTS, ZONE)
    before = mtimes_of(first.directory)
    second = archive.write_session_folder(
        tmp_path, LABEL, session(), OPTS, ZONE, rebuild=True
    )
    assert not second.skipped_current
    assert mtimes_of(second.directory) != before, "--rebuild must rewrite even a current folder"


def test_a_refusal_is_never_skipped_even_when_the_surviving_hash_still_matches(
    tmp_path: Path,
) -> None:
    """Regression guard. The surviving (larger) payload's hash still matches the
    existing manifest on a refusal, so a naive skip-check would treat the
    refused call as \"current\" and never record the refusal at all (F6)."""
    full = session() + jsonl(
        entry("assistant", [{"type": "text", "text": "The rest of it."}],
              "2026-05-07T03:48:10.000Z", session_id=UUID_A),
    )
    truncated = session()
    assert len(full) > len(truncated)

    archive.write_session_folder(tmp_path, LABEL, full, OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, truncated, OPTS, ZONE)
    assert result.refused_smaller
    assert not result.skipped_current
    manifest = manifest_of(result.directory)
    assert "replace_refused" in manifest
    assert manifest["source_hash"] == store.sha256_hex(full)


def test_a_subagent_added_after_the_parents_render_forces_a_rebuild_and_gets_listed(
    tmp_path: Path,
) -> None:
    data = basic_session(session_id=DEFAULT_UUID)
    first = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert manifest_of(first.directory)["subagents"] == []

    archive.write_subagent(
        tmp_path, LABEL, subagent_session(parent_uuid=DEFAULT_UUID), ZONE,
        meta=subagent_meta(),
    )
    second = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert not second.skipped_current
    listed = manifest_of(second.directory)["subagents"]
    assert isinstance(listed, list)
    assert len(cast(list[object], listed)) == 1


# ---------------------------------------------------------------------------
# The write order the skip depends on
# ---------------------------------------------------------------------------


def test_manifest_is_yielded_last() -> None:
    """Pins the invariant `folder_is_current` relies on for safety under an
    interrupted run: a kill mid-loop can only leave a STALE manifest beside
    fresh pages, never the reverse. Reordering these yields would silently
    break that safety with nothing else here going red."""
    names = [name for name, _ in build.iter_projection_files(session(), OPTS)]
    assert names[-1] == _MANIFEST
    assert names == list(_RENDERED) + [_MANIFEST]


def test_an_interrupted_run_leaves_a_stale_manifest_which_forces_a_rebuild(
    tmp_path: Path,
) -> None:
    """Simulates a kill after the four pages were rewritten but before the
    manifest write reached disk: the folder holds NEW pages beside the OLD
    manifest. The skip-check must not read that as \"current\"."""
    old = session()
    new = old + jsonl(
        entry("assistant", [{"type": "text", "text": "A second reply."}],
              "2026-05-07T03:48:20.000Z", session_id=UUID_A),
    )
    first = archive.write_session_folder(tmp_path, LABEL, old, OPTS, ZONE)
    stale_manifest = (first.directory / _MANIFEST).read_bytes()

    # Simulate the interruption: the four pages get rewritten from the NEW
    # payload, but the manifest write never lands (kill mid-loop).
    new_pages = dict(build.iter_projection_files(new, OPTS))
    for name in _RENDERED:
        store.atomic_write(first.directory / name, new_pages[name])
    assert (first.directory / _MANIFEST).read_bytes() == stale_manifest

    retry = archive.write_session_folder(tmp_path, LABEL, new, OPTS, ZONE)
    assert not retry.skipped_current, "a stale manifest was trusted as current"
    assert manifest_of(retry.directory)["source_hash"] == store.sha256_hex(new)
    for name in _RENDERED:
        assert (retry.directory / name).read_bytes() == new_pages[name]


# ---------------------------------------------------------------------------
# The big win: skipping before the stored payload is even read
# ---------------------------------------------------------------------------


def populated(env: dict[str, str]) -> None:
    for uuid, prompt in ((UUID_A, "Do the thing"), (UUID_B, "Second thing")):
        transcript = write_transcript(env, session(uuid, prompt), session_id=uuid,
                                       name=f"{uuid}.jsonl")
        result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=None, session_id=uuid))
        assert result.code == 0, result.err


def test_a_second_archive_run_reports_everything_as_unchanged(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    result = run_cli(["archive", "--to", str(target)])
    assert result.code == 0, result.err
    assert "2 unchanged" in result.out


def test_a_second_archive_run_never_reads_the_stored_payload_for_unchanged_sessions(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE BIG WIN, proved black-box. If the skip happened anywhere other than
    before `store.get()`, deleting the stored object would surface as a failure
    on the second run; instead it must not even be touched."""
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0

    root = warehouse_root(ccw_env)
    for row in catalog_rows(ccw_env, "SELECT hash FROM session"):
        hash_ = cast(tuple[str], row)[0]
        store.object_path(root, str(hash_)).unlink()

    result = run_cli(["archive", "--to", str(target)])
    assert result.code == 0, result.err
    assert "0 failed" in result.out
    assert "2 unchanged" in result.out


def test_a_second_run_is_a_true_no_op_on_the_tree(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    before = tree_snapshot(target)
    assert run_cli(["archive", "--to", str(target)]).code == 0
    assert tree_snapshot(target) == before


def test_rebuild_forces_every_folder_through_the_full_path_even_when_current(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    populated(ccw_env)
    target = tmp_path / "archive"
    assert run_cli(["archive", "--to", str(target)]).code == 0
    result = run_cli(["archive", "--to", str(target), "--rebuild"])
    assert result.code == 0, result.err
    assert "2 folders written" in result.out
    assert "0 unchanged" in result.out
