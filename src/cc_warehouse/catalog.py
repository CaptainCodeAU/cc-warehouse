"""SQLite catalog: frozen schema, session rows, version links, capture events.

Slice 2. DESIGN section 3; rules R1, R4 (soft flags only), R12.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cc_warehouse.store import is_sha256_hex

# DESIGN section 3 DDL, frozen by the slice-2 oracle tests. Rows are soft-flagged
# (retired, hidden), not removed (R4); first_ts/last_ts come from payload
# internals, not file mtimes (R12). SQLite writes catalog.sqlite through its own
# transactional machinery (the sanctioned R2 exception).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    retired INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_alias (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id),
    path TEXT NOT NULL,
    kind TEXT NOT NULL,          -- 'cwd' | 'encoded_dir' | 'label_claim'
    first_seen TEXT,
    last_seen TEXT,
    UNIQUE (path, kind)
);

CREATE TABLE IF NOT EXISTS session (
    hash TEXT PRIMARY KEY,       -- full sha256 (R1: identity is the content hash)
    short TEXT NOT NULL UNIQUE,  -- s: citation key, 12 hex unless extended
    project_id INTEGER REFERENCES project(id),
    source_kind TEXT NOT NULL,
    session_uuid TEXT,           -- version-links copies
    supersedes TEXT REFERENCES session(hash),
    slug TEXT,
    git_branch TEXT,
    cwd TEXT,
    first_ts TEXT,               -- from JSONL internals, never mtime (R12)
    last_ts TEXT,
    size_bytes INTEGER,
    line_count INTEGER,
    skipped_lines INTEGER,
    summary TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    captured_at TEXT NOT NULL,
    resolution_source TEXT
);

CREATE TABLE IF NOT EXISTS capture_event (
    id INTEGER PRIMARY KEY,
    at TEXT,
    session_hash TEXT,
    action TEXT,                 -- 'stored' | 'skipped_unchanged' | 'superseded' | 'error'
    elapsed_ms INTEGER,
    detail TEXT
);

-- Every capture touches these three lookups (version chain, project grouping,
-- alias repoint on merge); without indexes each is a full scan (F5). Indexes
-- add no columns, so the frozen table_info assertions are unaffected.
CREATE INDEX IF NOT EXISTS idx_session_uuid ON session(session_uuid);
CREATE INDEX IF NOT EXISTS idx_session_project ON session(project_id);
CREATE INDEX IF NOT EXISTS idx_alias_project ON project_alias(project_id);
"""


