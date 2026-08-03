"""ccw status and ccw verify surfaces (slice 9).

status reads the catalog only (the session table for listings/counts/size, the
capture_event table for recent errors); it opens no stored payload under objects/
(FINDINGS F5, rule R6), holds no write handle, and removes nothing (R2/R4 fences).
verify wraps the slice-1 store.verify_walk and cross-checks the catalog against the
objects in both directions; it re-implements no hashing (R9/F8) and mutates nothing in
the store (R4).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cc_warehouse import build, catalog, store, sweep
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


# Claude Code names a transcript `<uuid>.jsonl` and a sub-agent `agent-<id>.jsonl`.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_JSONL_SUFFIX = ".jsonl"


@dataclass(frozen=True)
class UncapturedGap:
    """How far the archive is behind the source tree, and by what instrument.

    `archived_root` is None when no `archive_root` is configured, which is a
    DIFFERENT state from a gap of zero: with no archive there is nothing to be
    behind, and reporting every session as uncaptured would be both alarming and
    false. Callers must distinguish the two.
    """

    sessions: int
    subagents: int
    source: Path
    archive_root: Path | None


def uncaptured_gap(config: Config, source: Path | None = None) -> UncapturedGap:
    """Sessions and sub-agents in the source tree with no archive folder.

    THE FIGURE THIS EXISTS FOR: on 2026-08-03 the warehouse held 13,836 sessions
    while the source tree held 1,857 the archive had never seen, and nothing in
    `ccw` could say so. It was computed by throwaway script three times that day.

    BY UUID, deliberately, and the cost is the reason. A source transcript is
    `<uuid>.jsonl`; an archive folder is `<stamp>_<uuid>`. This is a set
    difference over names: no file is opened and nothing is hashed, so `status`
    stays cheap enough to run constantly. Sub-agents are counted separately
    because they are not sessions (ruling (a) as amended by ticket 21) and
    because there were 1,420 of them outstanding against 437 sessions, so one
    combined number would have hidden the larger half.

    THE BLIND SPOT, stated rather than discovered later: Claude Code sometimes
    writes `<uuid>.orphaned-<n>-<hash>.jsonl`, whose stem is not a bare UUID, so
    it reads as uncaptured even when its payload is archived. Over-reporting is
    the safe direction; `ccw doctor` can afford the exact answer.

    Reads only directory entries. Nothing is created, including the archive root
    itself if it does not exist (F9).
    """
    walk_root = source if source is not None else Path.home() / ".claude" / "projects"
    if config.archive_root is None:
        return UncapturedGap(0, 0, walk_root, None)
    archived: set[str] = set()
    subagent_ids: set[str] = set()
    if config.archive_root.is_dir():
        for label_dir in config.archive_root.iterdir():
            if not label_dir.is_dir() or label_dir.name in build.RESERVED_LABELS:
                continue
            for session_dir in label_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                _stamp, _sep, tail = session_dir.name.partition("_")
                if _UUID_RE.match(tail):
                    archived.add(tail)
                nested = session_dir / "subagents"
                if nested.is_dir():
                    for agent_dir in nested.iterdir():
                        if agent_dir.is_dir():
                            _s, _p, agent_id = agent_dir.name.partition("_")
                            subagent_ids.add(agent_id)
    # The session / sub-agent split comes from sweep, which owns the source-tree
    # walk and is the one module the F4 fence exempts from filtering on the
    # `agent-` prefix. Re-deriving it here would both duplicate the walk (R9) and
    # put a filename-shaped identity check in a module that has no business
    # holding one.
    session_paths, subagent_paths = sweep.source_transcripts(walk_root)
    sessions = sum(
        1
        for path in session_paths
        if _UUID_RE.match(path.name[: -len(_JSONL_SUFFIX)])
        and path.name[: -len(_JSONL_SUFFIX)] not in archived
    )
    subagents = sum(
        1
        for path in subagent_paths
        if path.name[: -len(_JSONL_SUFFIX)].split("-", 1)[1] not in subagent_ids
    )
    return UncapturedGap(sessions, subagents, walk_root, config.archive_root)


def gap_line(gap: UncapturedGap) -> str:
    """One line an operator can read at a glance, in `status` and in `doctor`."""
    if gap.archive_root is None:
        return "Uncaptured: (no archive configured; set archive_root to track this)"
    return (
        f"Uncaptured: {gap.sessions} session(s), {gap.subagents} sub-agent(s)"
        f" in {gap.source} with no archive folder"
    )


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
    # DESIGN 7, status row amended 2026-08-03: the catalog cannot see a session
    # that was never captured, so a hook that never ran leaves no trace here. The
    # gap is the only figure that distinguishes "nothing to do" from "nothing is
    # working", which is exactly the confusion that let ten days pass unnoticed.
    lines.append(gap_line(uncaptured_gap(config)))
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
