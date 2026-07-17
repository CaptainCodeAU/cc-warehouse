"""Oracle tests: project registry (slice 2).

Contract: DESIGN section 2 (project identity), rule R3; FINDINGS F4 (paths are
claims, not identity); SPEC section 3 (label derivation as a default only).
"""

import sqlite3
from pathlib import Path
from typing import cast

from cc_warehouse import catalog, registry

NOW = "2026-01-05T12:00:00Z"
LATER = "2026-02-01T12:00:00Z"


def fresh(tmp_path: Path) -> sqlite3.Connection:
    return catalog.open_catalog(tmp_path / "warehouse")


def rows(conn: sqlite3.Connection, sql: str) -> list[tuple[object, ...]]:
    return cast(list[tuple[object, ...]], conn.execute(sql).fetchall())


def test_derive_label_strips_prefix_username_and_known_dirs() -> None:
    """SPEC section 3: the derivation is only a default label suggestion."""
    assert registry.derive_label("/home/alice/projects/widget") == "widget"
    assert registry.derive_label("/Users/alice/code/widget") == "widget"


def test_resolve_creates_project_with_aliases(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    resolved = registry.resolve_project(
        conn,
        cwd="/home/alice/projects/widget",
        encoded_dir="-home-alice-projects-widget",
        now=NOW,
    )
    assert resolved.created is True
    project_rows = rows(conn, "SELECT id, label, retired FROM project")
    assert project_rows == [(resolved.project_id, "widget", 0)]
    alias_rows = rows(conn, "SELECT project_id, path, kind FROM project_alias ORDER BY kind")
    assert (resolved.project_id, "/home/alice/projects/widget", "cwd") in alias_rows
    assert (resolved.project_id, "-home-alice-projects-widget", "encoded_dir") in alias_rows


def test_resolve_is_stable_for_a_known_path(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    first = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now=NOW
    )
    second = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now=LATER
    )
    assert second.project_id == first.project_id
    assert second.created is False
    assert len(rows(conn, "SELECT id FROM project")) == 1


def test_colliding_derived_names_make_two_projects(tmp_path: Path) -> None:
    """F4: two different cwds whose encoded/display forms collide are still two
    distinct registry entries; collisions never merge identities."""
    conn = fresh(tmp_path)
    a = registry.resolve_project(
        conn,
        cwd="/home/alice/projects/app.x",
        encoded_dir="-home-alice-projects-app-x",
        now=NOW,
    )
    b = registry.resolve_project(
        conn,
        cwd="/home/alice/projects/app-x",
        encoded_dir="-home-alice-projects-app-x",
        now=NOW,
    )
    assert a.project_id != b.project_id
    assert len(rows(conn, "SELECT id FROM project")) == 2


def test_rename_project_is_label_edit_only(tmp_path: Path) -> None:
    conn = fresh(tmp_path)
    resolved = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now=NOW
    )
    aliases_before = rows(conn, "SELECT project_id, path, kind FROM project_alias")
    registry.rename_project(conn, resolved.project_id, "Widget Deluxe")
    assert rows(conn, "SELECT label FROM project") == [("Widget Deluxe",)]
    assert rows(conn, "SELECT project_id, path, kind FROM project_alias") == aliases_before


def test_move_relinks_history_with_zero_file_rewrites(tmp_path: Path) -> None:
    """F4 oracle: a registry move is metadata only; the project id survives and
    both paths resolve to it (paths are time-stamped claims)."""
    conn = fresh(tmp_path)
    resolved = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now=NOW
    )
    registry.move_project(
        conn,
        resolved.project_id,
        "/home/alice/projects/widget",
        "/home/alice/code/widget-next",
        LATER,
    )
    again = registry.resolve_project(
        conn, cwd="/home/alice/code/widget-next", encoded_dir=None, now=LATER
    )
    assert again.project_id == resolved.project_id
    assert again.created is False
    paths = {p for (p,) in cast(list[tuple[str]], rows(conn, "SELECT path FROM project_alias"))}
    assert "/home/alice/projects/widget" in paths
    assert "/home/alice/code/widget-next" in paths


def test_merge_repoints_sessions_and_soft_retires(tmp_path: Path) -> None:
    """R4: merge never deletes; the merged project row is soft-retired and its
    sessions repoint to the kept project."""
    conn = fresh(tmp_path)
    keep = registry.resolve_project(
        conn, cwd="/home/alice/projects/widget", encoded_dir=None, now=NOW
    )
    merge = registry.resolve_project(
        conn, cwd="/home/alice/projects/gadget", encoded_dir=None, now=NOW
    )
    m = catalog.SessionMeta(
        sha256="ff" * 32,
        source_kind="claude_code",
        session_uuid="u-merge",
        slug=None,
        git_branch=None,
        cwd="/home/alice/projects/gadget",
        first_ts="2026-01-05T10:00:00.000Z",
        last_ts="2026-01-05T10:00:05.000Z",
        size_bytes=1,
        line_count=1,
        skipped_lines=0,
        summary="s",
        hidden=False,
        resolution_source="payload_cwd",
    )
    catalog.add_session(conn, m, merge.project_id, NOW)
    registry.merge_projects(conn, keep.project_id, merge.project_id)
    assert rows(conn, "SELECT project_id FROM session") == [(keep.project_id,)]
    retired = dict(
        cast(list[tuple[int, int]], rows(conn, "SELECT id, retired FROM project"))
    )
    assert retired[keep.project_id] == 0
    assert retired[merge.project_id] == 1
