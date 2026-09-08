"""Oracle tests: the per-session slice of `history.jsonl` (39d).

    <root>/<label>/<stamp>_<uuid>/
        <uuid>.jsonl   ...   manifest.json
        prompts.jsonl       THIS SLICE - this session's own history.jsonl rows

RAW LINES, NEVER RE-SERIALIZED. `split_history_by_session` parses each line only
to read `sessionId` for routing; the bytes it groups are the ORIGINAL LINES,
verbatim. A round trip through `json.dumps` would drift on unicode escaping, key
order and float formatting, so every test below that cares about byte fidelity
checks the returned bytes are literally a substring of the source, not merely
"parses to the same value".

A SINGLE FILE, NOT A COMPANION DIRECTORY, and that is why `prompts` gets its own
small manifest shape (`{present, sha256, bytes, lines}`) rather than reusing
`COMPANION_MANIFEST_KEYS`'s list-of-records shape - there is exactly one of
these per session, never a list.

Contract: DESIGN 6 (new top-level manifest keys, never `loss` amendments), R2,
R9, R10; FINDINGS F1, F4, F6.
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

ROW_A = b'{"display":"fix the flux capacitor","sessionId":"aaaa"}\n'
ROW_A2 = b'{"display":"a second prompt","sessionId":"aaaa"}\n'
ROW_B = b'{"display":"an unrelated prompt","sessionId":"bbbb"}\n'
ROW_UNICODE = '{"display":"emoji \U0001f680 and café","sessionId":"aaaa"}\n'.encode()
ROW_FLOAT = b'{"display":"a number","value":1.100000,"sessionId":"aaaa"}\n'


def parent_folder(root: Path) -> Path:
    return archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE
    ).directory


def manifest_of(folder: Path) -> dict[str, object]:
    return json.loads((folder / "manifest.json").read_text("utf-8"))


def rebuild(root: Path) -> None:
    archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE, rebuild=True
    )


# ---------------------------------------------------------------------------
# split_history_by_session: grouping, byte fidelity, malformed input
# ---------------------------------------------------------------------------


def test_rows_are_grouped_by_session_id() -> None:
    grouped = archive.split_history_by_session(ROW_A + ROW_B + ROW_A2)
    assert set(grouped) == {"aaaa", "bbbb"}
    assert grouped["aaaa"] == ROW_A + ROW_A2
    assert grouped["bbbb"] == ROW_B


def test_a_returned_line_is_byte_for_byte_a_substring_of_the_source() -> None:
    """Proves this is slicing, not a json.dumps round trip - try wording that
    would drift under re-encoding (unicode, a trailing-zero float)."""
    source = ROW_UNICODE + ROW_FLOAT
    grouped = archive.split_history_by_session(source)
    for line in (ROW_UNICODE, ROW_FLOAT):
        assert line in source
        assert grouped["aaaa"].count(line) == 1
    assert grouped["aaaa"] == ROW_UNICODE + ROW_FLOAT


def test_a_malformed_json_line_is_skipped_not_raised() -> None:
    source = ROW_A + b"not json at all\n" + ROW_B
    grouped = archive.split_history_by_session(source)
    assert set(grouped) == {"aaaa", "bbbb"}


def test_a_line_that_is_not_a_json_object_is_skipped() -> None:
    source = ROW_A + b'["just", "an", "array"]\n' + ROW_B
    grouped = archive.split_history_by_session(source)
    assert set(grouped) == {"aaaa", "bbbb"}


def test_a_row_with_no_session_id_is_skipped() -> None:
    source = ROW_A + b'{"display":"orphan row, no sessionId"}\n'
    grouped = archive.split_history_by_session(source)
    assert set(grouped) == {"aaaa"}


def test_a_row_with_a_non_string_session_id_is_skipped() -> None:
    source = ROW_A + b'{"display":"bad type","sessionId":42}\n'
    grouped = archive.split_history_by_session(source)
    assert set(grouped) == {"aaaa"}


def test_an_empty_line_is_skipped() -> None:
    source = ROW_A + b"\n\n" + ROW_B
    grouped = archive.split_history_by_session(source)
    assert set(grouped) == {"aaaa", "bbbb"}


def test_empty_input_groups_nothing() -> None:
    assert archive.split_history_by_session(b"") == {}


def test_a_line_missing_its_trailing_newline_still_gets_one() -> None:
    """The last line of a real history.jsonl can lack a trailing newline if
    Claude Code was killed mid-write; the grouped output must still be valid
    JSONL (one row per line) rather than concatenating two rows together."""
    source = ROW_A.rstrip(b"\n")
    grouped = archive.split_history_by_session(source)
    assert grouped["aaaa"] == ROW_A


# ---------------------------------------------------------------------------
# write_prompts / prompts_record
# ---------------------------------------------------------------------------


def test_write_prompts_lands_at_the_fixed_name(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A)
    assert (folder / "prompts.jsonl").read_bytes() == ROW_A


def test_a_second_identical_write_reports_no_change(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    assert archive.write_prompts(folder, ROW_A) is True
    assert archive.write_prompts(folder, ROW_A) is False
    assert (folder / "prompts.jsonl").read_bytes() == ROW_A


def test_a_changed_write_is_allowed_to_rewrite(tmp_path: Path) -> None:
    """Unlike the content-addressed snapshot, prompts.jsonl has a FIXED name and
    must accept a legitimate fix to the extraction logic."""
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A)
    assert archive.write_prompts(folder, ROW_A + ROW_A2) is True
    assert (folder / "prompts.jsonl").read_bytes() == ROW_A + ROW_A2


def test_prompts_record_of_a_session_with_no_file(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    assert archive.prompts_record(folder) == {"present": False}


def test_prompts_record_of_a_session_with_a_file(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A + ROW_A2)
    record = archive.prompts_record(folder)
    assert record["present"] is True
    assert record["sha256"] == store.sha256_hex(ROW_A + ROW_A2)
    assert record["bytes"] == len(ROW_A + ROW_A2)
    assert record["lines"] == 2


# ---------------------------------------------------------------------------
# Manifest wiring: present in every manifest, absent-vs-empty (F6)
# ---------------------------------------------------------------------------


def test_a_session_with_no_prompts_still_gets_the_key(tmp_path: Path) -> None:
    """F6: `{"present": False}` says "checked, none" - a missing key says "this
    manifest predates the feature". Every existing folder is in the second state
    until the next rebuild reaches it."""
    manifest = manifest_of(parent_folder(tmp_path))
    assert manifest["prompts"] == {"present": False}


def test_the_manifest_records_the_written_prompts_file(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A)
    rebuild(tmp_path)
    record = cast(dict[str, object], manifest_of(folder)["prompts"])
    assert record == archive.prompts_record(folder)
    assert record["present"] is True


def test_a_manifest_written_before_this_slice_raises_no_new_problems(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    manifest = manifest_of(folder)
    del manifest["prompts"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert archive.verify_folder(folder, ZONE) == []


# ---------------------------------------------------------------------------
# folder_is_current: a prompts.jsonl written after the last render forces one
# ---------------------------------------------------------------------------


def test_a_folder_stops_being_current_once_prompts_are_added(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    assert archive.folder_is_current(folder, digest, OPTS) is True
    archive.write_prompts(folder, ROW_A)
    assert archive.folder_is_current(folder, digest, OPTS) is False
    rebuild(tmp_path)
    assert archive.folder_is_current(folder, digest, OPTS) is True


def test_a_folder_stops_being_current_once_prompts_are_deleted(tmp_path: Path) -> None:
    """The manifest can go stale in either direction: a file appearing, or one
    disappearing out from under a `present: True` record."""
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    archive.write_prompts(folder, ROW_A)
    rebuild(tmp_path)
    assert archive.folder_is_current(folder, digest, OPTS) is True
    (folder / "prompts.jsonl").unlink()
    assert archive.folder_is_current(folder, digest, OPTS) is False


# ---------------------------------------------------------------------------
# verify_folder / _prompts_problems
# ---------------------------------------------------------------------------


def test_verify_reports_a_deleted_prompts_file(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A)
    rebuild(tmp_path)
    (folder / "prompts.jsonl").unlink()
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert "prompts.jsonl is missing" in problems, problems


def test_no_prompts_problem_string_starts_with_the_word_missing(tmp_path: Path) -> None:
    """`doctor._desync` reclassifies a folder whose problems ALL start with
    `missing ` as "still queued behind a render" (ticket 34). A deleted
    prompts.jsonl is never queued behind anything, so borrowing the word would
    hide a real loss forever."""
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A)
    rebuild(tmp_path)
    (folder / "prompts.jsonl").unlink()
    problems = [p.problem for p in archive.verify_folder(folder, ZONE) if "prompts" in p.problem]
    assert problems
    assert not any(p.startswith("missing ") for p in problems)


def test_verify_reports_a_prompts_file_whose_bytes_changed(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_prompts(folder, ROW_A)
    rebuild(tmp_path)
    (folder / "prompts.jsonl").write_bytes(b"tampered")
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert any("does not match its hash" in p for p in problems), problems
