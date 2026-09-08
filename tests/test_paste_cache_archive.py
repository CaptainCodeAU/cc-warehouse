"""Oracle tests: gathering `~/.claude/paste-cache/` files a session referenced (39e).

    <root>/<label>/<stamp>_<uuid>/
        <uuid>.jsonl   ...   manifest.json
        pastes/             THIS SLICE - <contentHash>.txt, only what this session referenced

A COMPANION DIRECTORY, not a new manifest shape (unlike 39d's `prompts.jsonl`,
which is exactly one file per session): `pastes/` holds zero or more files, the
same shape `tool-results/`, `workflows/`, `file-history/` and `todos/` already
share, so it reuses COMPANION_MANIFEST_KEYS / copy_companion_dir /
companion_records / write_companion_file / _companion_problems /
folder_is_current wholesale rather than inventing a fifth mechanism (C12).

`paste_hashes_by_session` is a SEPARATE second pass over `history.jsonl`'s raw
bytes, not folded into `split_history_by_session` (39d, already shipped and
red-teamed) - see that function's own docstring in archive.py for why.

Only the EXTERNALISED shape (`{"id":..,"type":"text","contentHash": <hash>}`)
contributes a hash; the INLINED shape (`{"id":..,"type":"text","content": <text>}`)
needs no paste-cache lookup at all, since its text already lives in
`history.jsonl` and is already covered by the 39c snapshot and the 39d split.

Contract: DESIGN 6 (new top-level manifest keys, never `loss` amendments), R2,
R5, R9, R10; FINDINGS F1, F4, F6.
"""

import json
from pathlib import Path
from typing import cast

from cc_warehouse import archive, store
from cc_warehouse.render import RenderOptions
from conftest import DEFAULT_UUID, basic_session

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"


def parent_folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE
    ).directory


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def rebuild(root: Path) -> None:
    archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )


def history_row(session_id: str, pasted: dict[str, object]) -> bytes:
    row = {"display": "a prompt", "sessionId": session_id, "pastedContents": pasted}
    return json.dumps(row).encode() + b"\n"


# ---------------------------------------------------------------------------
# paste_hashes_by_session: shapes, grouping, malformed input
# ---------------------------------------------------------------------------


def test_externalized_entries_contribute_their_hash() -> None:
    row = history_row("aaaa", {"1": {"id": 1, "type": "text", "contentHash": "hash1"}})
    assert archive.paste_hashes_by_session(row) == {"aaaa": frozenset({"hash1"})}


def test_inlined_entries_contribute_no_hash() -> None:
    """The inlined shape's text is already in `history.jsonl`; it needs no
    paste-cache lookup at all."""
    row = history_row("aaaa", {"1": {"id": 1, "type": "text", "content": "the actual text"}})
    assert archive.paste_hashes_by_session(row) == {}


def test_a_mix_of_inlined_and_externalized_keeps_only_the_externalized_hash() -> None:
    row = history_row(
        "aaaa",
        {
            "1": {"id": 1, "type": "text", "content": "inline text"},
            "2": {"id": 2, "type": "text", "contentHash": "hash2"},
        },
    )
    assert archive.paste_hashes_by_session(row) == {"aaaa": frozenset({"hash2"})}


def test_a_shared_hash_lands_under_every_session_that_referenced_it() -> None:
    """The ticket's own requirement, stated explicitly: a shared clipboard blob
    pasted into two different sessions groups under BOTH."""
    row_a = history_row("aaaa", {"1": {"id": 1, "type": "text", "contentHash": "shared"}})
    row_b = history_row("bbbb", {"1": {"id": 1, "type": "text", "contentHash": "shared"}})
    grouped = archive.paste_hashes_by_session(row_a + row_b)
    assert grouped == {"aaaa": frozenset({"shared"}), "bbbb": frozenset({"shared"})}


def test_multiple_hashes_for_one_session_are_all_grouped() -> None:
    row = history_row(
        "aaaa",
        {
            "1": {"id": 1, "type": "text", "contentHash": "hash1"},
            "2": {"id": 2, "type": "text", "contentHash": "hash2"},
        },
    )
    assert archive.paste_hashes_by_session(row) == {"aaaa": frozenset({"hash1", "hash2"})}


def test_a_non_dict_pastedcontents_is_skipped() -> None:
    row = b'{"sessionId":"aaaa","pastedContents":"not a dict"}\n'
    assert archive.paste_hashes_by_session(row) == {}


def test_a_row_with_no_session_id_is_skipped() -> None:
    row = b'{"pastedContents":{"1":{"id":1,"type":"text","contentHash":"h"}}}\n'
    assert archive.paste_hashes_by_session(row) == {}


def test_a_row_with_a_non_string_session_id_is_skipped() -> None:
    row = b'{"sessionId":42,"pastedContents":{"1":{"id":1,"type":"text","contentHash":"h"}}}\n'
    assert archive.paste_hashes_by_session(row) == {}


def test_a_row_with_no_pastedcontents_at_all_is_skipped() -> None:
    row = b'{"sessionId":"aaaa","display":"no pastes here"}\n'
    assert archive.paste_hashes_by_session(row) == {}


def test_an_entry_missing_both_content_and_contenthash_contributes_nothing() -> None:
    row = history_row("aaaa", {"1": {"id": 1, "type": "text"}})
    assert archive.paste_hashes_by_session(row) == {}


def test_a_non_dict_entry_inside_pastedcontents_is_skipped() -> None:
    row = history_row("aaaa", {"1": "not a dict entry"})
    assert archive.paste_hashes_by_session(row) == {}


