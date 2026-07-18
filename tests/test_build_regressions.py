"""Contract-derived regression tests for build/render orchestration (slice 8,
post-review). NOT the frozen oracle suite (tests/test_build.py); these pin the
reviewer clusters the oracle did not cover. Cited in ticket 08.

- RT-PRUNE-LOSS (F7/F9): a build where the new head fails to render must KEEP the
  last-good projection, never delete-then-fail into zero dirs. [C-PRUNE-LOSS]
- RT-BUILD-LOCK (R14): a live locks/build holder makes build refuse, building
  nothing and leaving the lock untouched. [C-BUILD-LOCK]
- RT-ADHOC-GUARD (F9): ad-hoc render refuses an --out that resolves under the
  warehouse store/projections, so it can never clobber them. [C-ADHOC-GUARD]
- RT-RENAME-NOID (F7): project rename of an unknown id errors, not a silent success.
  [C-RENAME-NOID]
"""

import hashlib
import os
from pathlib import Path

from cc_warehouse import build, catalog, registry, store
from cc_warehouse.config import Config
from conftest import basic_session, run_ccw, warehouse_root


def _session_dirs(env: dict[str, str]) -> list[Path]:
    projections = warehouse_root(env) / "projections"
    if not projections.exists():
        return []
    return sorted(p for p in projections.glob("*/*") if p.is_dir())


def _meta(sha: str, uuid: str, first_ts: str) -> catalog.SessionMeta:
    return catalog.SessionMeta(
        sha256=sha,
        source_kind="claude_code",
        session_uuid=uuid,
        slug="fix-flux",
        git_branch=None,
        cwd="/home/alice/projects/widget",
        first_ts=first_ts,
        last_ts=first_ts,
        size_bytes=1,
        line_count=1,
        skipped_lines=0,
        summary="a real summary",
        hidden=False,
        resolution_source="payload_cwd",
    )


def _seed_real_session(root: Path) -> int:
    conn = catalog.open_catalog(root)
    proj = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now="2026-01-05T12:00:00Z"
    )
    data = basic_session()
    put = store.put(root, data)
    catalog.add_session(
        conn,
        _meta(put.sha256, "uuid-a", "2026-01-05T10:00:00.000Z"),
        proj.project_id,
        "2026-01-05T12:00:00Z",
    )
    conn.commit()
    conn.close()
    return proj.project_id


def test_build_keeps_last_good_projection_when_a_head_fails(ccw_env: dict[str, str]) -> None:
    """RT-PRUNE-LOSS: a later version whose stored object is missing must not cost the
    session its last-good projection (the prune must not run on a failed build)."""
    root = warehouse_root(ccw_env)
    project_id = _seed_real_session(root)
    build.build(Config(root=root))
    assert len(_session_dirs(ccw_env)) == 1

    conn = catalog.open_catalog(root)
    missing = hashlib.sha256(b"a version whose object was never stored").hexdigest()
    catalog.add_session(
        conn,
        _meta(missing, "uuid-a", "2026-01-05T11:00:00.000Z"),
        project_id,
        "2026-01-05T13:00:00Z",
    )
    conn.commit()
    conn.close()

    report = build.build(Config(root=root))
    assert report.failures  # the missing-object head is reported
    assert len(_session_dirs(ccw_env)) >= 1  # the last-good projection survives


def test_build_refuses_beside_a_live_lock_holder(ccw_env: dict[str, str]) -> None:
    """RT-BUILD-LOCK (R14/DESIGN-13): a live locks/build holder makes build a no-op that
    builds nothing, exits non-zero, and leaves the lock untouched."""
    root = warehouse_root(ccw_env)
    _seed_real_session(root)
    lock = root / "locks" / "build"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))
    result = run_ccw(["build"], ccw_env)
    assert result.code != 0
    assert _session_dirs(ccw_env) == []
    assert lock.read_text().strip() == str(os.getpid())


def test_adhoc_render_refuses_out_under_the_store(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """RT-ADHOC-GUARD (F9): an --out resolving under the warehouse objects/ is refused so
    ad-hoc render can never clobber the content-addressed store."""
    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    bad_out = warehouse_root(ccw_env) / "objects" / "sneaky"
    result = run_ccw(["render", str(source), "--out", str(bad_out)], ccw_env)
    assert result.code != 0
    assert "Error:" in result.err
    assert not bad_out.exists()


def test_adhoc_render_refuses_out_under_projections(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """RT-ADHOC-GUARD (F9): an --out under projections/ is refused too."""
    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    bad_out = warehouse_root(ccw_env) / "projections" / "sneaky"
    result = run_ccw(["render", str(source), "--out", str(bad_out)], ccw_env)
    assert result.code != 0
    assert not bad_out.exists()


def test_project_rename_unknown_id_errors(ccw_env: dict[str, str]) -> None:
    """RT-RENAME-NOID (F7): renaming a project that does not exist is an error, not a
    silent success."""
    result = run_ccw(["project", "rename", "9999", "whatever"], ccw_env)
    assert result.code != 0
    assert "Error:" in result.err
