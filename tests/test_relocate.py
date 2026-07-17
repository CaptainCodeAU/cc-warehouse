"""Oracle tests: ccw relocate (slice 12, the riskiest surface).

Contract: DESIGN section 11 (PLAN -> BACKUP -> APPLY -> VERIFY -> REPORT,
dry-run default, refuse non-empty targets, contents before containers,
boundary-guarded encoded-dir matching, JSON-aware memory edits); SPEC section
10.2 KEEP mechanics; rules R5, R13; FINDINGS F2, F7, F9, F10.
"""

import json
import re
import stat
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    claude_projects,
    hook_payload,
    run_ccw,
    tree_snapshot,
    warehouse_root,
)


def encode(path: Path) -> str:
    """Claude Code's cwd encoding: `/`, `_`, `.` become `-` (SPEC section 3)."""
    return re.sub(r"[/_.]", "-", str(path))


class World:
    """A miniature external world for relocate to repair."""

    def __init__(self, env: dict[str, str], tmp_path: Path) -> None:
        home = Path(env["HOME"])
        self.old_repo = home / "projects" / "widget"
        self.new_repo = home / "code" / "widget-next"
        self.old_repo.mkdir(parents=True)
        (self.old_repo / "main.py").write_text("print('widget')\n")

        self.encoded_dir = claude_projects(env) / encode(self.old_repo)
        self.encoded_dir.mkdir(parents=True)
        (self.encoded_dir / "session.jsonl").write_text("{}\n")
        # Boundary guard: `...-widgetbar` must never match `...-widget`.
        self.bystander = claude_projects(env) / (encode(self.old_repo) + "bar")
        self.bystander.mkdir()

        self.inventory = tmp_path / "pai-root"
        self.inventory.mkdir()
        self.memory_md = self.inventory / "memory.md"
        self.memory_md.write_text(f"The project lives at {self.old_repo} today.\n")
        self.memory_json = self.inventory / "state.json"
        self.memory_json.write_text(
            json.dumps({"path": str(self.old_repo), "nested": {"sub": f"{self.old_repo}/src"}})
        )

        root = warehouse_root(env)
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.toml").write_text(
            f'[relocate]\nroots = ["{self.inventory}"]\n'
        )
        # A captured session gives the registry an alias claim on the old path.
        transcript = self.encoded_dir / "capture.jsonl"
        transcript.write_bytes(basic_session(cwd=str(self.old_repo)))
        result = run_ccw(
            ["hook"], env, stdin=hook_payload(transcript, cwd=str(self.old_repo))
        )
        assert result.code == 0, result.err

    def snapshots(self, env: dict[str, str]) -> dict[str, dict[str, bytes]]:
        return {
            "claude": tree_snapshot(claude_projects(env)),
            "inventory": tree_snapshot(self.inventory),
            "repo": tree_snapshot(self.old_repo),
        }


def test_dry_run_is_the_default_and_changes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R13 posture: without --apply, relocate only plans and reports."""
    world = World(ccw_env, tmp_path)
    before = world.snapshots(ccw_env)
    result = run_ccw(
        ["relocate", str(world.old_repo), "--to", str(world.new_repo)], ccw_env
    )
    assert result.code == 0, result.err
    assert str(world.new_repo) in result.out
    assert world.snapshots(ccw_env) == before
    assert not world.new_repo.exists()


def test_apply_moves_repairs_and_backs_up(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The full pipeline: repo moved, memory contents rewritten (markdown AND
    JSON-aware) BEFORE encoded dirs are renamed, boundary bystander untouched,
    registry alias added, backups of every touched file."""
    world = World(ccw_env, tmp_path)
    result = run_ccw(
        [
            "relocate",
            str(world.old_repo),
            "--to",
            str(world.new_repo),
            "--apply",
            "--yes",
        ],
        ccw_env,
    )
    assert result.code == 0, result.err

    assert not world.old_repo.exists()
    assert (world.new_repo / "main.py").exists()

    md = world.memory_md.read_text()
    assert str(world.new_repo) in md
    assert str(world.old_repo) not in md
    data = cast(dict[str, object], json.loads(world.memory_json.read_text()))
    assert data["path"] == str(world.new_repo)
    assert cast(dict[str, object], data["nested"])["sub"] == f"{world.new_repo}/src"

    assert not world.encoded_dir.exists()
    renamed = claude_projects(ccw_env) / encode(world.new_repo)
    assert renamed.is_dir()
    assert world.bystander.is_dir()

    paths = {
        cast(tuple[str], r)[0]
        for r in cast(
            list[tuple[object, ...]],
            catalog_rows(ccw_env, "SELECT path FROM project_alias"),
        )
    }
    assert str(world.new_repo) in paths

    backups_root = warehouse_root(ccw_env) / "backups"
    backup_files = [p for p in backups_root.rglob("*") if p.is_file()]
    assert any(p.name == "memory.md" for p in backup_files)
    assert any(p.name == "state.json" for p in backup_files)
    originals = [p for p in backup_files if p.name == "memory.md"]
    assert str(world.old_repo) in originals[0].read_text()


def test_apply_refuses_a_non_empty_target(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    world = World(ccw_env, tmp_path)
    world.new_repo.mkdir(parents=True)
    (world.new_repo / "occupied.txt").write_text("here first")
    before = world.snapshots(ccw_env)
    result = run_ccw(
        [
            "relocate",
            str(world.old_repo),
            "--to",
            str(world.new_repo),
            "--apply",
            "--yes",
        ],
        ccw_env,
    )
    assert result.code == 1
    assert result.err.startswith("Error: ")
    assert world.snapshots(ccw_env) == before


def test_apply_without_yes_on_non_tty_aborts_untouched(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F10/R13: piping into an apply-class command without --yes changes nothing."""
    world = World(ccw_env, tmp_path)
    before = world.snapshots(ccw_env)
    result = run_ccw(
        ["relocate", str(world.old_repo), "--to", str(world.new_repo), "--apply"],
        ccw_env,
        stdin="",
    )
    assert result.code != 0
    assert world.snapshots(ccw_env) == before
    assert not world.new_repo.exists()


def test_content_rewrite_failure_halts_container_renames(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F7 + contents-before-containers: when a memory rewrite fails, relocate
    reports it and never falls through to renaming dirs or moving the repo
    with un-rewritten contents."""
    world = World(ccw_env, tmp_path)
    world.inventory.chmod(stat.S_IRUSR | stat.S_IXUSR)  # rewrite will fail
    try:
        result = run_ccw(
            [
                "relocate",
                str(world.old_repo),
                "--to",
                str(world.new_repo),
                "--apply",
                "--yes",
            ],
            ccw_env,
        )
        assert result.code != 0
        assert world.memory_md.name in result.out + result.err
        assert world.encoded_dir.is_dir()
        assert world.old_repo.is_dir()
        assert not world.new_repo.exists()
    finally:
        world.inventory.chmod(stat.S_IRWXU)
