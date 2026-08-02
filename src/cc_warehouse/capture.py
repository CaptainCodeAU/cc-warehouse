"""Capture pipeline shared verbatim by the hook, sweep, and migrate (DESIGN section 4, R9).

Slice 4 (hook + notify wiring; the render child stays a stub until slice 8). This is
the ONE store-and-catalog routine (R9/F8): `ccw hook` today, `ccw sweep` and
`ccw migrate` later, all call `capture_transcript`. Identity is the payload's sha256
(R1); the store write precedes the catalog row; a per-hash O_EXCL lock serializes the
read-decide-store-record critical section so N concurrent captures of one session yield
exactly one object, one row, and one `stored` event (F3/R14).
"""

import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cc_warehouse import catalog, parser, registry, store
from cc_warehouse.config import Config

# DESIGN section 4: a re-fire whose latest capture_event landed within this window is a
# duplicate SessionEnd invocation (both wired hook paths fired), suppressed and silent;
# an unchanged re-fire outside it reports skipped_unchanged.
_DUP_WINDOW = timedelta(seconds=10)

# Bound on the wait for the per-hash capture lock. The critical section is milliseconds
# (hash + store + a few catalog statements), so contenders serialize quickly; the bound
# only guards against a wedged holder (R5: refuse rather than wait forever).
_LOCK_WAIT_S = 30.0
_LOCK_POLL_S = 0.02

# v1 source (DESIGN section 5): the store accepts any blob; this slice captures JSONL.
_SOURCE_KIND = "claude_code"


@dataclass(frozen=True)
class CaptureResult:
    sha256: str
    short: str
    action: str  # stored | skipped_unchanged | duplicate-invocation | error
    project_id: int | None
    elapsed_ms: int
    detail: str


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def _acquire_capture_lock(root: Path, name: str, deadline: float) -> bool:
    """Contend for the per-hash lock until won or the deadline passes.

    store.acquire_lock refuses immediately while a live holder owns the lock, so the
    losers spin here until the winner releases; then exactly one loser wins the freed
    lock (O_EXCL) and the rest keep waiting (F3)."""
    while True:
        if store.acquire_lock(root, name):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_LOCK_POLL_S)


def _existing_short(conn: sqlite3.Connection, digest: str) -> str | None:
    row = conn.execute("SELECT short FROM session WHERE hash = ?", (digest,)).fetchone()
    if row is None:
        return None
    return cast(str, cast(tuple[object, ...], row)[0])


def _latest_event_at(conn: sqlite3.Connection, digest: str) -> str | None:
    """The `at` of the most recent capture_event for this hash (insertion order)."""
    row = conn.execute(
        "SELECT at FROM capture_event WHERE session_hash = ? ORDER BY id DESC LIMIT 1",
        (digest,),
    ).fetchone()
    if row is None:
        return None
    value = cast(tuple[object, ...], row)[0]
    return value if isinstance(value, str) else None


def _within_window(now: datetime, last_at: str | None) -> bool:
    """True when `last_at` is within the duplicate-invocation window of `now`.

    fromisoformat parses the trailing Z that the catalog stores; a naive timestamp is
    read as UTC. An unparseable value falls to the conservative branch (not within the
    window), so a bad timestamp reports skipped_unchanged rather than silently swallowing
    the event (R5)."""
    if last_at is None:
        return False
    try:
        parsed = datetime.fromisoformat(last_at)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now - parsed <= _DUP_WINDOW


def _resolve(
    conn: sqlite3.Connection,
    transcript_path: Path,
    payload_cwd: str | None,
    parsed: parser.ParsedSession,
    now_iso: str,
) -> tuple[str, str | None, int]:
    """SPEC section 3 ladder: payload cwd -> first jsonl cwd -> transcript parent dir ->
    _unresolved.

    Returns (resolution_source, session_cwd, project_id). The transcript parent dir name
    is already Claude Code's encoded form, so it is passed straight to
    registry.resolve_project as `encoded_dir` (no forward encoder is needed here). On the
    transcript_dir rung there is no real working directory, so session.cwd is None and the
    project is keyed by the encoded dir alone. The 4th rung catches a session with no
    payload cwd, no jsonl cwd, AND no usable transcript dir name (e.g. a root-level
    transcript): rather than let registry.resolve_project raise on the empty key and
    error-drop the session, it is attributed to a stable `_unresolved` bucket (source
    label `unresolved`) so the row is still stored and reported (SPEC section 3
    did-we-lose-anything)."""
    encoded_dir = transcript_path.parent.name
    if payload_cwd is not None and payload_cwd.strip():
        source, session_cwd = "payload_cwd", payload_cwd
    elif parsed.cwd is not None and parsed.cwd.strip():
        source, session_cwd = "jsonl_cwd", parsed.cwd
    elif encoded_dir.strip():
        source, session_cwd = "transcript_dir", None
    else:
        source, session_cwd, encoded_dir = "unresolved", None, "_unresolved"
    resolved = registry.resolve_project(
        conn, cwd=session_cwd, encoded_dir=encoded_dir, now=now_iso
    )
    return source, session_cwd, resolved.project_id


