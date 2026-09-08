"""Oracle tests: the sweep snapshots `history.jsonl` once per run (39c).

ONE PASS, WHOLE-MACHINE, not per-transcript. Unlike `file-history/` and `todos/`
(39b), which are keyed by session id and gathered per session, `history.jsonl` is
a single file shared by every session on the machine, so there is nothing to key
a per-transcript pass on. The sweep reads it once and writes at most one new
content-addressed snapshot per run.

Contract: DESIGN R2, R5, R9, R10; FINDINGS F6, F9; ticket 39's constraint that
nothing under `~/.claude` is ever written.
"""

from pathlib import Path

from cc_warehouse import store
from conftest import basic_session, run_ccw, tree_snapshot, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
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
