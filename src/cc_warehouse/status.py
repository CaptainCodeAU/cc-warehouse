"""ccw status and ccw verify surfaces (slice 9).

status reads the catalog only (the session table for listings/counts/size, the
capture_event table for recent errors); it opens no stored payload under objects/
(FINDINGS F5, rule R6), holds no write handle, and removes nothing (R2/R4 fences).
verify wraps the slice-1 store.verify_walk and cross-checks the catalog against the
objects in both directions; it re-implements no hashing (R9/F8) and mutates nothing in
the store (R4).
"""

from dataclasses import dataclass
from typing import cast

from cc_warehouse import catalog, store
from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport, ItemOutcome

# How many rows the human status summary lists at a glance; the CLI could widen these
# with flags in a later slice.
_RECENT_LIMIT = 10
_ERROR_LIMIT = 5


@dataclass(frozen=True)
class SessionListing:
    short: str
    label: str
    summary: str
    captured_at: str


def recent_sessions(config: Config, limit: int = 10) -> list[SessionListing]:
    """Recent captures from the catalog, newest first; opens zero stored payloads (F5).

    Reads catalog.sqlite only: one SELECT over the session table left-joined to project
    for the label, ordered by captured_at then rowid so the order stays stable when two
    rows share a capture time. No object under objects/ and no size stat are touched
    here; the listing is a pure catalog read (R6/F5)."""
    conn = catalog.open_catalog(config.root)
    try:
        rows = cast(
            list[tuple[str, str, str, str]],
            conn.execute(
                "SELECT s.short, COALESCE(p.label, ''),"
                " COALESCE(s.summary, ''), COALESCE(s.captured_at, '')"
                " FROM session AS s LEFT JOIN project AS p ON s.project_id = p.id"
                " ORDER BY s.captured_at DESC, s.rowid DESC"
                " LIMIT ?",
                (limit,),
            ).fetchall(),
        )
    finally:
        conn.close()
    return [
        SessionListing(short=row[0], label=row[1], summary=row[2], captured_at=row[3])
        for row in rows
    ]


def status_text(config: Config) -> str:
    """Human summary: recent captures, session count, stored size, recent errors.

    Every figure comes from the catalog: the session count and the SUM of size_bytes from
    the session table, the last errors from the capture_event table. No object under
    objects/ is opened and the verify walk is not run (R6/F5). No file mtime reaches the
    output (R12): captured_at is the catalog's own capture time, not a filesystem stamp."""
    conn = catalog.open_catalog(config.root)
    try:
        session_total = cast(
            tuple[int], conn.execute("SELECT COUNT(*) FROM session").fetchone()
        )[0]
        stored_bytes = cast(
            tuple[int],
            conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM session").fetchone(),
        )[0]
        error_rows = cast(
            list[tuple[str | None, str | None, str | None]],
            conn.execute(
                "SELECT at, session_hash, detail FROM capture_event"
                " WHERE action = 'error' ORDER BY id DESC LIMIT ?",
                (_ERROR_LIMIT,),
            ).fetchall(),
        )
    finally:
        conn.close()
    recent = recent_sessions(config, limit=_RECENT_LIMIT)
    lines = [f"cc-warehouse: {session_total} session(s), {stored_bytes} byte(s) stored"]
    lines.append("Recent captures:")
    if recent:
        for listing in recent:
            label = listing.label or "(no project)"
            summary = listing.summary or "(no summary)"
            lines.append(f"  {listing.short}  {label}  {summary}")
    else:
        lines.append("  (none)")
    lines.append("Recent errors:")
    if error_rows:
        for at, session_hash, detail in error_rows:
            when = at or "(unknown time)"
            which = (session_hash or "")[:12] or "(no session)"
            what = detail or "(no detail)"
            lines.append(f"  {when}  {which}  {what}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


def verify(config: Config) -> BatchReport:
    """Wrap store.verify_walk and cross-check the catalog against the objects both ways.

    store.verify_walk re-hashes each stored object against its address (the one hashing
    implementation, R9/F8): a digest mismatch is a corrupted object, an object that could
    not be read is an unreadable object, and a walk result that hashes cleanly but whose
    digest has no catalog row is an orphan (reported, left in place, R4; sweep re-adopts
    it). The reverse direction the walk cannot see, a catalog row whose object is absent,
    is a missing object, found by asking the store whether each catalog hash exists. A
    catalog row whose hash is NULL or not a sha256 digest is itself reported (as malformed)
    and skipped, never handed to the store, so a poisoned row cannot crash the walk or
    suppress the genuine findings (R5/F7). The catalog hash set is fetched once, one SELECT
    rather than a per-object scan (R6/F5). This function only reads and reports; it writes
    and removes nothing in the store (R4)."""
    root = config.root
    conn = catalog.open_catalog(root)
    try:
        hash_rows = cast(
            list[tuple[str | None]],
            conn.execute("SELECT hash FROM session").fetchall(),
        )
    finally:
        conn.close()
    catalog_hashes = {row[0] for row in hash_rows}
    outcomes: list[ItemOutcome] = []
    for result in store.verify_walk(root):
        if not result.ok:
            if result.actual_sha256 == "":
                outcomes.append(
                    ItemOutcome(
                        item=result.expected_sha256[:12],
                        action="unreadable",
                        detail="stored object is unreadable",
                    )
                )
            else:
                outcomes.append(
                    ItemOutcome(
                        item=result.expected_sha256[:12],
                        action="corrupted",
                        detail="stored object does not match its content address",
                    )
                )
        elif result.expected_sha256 not in catalog_hashes:
            outcomes.append(
                ItemOutcome(
                    item=result.expected_sha256[:12],
                    action="orphan",
                    detail="stored object has no catalog row; sweep re-adopts it",
                )
            )
    for digest in sorted(catalog_hashes, key=lambda h: (h is None, h or "")):
        if digest is None or not store.is_sha256_hex(digest):
            outcomes.append(
                ItemOutcome(
                    item="<null>" if digest is None else digest[:12],
                    action="malformed",
                    detail="catalog row has a malformed hash",
                )
            )
            continue
        if not store.has(root, digest):
            outcomes.append(
                ItemOutcome(
                    item=digest[:12],
                    action="missing",
                    detail="catalog row has no stored object",
                )
            )
    return BatchReport(tuple(outcomes))
