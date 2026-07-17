"""SQLite catalog: frozen schema, session rows, version links, capture events.

Slice 2. DESIGN section 3; rules R1, R4 (soft flags only), R12.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionMeta:
    """Parsed facts about one stored payload, as recorded in the session table."""

    sha256: str
    source_kind: str
    session_uuid: str | None
    slug: str | None
    git_branch: str | None
    cwd: str | None
    first_ts: str | None
    last_ts: str | None
    size_bytes: int
    line_count: int
    skipped_lines: int
    summary: str
    hidden: bool
    resolution_source: str


def open_catalog(root: Path) -> sqlite3.Connection:
    """Open (creating if needed) catalog.sqlite under root with the frozen schema."""
    raise NotImplementedError


def add_session(
    conn: sqlite3.Connection, meta: SessionMeta, project_id: int, captured_at: str
) -> str:
    """Insert a session row in a transaction; returns the short citation key.

    Extends the short key past 12 hex on prefix collision; links `supersedes` when an
    older version of the same session_uuid exists.
    """
    raise NotImplementedError


def record_event(
    conn: sqlite3.Connection,
    session_hash: str,
    action: str,
    elapsed_ms: int,
    detail: str,
    at: str,
) -> None:
    raise NotImplementedError
