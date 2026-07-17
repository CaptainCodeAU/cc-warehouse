"""Oracle tests: ccw migrate + retire (slice 10).

Contract: DESIGN section 10 (standard store routine, hash dedupe, per-file
manifest, NEVER writes to the source tree, retire = single sanctioned rename);
rules R10, R13; FINDINGS F1, F7, F9, F10.

Frozen here (Phase 2): the migration manifest is written to
<root>/logs/migrate-manifest.json (latest run, atomic write).
"""

import json
import re
import stat
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    run_ccw,
    session_count,
    tree_snapshot,
    warehouse_root,
)

UUID_A = "aaaaaaaa-0000-0000-0000-000000000001"
UUID_B = "aaaaaaaa-0000-0000-0000-000000000002"


def legacy_archive(tmp_path: Path) -> Path:
    """A miniature of the ~7k-session legacy archive: project dirs holding
    <uuid>/<uuid>.jsonl, including a byte-identical duplicate copy."""
    root = tmp_path / "old-archive"
    a = basic_session(cwd="/home/alice/projects/widget", session_id=UUID_A)
    b = basic_session(cwd="/home/alice/projects/gadget", session_id=UUID_B)
    for project, uuid, data in (
        ("widget", UUID_A, a),
        ("gadget", UUID_B, b),
        ("widget-copy", UUID_A, a),  # duplicate bytes under another project dir
    ):
        session_dir = root / project / uuid
        session_dir.mkdir(parents=True)
        (session_dir / f"{uuid}.jsonl").write_bytes(data)
    return root


def test_migrate_imports_everything_and_dedupes_by_hash(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F1: the duplicate copy collapses via hash equality, not size; every
    source file is accounted for in the manifest."""
    root = legacy_archive(tmp_path)
    result = run_ccw(["migrate", str(root)], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 2

    manifest_path = warehouse_root(ccw_env) / "logs" / "migrate-manifest.json"
    assert manifest_path.exists()
    entries = cast(list[dict[str, object]], json.loads(manifest_path.read_text()))
    assert len(entries) == 3
    outcomes = sorted(str(e["outcome"]) for e in entries)
    assert outcomes.count("stored") == 2
    assert any(o.startswith("duplicate") for o in outcomes)
    for e in entries:
        assert e["source"]
        assert e["hash"]


def test_migrate_never_touches_the_source_tree(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9 oracle: the source tree is byte-identical after migrate."""
    root = legacy_archive(tmp_path)
    before = tree_snapshot(root)
    run_ccw(["migrate", str(root)], ccw_env)
    assert tree_snapshot(root) == before


def test_migrate_is_idempotent(ccw_env: dict[str, str], tmp_path: Path) -> None:
    root = legacy_archive(tmp_path)
    assert run_ccw(["migrate", str(root)], ccw_env).code == 0
    assert run_ccw(["migrate", str(root)], ccw_env).code == 0
    assert session_count(ccw_env) == 2


def test_migrate_continues_past_unreadable_items(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F7/R10: an unreadable file is reported by name and left alone; the rest
    of the batch imports."""
    root = legacy_archive(tmp_path)
    broken = root / "widget" / UUID_A / f"{UUID_A}.jsonl"
    broken.chmod(0)
    try:
        result = run_ccw(["migrate", str(root)], ccw_env)
        assert result.code != 0
        # The identical duplicate under widget-copy still imports session A.
        assert session_count(ccw_env) == 2
        assert broken.name in result.out + result.err
    finally:
        broken.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_retire_is_a_single_visible_rename(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN section 10: `migrate --retire` renames the source root to
    _RETIRED_<YYYY-MM>_<name>; the one sanctioned old-world write."""
    root = legacy_archive(tmp_path)
    before = tree_snapshot(root)
    result = run_ccw(["migrate", "--retire", str(root), "--yes"], ccw_env)
    assert result.code == 0, result.err
    assert not root.exists()
    retired = [
        p
        for p in root.parent.iterdir()
        if re.fullmatch(r"_RETIRED_\d{4}-\d{2}_old-archive", p.name)
    ]
    assert len(retired) == 1
    assert tree_snapshot(retired[0]) == before


def test_retire_without_consent_on_non_tty_aborts(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F10/R13: non-TTY stdin without --yes exits non-zero having changed nothing."""
    root = legacy_archive(tmp_path)
    result = run_ccw(["migrate", "--retire", str(root)], ccw_env, stdin="")
    assert result.code != 0
    assert root.exists()
    assert not any(p.name.startswith("_RETIRED_") for p in root.parent.iterdir())
