"""Oracle tests: SQLite catalog schema and session rows (slice 2).

Contract: DESIGN sections 2-3; rules R1, R4 (soft flags), R12; FINDINGS F1, F4.
These tests freeze the Phase 2 DDL: table and column names below are the contract.
"""

import sqlite3
from pathlib import Path
from typing import cast

from cc_warehouse import catalog, registry

NOW = "2026-01-05T12:00:00Z"


def meta(
    sha256: str,
    *,
    session_uuid: str | None = "11111111-2222-3333-4444-555555555555",
    first_ts: str | None = "2026-01-05T10:00:00.000Z",
    last_ts: str | None = "2026-01-05T10:00:05.000Z",
    hidden: bool = False,
    summary: str = "a summary",
) -> catalog.SessionMeta:
    return catalog.SessionMeta(
        sha256=sha256,
        source_kind="claude_code",
        session_uuid=session_uuid,
        slug="fix-flux",
        git_branch="main",
        cwd="/home/alice/projects/widget",
        first_ts=first_ts,
        last_ts=last_ts,
        size_bytes=123,
        line_count=2,
        skipped_lines=0,
        summary=summary,
        hidden=hidden,
        resolution_source="payload_cwd",
    )


def open_with_project(tmp_path: Path) -> tuple[sqlite3.Connection, int]:
    conn = catalog.open_catalog(tmp_path / "warehouse")
    resolved = registry.resolve_project(
        conn,
        cwd="/home/alice/projects/widget",
        encoded_dir="-home-alice-projects-widget",
        now=NOW,
    )
    return conn, resolved.project_id


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = cast(list[tuple[object, ...]], conn.execute(f"PRAGMA table_info({table})").fetchall())
    return {cast(str, r[1]) for r in rows}


def test_open_catalog_creates_frozen_schema(tmp_path: Path) -> None:
    conn = catalog.open_catalog(tmp_path / "warehouse")
    assert (tmp_path / "warehouse" / "catalog.sqlite").exists()
    assert {"id", "label", "created_at", "retired"} <= columns(conn, "project")
    assert {"id", "project_id", "path", "kind", "first_seen", "last_seen"} <= columns(
        conn, "project_alias"
    )
    assert {
        "hash",
        "short",
        "project_id",
        "source_kind",
        "session_uuid",
        "supersedes",
        "slug",
        "git_branch",
        "cwd",
        "first_ts",
        "last_ts",
        "size_bytes",
        "line_count",
        "skipped_lines",
        "summary",
        "hidden",
        "captured_at",
        "resolution_source",
    } <= columns(conn, "session")
    assert {"id", "at", "session_hash", "action", "elapsed_ms", "detail"} <= columns(
        conn, "capture_event"
    )


def test_add_session_returns_12hex_short_key(tmp_path: Path) -> None:
    conn, project_id = open_with_project(tmp_path)
    digest = "ab" * 32
    short = catalog.add_session(conn, meta(digest), project_id, NOW)
    assert short == digest[:12]
    rows = cast(
        list[tuple[object, ...]],
        conn.execute("SELECT hash, short, project_id FROM session").fetchall(),
    )
    assert rows == [(digest, digest[:12], project_id)]


def test_short_key_extends_on_prefix_collision(tmp_path: Path) -> None:
    """DESIGN section 2: on a 12-hex prefix collision the newer short key
    extends until unique; existing citations stay valid."""
    conn, project_id = open_with_project(tmp_path)
    prefix = "0123456789ab"
    h1 = prefix + "0" * 52
    h2 = prefix + "1" * 52
    short1 = catalog.add_session(conn, meta(h1, session_uuid="u-1"), project_id, NOW)
    short2 = catalog.add_session(conn, meta(h2, session_uuid="u-2"), project_id, NOW)
    assert short1 == prefix
    assert short2 != short1
    assert len(short2) > 12
    assert h2.startswith(short2)


def test_grown_session_links_supersedes_and_keeps_both(tmp_path: Path) -> None:
    """DESIGN section 2: a grown JSONL becomes the same uuid's new version;
    versions are linked, newest canonical, all kept."""
    conn, project_id = open_with_project(tmp_path)
    h1 = "aa" * 32
    h2 = "bb" * 32
    catalog.add_session(conn, meta(h1), project_id, NOW)
    catalog.add_session(conn, meta(h2), project_id, "2026-01-05T13:00:00Z")
    rows = cast(
        list[tuple[object, ...]],
        conn.execute("SELECT hash, supersedes FROM session ORDER BY captured_at").fetchall(),
    )
    assert len(rows) == 2
    assert rows[0] == (h1, None)
    assert rows[1] == (h2, h1)


def test_soft_flags_only_hidden_and_retired(tmp_path: Path) -> None:
    """R4: rows are never hard-deleted; hidden/retired are soft flags."""
    conn, project_id = open_with_project(tmp_path)
    catalog.add_session(conn, meta("cc" * 32, hidden=True, summary="warmup"), project_id, NOW)
    rows = cast(
        list[tuple[object, ...]],
        conn.execute("SELECT hidden FROM session").fetchall(),
    )
    assert rows == [(1,)]


def test_session_timestamps_come_from_payload_internals(tmp_path: Path) -> None:
    """R12: first_ts/last_ts are the JSONL-internal timestamps, never file mtimes."""
    conn, project_id = open_with_project(tmp_path)
    catalog.add_session(conn, meta("dd" * 32), project_id, NOW)
    rows = cast(
        list[tuple[object, ...]],
        conn.execute("SELECT first_ts, last_ts FROM session").fetchall(),
    )
    assert rows == [("2026-01-05T10:00:00.000Z", "2026-01-05T10:00:05.000Z")]


def test_record_event_appends_capture_events(tmp_path: Path) -> None:
    conn, project_id = open_with_project(tmp_path)
    digest = "ee" * 32
    catalog.add_session(conn, meta(digest), project_id, NOW)
    catalog.record_event(conn, digest, "stored", 12, "hook", NOW)
    catalog.record_event(conn, digest, "skipped_unchanged", 3, "hook", NOW)
    rows = cast(
        list[tuple[object, ...]],
        conn.execute("SELECT session_hash, action, elapsed_ms FROM capture_event").fetchall(),
    )
    assert rows == [(digest, "stored", 12), (digest, "skipped_unchanged", 3)]
