"""Oracle tests: the sweep snapshots AND splits `history.jsonl` once per run
(39c/39d).

ONE READ, WHOLE-MACHINE, not per-transcript. Unlike `file-history/` and
`todos/` (39b), which are keyed by session id and gathered per session,
`history.jsonl` is a single file shared by every session on the machine, so
there is nothing to key a per-transcript pass on. The sweep reads it exactly
once: it writes at most one new content-addressed whole-file snapshot (39c),
then groups the same bytes by `sessionId` and writes each archived session's
own slice into `prompts.jsonl` (39d). A `sessionId` with no matching archived
folder is silently skipped - the whole-file snapshot is the backstop for that
case, so nothing is lost, only left unsplit.

Contract: DESIGN R2, R5, R9, R10; FINDINGS F1, F4, F6, F9; ticket 39's
constraint that nothing under `~/.claude` is ever written.
"""

import json
from pathlib import Path
from typing import cast

from cc_warehouse import store
from conftest import basic_session, run_ccw, tree_snapshot, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
HISTORY_BYTES = b'{"display":"fix the flux capacitor","sessionId":"aaaa"}\n'


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def claude_home(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude"


def plant_history(env: dict[str, str], data: bytes = HISTORY_BYTES) -> Path:
    path = claude_home(env) / "history.jsonl"
    path.write_bytes(data)
    return path


def snapshots_dir(archive_root: Path) -> Path:
    return archive_root / "_not-sessions" / "history-jsonl-snapshots"


def sweep(env: dict[str, str]) -> None:
    result = run_ccw(["sweep", "--quiet"], env)
    assert result.code == 0, result.err + result.out


def test_a_sweep_snapshots_the_live_history_file(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    sweep(ccw_env)
    found = list(snapshots_dir(archive_root).glob("*.jsonl"))
    assert len(found) == 1
    assert found[0].read_bytes() == HISTORY_BYTES


def test_a_second_sweep_writes_no_new_snapshot(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    sweep(ccw_env)
    before = tree_snapshot(snapshots_dir(archive_root))
    sweep(ccw_env)
    assert tree_snapshot(snapshots_dir(archive_root)) == before


def test_a_changed_history_file_gets_a_second_snapshot(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    sweep(ccw_env)
    plant_history(ccw_env, HISTORY_BYTES + b'{"display":"a second prompt"}\n')
    sweep(ccw_env)
    found = {p.read_bytes() for p in snapshots_dir(archive_root).glob("*.jsonl")}
    assert found == {HISTORY_BYTES, HISTORY_BYTES + b'{"display":"a second prompt"}\n'}


def test_a_machine_with_no_history_file_sweeps_clean(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    sweep(ccw_env)
    assert not snapshots_dir(archive_root).exists()


def test_a_dry_run_reports_the_would_be_snapshot_and_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    result = run_ccw(["sweep", "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert "would-archive-history-snapshot" in result.out, result.out
    assert not archive_root.exists()


def test_a_dry_run_reports_nothing_once_a_snapshot_already_exists(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    sweep(ccw_env)
    result = run_ccw(["sweep", "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert "would-archive-history-snapshot" not in result.out, result.out


def test_the_source_history_file_is_untouched_by_a_sweep(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    before = tree_snapshot(claude_home(ccw_env))
    sweep(ccw_env)
    assert tree_snapshot(claude_home(ccw_env)) == before


def test_a_normal_session_sweep_still_works_alongside_a_history_file(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The new pass must not disturb the existing session-capture passes."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_history(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    sweep(ccw_env)
    found = sorted(archive_root.glob(f"*/*_{UUID_A}"))
    assert len(found) == 1
    assert (snapshots_dir(archive_root) / f"{store.sha256_hex(HISTORY_BYTES)[:12]}.jsonl").is_file()


# ---------------------------------------------------------------------------
# 39d: the per-session split into prompts.jsonl, from the same read
# ---------------------------------------------------------------------------


def session_folder(archive_root: Path, uuid: str) -> Path:
    found = sorted(archive_root.glob(f"*/*_{uuid}"))
    assert len(found) == 1, found
    return found[0]


def test_a_sweep_splits_prompts_for_two_sessions_and_still_snapshots(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(
        ccw_env,
        basic_session(session_id=UUID_B),
        session_id=UUID_B,
        encoded_dir="-home-alice-projects-b",
    )
    row_a = f'{{"display":"prompt for A","sessionId":"{UUID_A}"}}\n'.encode()
    row_b = f'{{"display":"prompt for B","sessionId":"{UUID_B}"}}\n'.encode()
    data = row_a + row_b
    plant_history(ccw_env, data)
    sweep(ccw_env)

    assert (session_folder(archive_root, UUID_A) / "prompts.jsonl").read_bytes() == row_a
    assert (session_folder(archive_root, UUID_B) / "prompts.jsonl").read_bytes() == row_b
    assert (snapshots_dir(archive_root) / f"{store.sha256_hex(data)[:12]}.jsonl").is_file()


def test_a_session_id_with_no_archived_folder_is_silently_skipped(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The whole-file snapshot is the backstop for exactly this case, so
    nothing about it is an error, and nothing invents a folder for it (F4)."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    orphan_uuid = "99999999-0000-4000-8000-000000000000"
    orphan_row = f'{{"display":"no session archived","sessionId":"{orphan_uuid}"}}\n'.encode()
    plant_history(ccw_env, orphan_row)
    result = run_ccw(["sweep", "--quiet"], ccw_env)
    assert result.code == 0, result.err + result.out
    assert not any(archive_root.glob("**/prompts.jsonl"))
    assert (snapshots_dir(archive_root) / f"{store.sha256_hex(orphan_row)[:12]}.jsonl").is_file()


def test_a_second_sweep_writes_no_new_prompts(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    row_a = f'{{"display":"prompt for A","sessionId":"{UUID_A}"}}\n'.encode()
    plant_history(ccw_env, row_a)
    sweep(ccw_env)
    folder = session_folder(archive_root, UUID_A)
    before = (folder / "prompts.jsonl").stat().st_mtime_ns
    sweep(ccw_env)
    assert (folder / "prompts.jsonl").stat().st_mtime_ns == before
    assert (folder / "prompts.jsonl").read_bytes() == row_a


def test_a_dry_run_reports_would_archive_prompts_and_writes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    sweep(ccw_env)  # archive the session first, with no history.jsonl yet
    row_a = f'{{"display":"prompt for A","sessionId":"{UUID_A}"}}\n'.encode()
    plant_history(ccw_env, row_a)
    folder = session_folder(archive_root, UUID_A)
    result = run_ccw(["sweep", "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert "would-archive-prompts" in result.out, result.out
    assert not (folder / "prompts.jsonl").exists()


def test_a_sweep_added_prompts_file_is_reflected_in_the_manifest_the_same_run(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The listing is the only thing that makes a later deletion detectable, so
    a split that never reaches a manifest is half a feature - mirrors
    test_the_manifest_lists_the_snapshots_after_a_sweep in
    test_external_capture.py, proving the SAME cli.py post-sweep rebuild
    trigger (SIDECAR_ARCHIVED_ACTIONS) picks up `archived-prompts` too."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    sweep(ccw_env)  # archive AND render the session first, before any history exists
    folder = session_folder(archive_root, UUID_A)
    manifest_before = cast(
        dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8"))
    )
    assert manifest_before["prompts"] == {"present": False}

    row_a = f'{{"display":"prompt for A","sessionId":"{UUID_A}"}}\n'.encode()
    plant_history(ccw_env, row_a)
    sweep(ccw_env)

    manifest_after = cast(
        dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8"))
    )
    record = cast(dict[str, object], manifest_after["prompts"])
    assert record["present"] is True
    assert record["sha256"] == store.sha256_hex(row_a)


def test_the_split_preserves_exact_bytes_including_unicode(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    row = f'{{"display":"emoji \U0001f680 and café","sessionId":"{UUID_A}"}}\n'.encode()
    plant_history(ccw_env, row)
    sweep(ccw_env)
    assert (session_folder(archive_root, UUID_A) / "prompts.jsonl").read_bytes() == row
