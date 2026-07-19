"""Contract-derived regression tests for slice 10 (migrate + retire).

Written by the operator from DESIGN section 10, rules R4/R5/R10/R14, and FINDINGS
F7/F9 AFTER the slice-10 reviewer triage - not ported from any suite. Each pins one
CONFIRMED reviewer cluster so it stays fixed:

  C1 (F7/R10): a non-regular *.jsonl is reported by name, never silently dropped.
  C2 (R4/F9):  migrate --retire refuses an existing target, never clobbers or crashes.
  A1 (R14, DESIGN 13): a live locks/migrate holder makes migrate refuse and import nothing.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from conftest import (
    basic_session,
    run_ccw,
    session_count,
    tree_snapshot,
    warehouse_root,
)

UUID = "aaaaaaaa-0000-0000-0000-0000000000aa"


def _archive(tmp_path: Path) -> Path:
    """A one-session miniature of the legacy archive: <root>/widget/<uuid>/<uuid>.jsonl."""
    root = tmp_path / "old-archive"
    session_dir = root / "widget" / UUID
    session_dir.mkdir(parents=True)
    (session_dir / f"{UUID}.jsonl").write_bytes(basic_session(session_id=UUID))
    return root


def test_migrate_reports_non_regular_jsonl_and_still_imports_siblings(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """C1/F7/R10: a dangling-symlink *.jsonl is named as an error and accounted for in
    the manifest (never silently dropped), the exit is non-zero, and the real sibling
    transcript still imports - DESIGN 10 'every source jsonl accounted for'."""
    root = _archive(tmp_path)
    session_dir = root / "widget" / UUID
    (session_dir / "dangling.jsonl").symlink_to(tmp_path / "nonexistent-target")

    result = run_ccw(["migrate", str(root)], ccw_env)

    assert result.code != 0, result.out
    assert "dangling.jsonl" in result.out + result.err
    assert session_count(ccw_env) == 1  # the real sibling still imported
    manifest = json.loads(
        (warehouse_root(ccw_env) / "logs" / "migrate-manifest.json").read_text()
    )
    outcome_by_name = {Path(str(e["source"])).name: str(e["outcome"]) for e in manifest}
    assert outcome_by_name["dangling.jsonl"] == "error"
    assert outcome_by_name[f"{UUID}.jsonl"] == "stored"


def test_migrate_retire_refuses_existing_target_and_never_clobbers(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """C2/R4/F9: with the _RETIRED_<ym>_<name> target already present, migrate --retire
    refuses (non-zero exit) rather than rename onto it - os.rename would silently REMOVE
    an existing empty dir (a delete outside R4's closed list). The target and the source
    are both left intact."""
    root = _archive(tmp_path)
    before = tree_snapshot(root)
    ym = datetime.now(UTC).strftime("%Y-%m")
    target = root.parent / f"_RETIRED_{ym}_{root.name}"
    target.mkdir()  # empty: the case os.rename would silently clobber

    result = run_ccw(["migrate", "--retire", str(root), "--yes"], ccw_env)

    assert result.code != 0, result.out
    assert target.is_dir()  # not clobbered
    assert root.is_dir() and tree_snapshot(root) == before  # source untouched


def test_migrate_refuses_when_migrate_lock_is_held(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A1/R14/DESIGN 13: a live locks/migrate holder makes migrate a no-op that refuses
    with a non-zero exit, imports nothing, and writes no manifest (two concurrent runs
    cannot race the shared manifest)."""
    root = _archive(tmp_path)
    locks = warehouse_root(ccw_env) / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "migrate").write_text(str(os.getpid()))  # this live test process holds it

    result = run_ccw(["migrate", str(root)], ccw_env)

    assert result.code != 0, result.out
    assert session_count(ccw_env) == 0
    assert not (warehouse_root(ccw_env) / "logs" / "migrate-manifest.json").exists()
