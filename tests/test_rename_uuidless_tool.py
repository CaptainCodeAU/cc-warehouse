"""Tests for the one-off `tools/rename_uuidless_folders.py` (W-20261001-A56).

The tool moves uuid-less session folders from the name the pre-fix hook wrote
(`<stamp>_session/session.jsonl`) to the name every reader looks for
(`<stamp>_session-<short>/session-<short>.jsonl`). It lives in `tools/`, outside
the shipped package, and is driven here as a subprocess exactly as an operator
runs it, against a scratch archive built by the product's own capture path.

Every arm the brief names is exercised: dry run by default, `--record`
required with `--apply`, SKIP when the old JSONL is missing or its hash is not
the catalog's, REFUSE when the new folder exists, and never an overwrite.
"""

import json
import subprocess
import sys
from pathlib import Path

from cc_warehouse import archive, capture, catalog
from cc_warehouse.config import Config
from conftest import REPO_ROOT, jsonl, mark_archive, tree_snapshot

TOOL = REPO_ROOT / "tools" / "rename_uuidless_folders.py"
ZONE = "Australia/Melbourne"
CWD = "/home/alice/projects/widget"
TS = "2026-09-29T14:01:24.763Z"


def uuidless(marker: str, ts: str = TS) -> bytes:
    return jsonl(
        {"type": "system", "subtype": "init", "cwd": CWD, "timestamp": ts},
        {
            "type": "user",
            "timestamp": ts,
            "cwd": CWD,
            "message": {"role": "user", "content": f"prompt {marker}"},
        },
        {"type": "result", "subtype": "success", "timestamp": ts},
    )


def with_uuid(uuid: str) -> bytes:
    return jsonl(
        {
            "type": "user",
            "timestamp": TS,
            "cwd": CWD,
            "sessionId": uuid,
            "message": {"role": "user", "content": "a real session"},
        }
    )


def setup(tmp_path: Path) -> Config:
    root = tmp_path / "warehouse"
    root.mkdir()
    return Config(
        root=root,
        archive_root=mark_archive(tmp_path / "archive", ZONE),
        archive_timezone=ZONE,
        keep_objects=False,
        keep_projections=False,
    )


def captured(config: Config, tmp_path: Path, data: bytes, name: str) -> str:
    path = tmp_path / "claude" / "projects" / "-home-alice-projects-widget" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    result = capture.capture_transcript(config, path, session_id=None, cwd=None)
    assert result.action == "stored", result.detail
    return result.sha256


def to_legacy(config: Config, sha256: str) -> Path:
    """Move one captured uuid-less folder to where the pre-fix hook wrote it."""
    assert config.archive_root is not None
    short = short_of(config, sha256)
    (folder,) = config.archive_root.glob(f"*/*_session-{short}")
    legacy = folder.with_name(folder.name.split("_", 1)[0] + "_session")
    folder.rename(legacy)
    (legacy / f"session-{short}.jsonl").rename(legacy / "session.jsonl")
    return legacy


def short_of(config: Config, sha256: str) -> str:
    conn = catalog.open_catalog(config.root)
    try:
        row = conn.execute("SELECT short FROM session WHERE hash = ?", (sha256,)).fetchone()
    finally:
        conn.close()
    return str(row[0])


def run(config: Config, *extra: str) -> subprocess.CompletedProcess[str]:
    assert config.archive_root is not None
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--archive-root",
            str(config.archive_root),
            "--catalog",
            str(config.root / "catalog.sqlite"),
            "--zone",
            ZONE,
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def read_back(config: Config, sha256: str) -> bytes:
    conn = catalog.open_catalog(config.root)
    try:
        label, short, first_ts = conn.execute(
            "SELECT p.label, s.short, s.first_ts FROM session s"
            " JOIN project p ON p.id = s.project_id WHERE s.hash = ?",
            (sha256,),
        ).fetchone()
    finally:
        conn.close()
    return archive.read_payload(
        config, label=label, first_ts=first_ts, session_uuid=None, short=short, sha256=sha256
    )