def _capture_locked(
    conn: sqlite3.Connection,
    config: Config,
    data: bytes,
    digest: str,
    transcript_path: Path,
    session_id: str | None,
    payload_cwd: str | None,
    now: datetime,
    now_iso: str,
    start: float,
) -> CaptureResult:
    existing = _existing_short(conn, digest)
    if existing is not None:
        # Identity already stored (F1: decided by hash, never size). Inside the window
        # this is a duplicate SessionEnd invocation (silent); outside it, an unchanged
        # re-fire reported as skipped_unchanged.
        if _within_window(now, _latest_event_at(conn, digest)):
            action = "duplicate-invocation"
        else:
            action = "skipped_unchanged"
        elapsed = _elapsed_ms(start)
        catalog.record_event(conn, digest, action, elapsed, "", now_iso)
        return CaptureResult(digest, existing, action, None, elapsed, "")

    # Fresh identity: the content-named store write precedes the catalog row.
    store.put(config.root, data)
    parsed = parser.parse_session(data)
    source, session_cwd, project_id = _resolve(conn, transcript_path, payload_cwd, parsed, now_iso)
    _archive_source(config, conn, project_id, data)
    meta = catalog.SessionMeta(
        sha256=digest,
        source_kind=_SOURCE_KIND,
        session_uuid=parsed.session_uuid or session_id,
        slug=parsed.slug,
        git_branch=parsed.git_branch,
        cwd=session_cwd,
        first_ts=parsed.first_ts,
        last_ts=parsed.last_ts,
        size_bytes=len(data),
        line_count=parsed.line_count,
        skipped_lines=parsed.skipped_lines,
        summary=parsed.summary,
        hidden=parsed.hidden,
        resolution_source=source,
    )
    short = catalog.add_session(conn, meta, project_id, now_iso)
    elapsed = _elapsed_ms(start)
    catalog.record_event(conn, digest, "stored", elapsed, "", now_iso)
    return CaptureResult(digest, short, "stored", project_id, elapsed, source)


def _archive_source(
    config: Config, conn: sqlite3.Connection, project_id: int, data: bytes
) -> None:
    """Put the session's JSONL in its archive folder SYNCHRONOUSLY (slice 19k).

    Runs inside the hook rather than in the detached render child, because the
    child is a renderer and must never be the thing that makes a session safe.
    While `objects/` still exists this is a second home; when `objects/` is
    retired it becomes the only one, and a child that never ran would otherwise
    have meant a session that existed nowhere but `~/.claude`.

    Never fatal, for now. The store already holds the payload by the time this
    runs, so an archive problem must not fail a capture that has already
    succeeded. THAT CHANGES when `objects/` retires and this becomes the last
    line of defence; the oracle suite records the dependency rather than
    assuming it away.
    """
    if config.archive_root is None:
        return
    try:
        row = conn.execute(
            "SELECT label FROM project WHERE id = ?", (project_id,)
        ).fetchone()
        label = str(row[0]) if row else "_unlabeled"
        from cc_warehouse import archive

        archive.write_source(config.archive_root, label, data, config.archive_timezone)
    except Exception:
        return


def capture_transcript(
    config: Config, transcript_path: Path, *, session_id: str | None, cwd: str | None
) -> CaptureResult:
    """Hash-first, identity-idempotent capture of one transcript into the store + catalog.

    Reads the transcript, hashes it, and under a per-hash O_EXCL lock decides between a
    fresh store (action `stored`), a duplicate SessionEnd invocation (`duplicate-invocation`,
    within the window), and an unchanged re-fire (`skipped_unchanged`). An unreadable
    transcript takes the conservative branch and returns an `error` result rather than
    raising, so a batch caller (sweep/migrate) can report the item and continue (R5/R10);
    the source transcript is never written (F9). Any deeper failure propagates to the
    caller's never-raise boundary with the lock released and the connection closed."""
    start = time.monotonic()
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    try:
        data = transcript_path.read_bytes()
    except OSError as exc:
        detail = f"unreadable transcript {transcript_path}: {exc}"
        return CaptureResult("", "", "error", None, _elapsed_ms(start), detail)
    digest = store.sha256_hex(data)
    lock_name = f"capture-{digest}"
    if not _acquire_capture_lock(config.root, lock_name, start + _LOCK_WAIT_S):
        return CaptureResult(
            digest, "", "error", None, _elapsed_ms(start), "capture lock unavailable"
        )
    try:
        conn = catalog.open_catalog(config.root)
        try:
            return _capture_locked(
                conn,
                config,
                data,
                digest,
                transcript_path,
                session_id,
                cwd,
                now,
                now_iso,
                start,
            )
        finally:
            conn.close()
    finally:
        store.release_lock(config.root, lock_name)
