"""Oracle tests: `custom-title.json`, a single-file sidecar (found 2026-09-10).

    <root>/<label>/<stamp>_<uuid>/
        <uuid>.jsonl   ...   manifest.json
        custom-title.json   THIS SLICE - the session's renamed title

Claude Code writes this directly inside a session's `<uuid>/` sidecar dir -
the same level as `subagents/`, `tool-results/` and `workflows/` - whenever a
session is renamed. `sidecars.py` did not know the name, so `sidecars.scan()`
classified it as an unknown (level A) sibling, firing a real desktop
notification and never archiving the file.

A SINGLE FILE, NOT A DIRECTORY TO MIRROR, so it follows the `prompts.jsonl`
shape (`write_if_changed`, its own small `{present, sha256, bytes}` manifest
key) rather than `copy_companion_dir`/`COMPANION_MANIFEST_KEYS`, which assume
a source directory to `rglob`. `write_if_changed` rather than `write_if_absent`
because a rename is a legitimate later update to a fixed-name file, not a
second source to refuse under R5 - the archive should hold the LATEST title.

Contract: DESIGN 6 (new top-level manifest keys, never `loss` amendments), R2,
R5 (deliberately not applied here - see above), R9, R10; FINDINGS F1, F4, F6.
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

TITLE_A = b'{"customTitle":"np1"}\n'
TITLE_B = b'{"customTitle":"renamed again"}\n'


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


# ---------------------------------------------------------------------------
# The fence: custom-title.json must have a copier, same as every other name
# ---------------------------------------------------------------------------


def test_custom_title_file_is_a_known_sidecar_name() -> None:
    from cc_warehouse import sidecars

    assert sidecars.CUSTOM_TITLE_FILE in sidecars.SESSION_SIDECARS


def test_custom_title_has_a_registered_copier() -> None:
    from cc_warehouse import sidecars

    assert archive.COPIERS[sidecars.CUSTOM_TITLE_FILE] == "write_custom_title"


# ---------------------------------------------------------------------------
# write_custom_title / custom_title_record
# ---------------------------------------------------------------------------


def test_write_custom_title_lands_at_the_fixed_name(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    assert (folder / "custom-title.json").read_bytes() == TITLE_A


def test_a_second_identical_write_reports_no_change(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    assert archive.write_custom_title(folder, TITLE_A) is True
    assert archive.write_custom_title(folder, TITLE_A) is False
    assert (folder / "custom-title.json").read_bytes() == TITLE_A


def test_a_rename_is_allowed_to_overwrite_the_earlier_title(tmp_path: Path) -> None:
    """Unlike most sidecar copiers (R5, refuse-on-conflict), a rename is a
    legitimate later update to a fixed-name file, not a second source."""
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    assert archive.write_custom_title(folder, TITLE_B) is True
    assert (folder / "custom-title.json").read_bytes() == TITLE_B


def test_custom_title_record_of_a_session_never_renamed(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    assert archive.custom_title_record(folder) == {"present": False}


def test_custom_title_record_of_a_renamed_session(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    record = archive.custom_title_record(folder)
    assert record["present"] is True
    assert record["sha256"] == store.sha256_hex(TITLE_A)
    assert record["bytes"] == len(TITLE_A)


# ---------------------------------------------------------------------------
# Manifest wiring: present in every manifest, absent-vs-empty (F6)
# ---------------------------------------------------------------------------


def test_a_never_renamed_session_still_gets_the_key(tmp_path: Path) -> None:
    manifest = manifest_of(parent_folder(tmp_path))
    assert manifest["custom_title"] == {"present": False}


def test_the_manifest_records_the_written_title(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    rebuild(tmp_path)
    record = cast(dict[str, object], manifest_of(folder)["custom_title"])
    assert record == archive.custom_title_record(folder)
    assert record["present"] is True


def test_a_manifest_written_before_this_feature_raises_no_new_problems(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    manifest = manifest_of(folder)
    del manifest["custom_title"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert archive.verify_folder(folder, ZONE) == []


# ---------------------------------------------------------------------------
# folder_is_current: a title written or changed after the last render forces one
# ---------------------------------------------------------------------------


def test_a_folder_stops_being_current_once_a_title_is_added(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    assert archive.folder_is_current(folder, digest, OPTS) is True
    archive.write_custom_title(folder, TITLE_A)
    assert archive.folder_is_current(folder, digest, OPTS) is False
    rebuild(tmp_path)
    assert archive.folder_is_current(folder, digest, OPTS) is True


def test_a_folder_stops_being_current_once_the_title_is_deleted(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    digest = store.sha256_hex(basic_session(session_id=DEFAULT_UUID))
    archive.write_custom_title(folder, TITLE_A)
    rebuild(tmp_path)
    assert archive.folder_is_current(folder, digest, OPTS) is True
    (folder / "custom-title.json").unlink()
    assert archive.folder_is_current(folder, digest, OPTS) is False


# ---------------------------------------------------------------------------
# verify_folder / _custom_title_problems
# ---------------------------------------------------------------------------


def test_verify_reports_a_deleted_title_file(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    rebuild(tmp_path)
    (folder / "custom-title.json").unlink()
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert "custom-title.json is missing" in problems, problems


def test_no_custom_title_problem_string_starts_with_the_word_missing(tmp_path: Path) -> None:
    """`doctor._desync` reclassifies a folder whose problems ALL start with
    `missing ` as "still queued behind a render" (ticket 34). A deleted
    custom-title.json is never queued behind anything."""
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    rebuild(tmp_path)
    (folder / "custom-title.json").unlink()
    problems = [
        p.problem for p in archive.verify_folder(folder, ZONE) if "custom-title" in p.problem
    ]
    assert problems
    assert not any(p.startswith("missing ") for p in problems)


def test_verify_reports_a_title_file_whose_bytes_changed(tmp_path: Path) -> None:
    folder = parent_folder(tmp_path)
    archive.write_custom_title(folder, TITLE_A)
    rebuild(tmp_path)
    (folder / "custom-title.json").write_bytes(b"tampered")
    problems = [p.problem for p in archive.verify_folder(folder, ZONE)]
    assert any("does not match its hash" in p for p in problems), problems