def test_a_dry_run_is_the_default_and_changes_nothing(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    sha = captured(config, tmp_path, uuidless("one"), "armA.jsonl")
    legacy = to_legacy(config, sha)
    before = tree_snapshot(config.archive_root)
    result = run(config)
    assert result.returncode == 0, result.stderr
    assert f"RENAME widget/{legacy.name} -> widget/{legacy.name}-{short_of(config, sha)}" in (
        result.stdout
    )
    assert "1 to rename, 0 skipped, 0 refused (dry run" in result.stdout
    assert tree_snapshot(config.archive_root) == before


def test_apply_needs_a_record_path_and_changes_nothing_without_one(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    to_legacy(config, captured(config, tmp_path, uuidless("one"), "armA.jsonl"))
    before = tree_snapshot(config.archive_root)
    result = run(config, "--apply")
    assert result.returncode != 0
    assert "--record" in result.stderr
    assert tree_snapshot(config.archive_root) == before


def test_apply_renames_folder_and_jsonl_and_records_it(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    data = uuidless("one")
    sha = captured(config, tmp_path, data, "armA.jsonl")
    legacy = to_legacy(config, sha)
    (legacy / "notes.txt").write_text("rides along\n", encoding="utf-8")
    record = tmp_path / "rename-record.json"

    result = run(config, "--apply", "--record", str(record))
    assert result.returncode == 0, result.stderr
    short = short_of(config, sha)
    new = legacy.with_name(f"{legacy.name}-{short}")
    assert not legacy.exists()
    assert (new / f"session-{short}.jsonl").read_bytes() == data
    assert (new / "notes.txt").read_text(encoding="utf-8") == "rides along\n"
    assert read_back(config, sha) == data
    assert not (config.root / "objects").exists()

    (entry,) = json.loads(record.read_text(encoding="utf-8"))["renames"]
    assert entry["old"] == str(legacy / "session.jsonl")
    assert entry["new"] == str(new / f"session-{short}.jsonl")
    assert entry["sha256"] == sha
    assert entry["at"]


def test_skip_when_the_old_jsonl_is_not_the_cataloged_payload(tmp_path: Path) -> None:
    """A newer, larger copy captured later sits at the old path: its hash is
    not this row's, so this row is skipped and the file is left alone."""
    config = setup(tmp_path)
    assert config.archive_root is not None
    sha = captured(config, tmp_path, uuidless("one"), "armA.jsonl")
    legacy = to_legacy(config, sha)
    (legacy / "session.jsonl").write_bytes(uuidless("one, but grown since"))
    before = tree_snapshot(config.archive_root)
    result = run(config, "--apply", "--record", str(tmp_path / "r.json"))
    assert result.returncode == 0, result.stderr
    assert f"SKIP s:{short_of(config, sha)}: old JSONL hash is not the catalog's" in result.stdout
    assert tree_snapshot(config.archive_root) == before


def test_skip_when_the_old_folder_is_missing(tmp_path: Path) -> None:
    config = setup(tmp_path)
    sha = captured(config, tmp_path, uuidless("one"), "armA.jsonl")
    legacy = to_legacy(config, sha)
    (legacy / "session.jsonl").rename(tmp_path / "moved-out.jsonl")
    result = run(config)
    assert result.returncode == 0, result.stderr
    assert f"SKIP s:{short_of(config, sha)}: no old JSONL at" in result.stdout


def test_refuse_when_the_new_folder_already_exists(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    data = uuidless("one")
    sha = captured(config, tmp_path, data, "armA.jsonl")
    legacy = to_legacy(config, sha)
    short = short_of(config, sha)
    occupied = legacy.with_name(f"{legacy.name}-{short}")
    occupied.mkdir()
    before = tree_snapshot(config.archive_root)
    result = run(config, "--apply", "--record", str(tmp_path / "r.json"))
    assert result.returncode == 0, result.stderr
    assert f"REFUSE s:{short}: new folder already exists" in result.stdout
    assert "0 renamed, 0 skipped, 1 refused" in result.stdout
    assert tree_snapshot(config.archive_root) == before


def test_two_rows_that_shared_one_legacy_folder_rename_only_the_matching_one(
    tmp_path: Path,
) -> None:
    """The real harness-sealed case: two uuid-less payloads, one bare folder.
    Only the payload the folder actually holds moves; the other is skipped."""
    config = setup(tmp_path)
    assert config.archive_root is not None
    kept = uuidless("larger payload, the one that won the shared folder")
    lost = uuidless("smaller")
    sha_kept = captured(config, tmp_path, kept, "refusals.jsonl")
    sha_lost = captured(config, tmp_path, lost, "runs.jsonl")
    legacy = to_legacy(config, sha_kept)
    (lost_folder,) = config.archive_root.glob(f"*/*_session-{short_of(config, sha_lost)}")
    (lost_folder / f"session-{short_of(config, sha_lost)}.jsonl").unlink()
    lost_folder.rmdir()

    result = run(config, "--apply", "--record", str(tmp_path / "r.json"))
    assert result.returncode == 0, result.stderr
    assert "1 renamed, 1 skipped, 0 refused" in result.stdout
    assert read_back(config, sha_kept) == kept
    assert not legacy.exists()


def test_an_existing_record_file_is_never_overwritten(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    to_legacy(config, captured(config, tmp_path, uuidless("one"), "armA.jsonl"))
    record = tmp_path / "r.json"
    record.write_text("earlier\n", encoding="utf-8")
    before = tree_snapshot(config.archive_root)
    result = run(config, "--apply", "--record", str(record))
    assert result.returncode != 0
    assert record.read_text(encoding="utf-8") == "earlier\n"
    assert tree_snapshot(config.archive_root) == before


def test_sessions_with_a_uuid_are_never_touched(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    captured(config, tmp_path, with_uuid("e5111111-2222-3333-4444-555555555551"), "u.jsonl")
    before = tree_snapshot(config.archive_root)
    result = run(config, "--apply", "--record", str(tmp_path / "r.json"))
    assert result.returncode == 0, result.stderr
    assert "0 renamed, 0 skipped, 0 refused" in result.stdout
    assert tree_snapshot(config.archive_root) == before


def test_a_wrong_zone_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    config = setup(tmp_path)
    assert config.archive_root is not None
    to_legacy(config, captured(config, tmp_path, uuidless("one"), "armA.jsonl"))
    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--archive-root",
            str(config.archive_root),
            "--catalog",
            str(config.root / "catalog.sqlite"),
            "--zone",
            "UTC",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "zone mismatch" in result.stderr