def test_a_malformed_json_line_is_skipped_not_raised() -> None:
    good = history_row("aaaa", {"1": {"id": 1, "type": "text", "contentHash": "h"}})
    source = good + b"not json at all\n"
    assert archive.paste_hashes_by_session(source) == {"aaaa": frozenset({"h"})}


def test_a_line_that_is_not_a_json_object_is_skipped() -> None:
    good = history_row("aaaa", {"1": {"id": 1, "type": "text", "contentHash": "h"}})
    source = good + b'["just", "an", "array"]\n'
    assert archive.paste_hashes_by_session(source) == {"aaaa": frozenset({"h"})}


def test_an_empty_line_is_skipped() -> None:
    good = history_row("aaaa", {"1": {"id": 1, "type": "text", "contentHash": "h"}})
    source = good + b"\n\n"
    assert archive.paste_hashes_by_session(source) == {"aaaa": frozenset({"h"})}


def test_empty_input_groups_nothing() -> None:
    assert archive.paste_hashes_by_session(b"") == {}


# ---------------------------------------------------------------------------
# The fence: pastes/ is a known companion directory
# ---------------------------------------------------------------------------


def test_pastes_is_a_known_companion_directory() -> None:
    assert archive.COMPANION_MANIFEST_KEYS[archive.PASTES_DIR] == "pastes"
    assert archive.PASTES_DIR == "pastes"


def test_pastes_is_not_a_generated_file() -> None:
    """`GENERATED_NAMES` drives what the rebuild module may delete. A copied
    paste is not regenerable from the payload and is not the rebuilder's to
    remove (R4)."""
    assert archive.PASTES_DIR not in set(archive.GENERATED_NAMES)


# ---------------------------------------------------------------------------
# write_companion_file into pastes/
# ---------------------------------------------------------------------------


def test_a_pasted_file_lands_under_the_pastes_directory(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    assert (folder / "pastes" / "abc123.txt").read_bytes() == b"pasted text"


def test_a_second_write_of_the_same_bytes_reports_unchanged(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    outcome = archive.write_companion_file(
        folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text"
    )
    assert outcome == "unchanged"


def test_a_changed_paste_under_the_same_name_is_refused(tmp_path: Path) -> None:
    """R5: pastes are source-class data with no larger-is-better ordering, so
    the archived copy wins and the refusal is named, never silently overwritten."""
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"original")
    outcome = archive.write_companion_file(
        folder, archive.PASTES_DIR, Path("abc123.txt"), b"different content entirely"
    )
    assert outcome == "refused"
    assert (folder / "pastes" / "abc123.txt").read_bytes() == b"original"


def test_writing_a_session_folder_alone_creates_no_pastes_directory(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    assert not (folder / "pastes").exists()


def test_a_path_that_escapes_the_session_folder_is_refused(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    try:
        archive.write_companion_file(folder, archive.PASTES_DIR, Path("../escaped.txt"), b"x")
    except ValueError:
        return
    raise AssertionError("an escaping relative path must be refused")


# ---------------------------------------------------------------------------
# Manifest and verify
# ---------------------------------------------------------------------------


def test_the_manifest_lists_each_paste_with_its_hash_and_size(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    rebuild(tmp_path)
    records = cast(list[dict[str, object]], manifest_of(folder)["pastes"])
    assert {r["name"] for r in records} == {"abc123.txt"}
    record = records[0]
    assert record["sha256"] == store.sha256_hex(b"pasted text")
    assert record["bytes"] == len(b"pasted text")


def test_a_session_with_no_pastes_still_gets_the_empty_list_key(tmp_path: Path) -> None:
    """F6: `[]` says "none", a missing key says "this manifest predates the
    feature"."""
    manifest = manifest_of(parent_folder(tmp_path))
    assert manifest["pastes"] == []


def test_a_folder_stops_being_current_once_a_paste_is_added(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    assert archive.folder_is_current(folder, digest, OPTS) is True
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    assert archive.folder_is_current(folder, digest, OPTS) is False
    rebuild(tmp_path)
    assert archive.folder_is_current(folder, digest, OPTS) is True


def test_verify_reports_a_paste_that_has_been_deleted(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    rebuild(tmp_path)
    (folder / "pastes" / "abc123.txt").unlink()
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert "paste abc123.txt is missing" in problems, problems


def test_verify_reports_a_paste_whose_bytes_changed(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    rebuild(tmp_path)
    (folder / "pastes" / "abc123.txt").write_bytes(b"tampered")
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert any("does not match its hash" in p for p in problems), problems


def test_no_paste_problem_string_starts_with_the_word_missing(tmp_path: Path) -> None:
    """`doctor._desync` reclassifies a folder whose problems ALL start with
    `missing ` as "still queued behind a render" (ticket 34). A deleted paste is
    never queued behind anything, so borrowing the word would hide a real loss
    forever."""
    folder = parent_folder(tmp_path)
    archive.write_companion_file(folder, archive.PASTES_DIR, Path("abc123.txt"), b"pasted text")
    rebuild(tmp_path)
    (folder / "pastes" / "abc123.txt").unlink()
    named = [p.problem for p in archive.verify_folder(folder, ZONE) if "paste" in p.problem]
    assert named
    assert not any(p.startswith("missing ") for p in named)


def test_a_manifest_written_before_this_slice_raises_no_new_problems(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    manifest = manifest_of(folder)
    del manifest["pastes"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert archive.verify_folder(folder, ZONE) == []