@contextmanager
def writing(conn: sqlite3.Connection) -> Generator[None, None, None]:
    """Run a read-decide-write sequence under a held reserved write lock.

    open_catalog sets isolation_level = None, so Python issues no implicit BEGIN.
    Left in legacy autocommit, a SELECT-then-INSERT would be unlocked between the
    read and the write, letting two writers both miss the lookup and both insert
    (R14/F3). BEGIN IMMEDIATE takes the reserved lock at the first statement, so a
    contender waits on busy_timeout instead of racing. Commit on success; roll
    back and re-raise on any error, leaving the catalog untouched (R5).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


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
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "catalog.sqlite")
    # One transaction discipline for every mutating path: no implicit BEGIN, so
    # writing() owns BEGIN IMMEDIATE / COMMIT explicitly (R14). busy_timeout makes
    # a contender wait for the reserved lock instead of erroring at once.
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA)
    return conn


def _short_key(conn: sqlite3.Connection, sha256: str) -> str:
    """First 12 hex; on a prefix collision with an earlier session, extend by 4
    until no other stored hash shares the prefix (DESIGN section 2). Older
    citations stay valid: existing short keys are never rewritten."""
    for length in range(12, 65, 4):
        candidate = sha256[:length]
        # Prefix membership as a range on the hash PK so the query rides the
        # primary-key index instead of scanning every row (F5): all hashes are
        # 64 lowercase hex, so the prefix's band is [candidate+000.., candidate+fff..].
        low = candidate + "0" * (64 - length)
        high = candidate + "f" * (64 - length)
        clash = conn.execute(
            "SELECT 1 FROM session WHERE hash >= ? AND hash <= ? AND hash != ? LIMIT 1",
            (low, high, sha256),
        ).fetchone()
        if clash is None:
            return candidate
    return sha256


def _latest_version(conn: sqlite3.Connection, session_uuid: str | None) -> str | None:
    """Hash of the latest existing version of this session_uuid.

    Recency is the payload-internal last_ts, not warehouse capture order (R12):
    a NULL last_ts falls back to captured_at, ties break on captured_at then
    rowid.

    WHAT THIS DOES NOT GUARANTEE, and the previous docstring claimed it did.
    It said "a late-imported old export therefore never displaces the newer
    copy". That is FALSE, and the correction is recorded rather than quietly
    swapped because the sentence had stood beside working code and would have
    told the next reader that ticket 29 was closed.

    This function picks the right SUPERSEDES TARGET. It does not decide the
    head. `build._heads` defines a head as a row no other row supersedes, so
    the newest INSERT is always the head whatever its payload says: import an
    OLDER copy after a newer one and the older copy becomes current. Proved by
    execution 2026-08-05, not by reading. That is ticket 29 mechanism 1, which
    is OPEN and unscoped; do not change this function or `build._heads` to fix
    it without scoping the change with the principal first.
    """
    if session_uuid is None:
        return None
    row = conn.execute(
        "SELECT hash FROM session WHERE session_uuid = ?"
        " ORDER BY COALESCE(last_ts, captured_at) DESC, captured_at DESC, rowid DESC"
        " LIMIT 1",
        (session_uuid,),
    ).fetchone()
    if row is None:
        return None
    return cast(str, cast(tuple[object, ...], row)[0])


def add_session(
    conn: sqlite3.Connection, meta: SessionMeta, project_id: int, captured_at: str
) -> str:
    """Insert a session row in a transaction; returns the short citation key.

    Extends the short key past 12 hex on prefix collision; links `supersedes` when an
    older version of the same session_uuid exists. Idempotent by identity: a hash
    already stored returns its existing short key with no insert and no error, so a
    duplicate capture of stored content is a no-op, never an IntegrityError (R14/F3).
    """
    if not is_sha256_hex(meta.sha256):
        raise ValueError(f"not a lowercase sha256 hex digest: {meta.sha256!r}")
    with writing(conn):
        existing = conn.execute(
            "SELECT short FROM session WHERE hash = ?", (meta.sha256,)
        ).fetchone()
        if existing is not None:
            return cast(str, cast(tuple[object, ...], existing)[0])
        short = _short_key(conn, meta.sha256)
        supersedes = _latest_version(conn, meta.session_uuid)
        conn.execute(
            "INSERT INTO session (hash, short, project_id, source_kind, session_uuid,"
            " supersedes, slug, git_branch, cwd, first_ts, last_ts, size_bytes,"
            " line_count, skipped_lines, summary, hidden, captured_at, resolution_source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                meta.sha256,
                short,
                project_id,
                meta.source_kind,
                meta.session_uuid,
                supersedes,
                meta.slug,
                meta.git_branch,
                meta.cwd,
                meta.first_ts,
                meta.last_ts,
                meta.size_bytes,
                meta.line_count,
                meta.skipped_lines,
                meta.summary,
                int(meta.hidden),
                captured_at,
                meta.resolution_source,
            ),
        )
    return short


def record_event(
    conn: sqlite3.Connection,
    session_hash: str,
    action: str,
    elapsed_ms: int,
    detail: str,
    at: str,
) -> None:
    with writing(conn):
        conn.execute(
            "INSERT INTO capture_event (at, session_hash, action, elapsed_ms, detail)"
            " VALUES (?, ?, ?, ?, ?)",
            (at, session_hash, action, elapsed_ms, detail),
        )
