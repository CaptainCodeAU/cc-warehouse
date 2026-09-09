"""Cross-checks capture.jsonl's error records against whether the affected session
ever actually got archived (ticket 42 #5; closes ticket 28.10's "cross-tree
reconciliation as a test, not a hand-check" gap in the same pass).

THE FAILURE THIS EXISTS FOR. Ticket 41 Finding 5 found one session with a logged
capture error and no trace anywhere -- source, archive, or catalog -- gone for good.
Measuring the real log (2026-09-09) found the true figure was 21, not 3, running at
roughly 1-2 a week since 2026-08-08: nothing before this cross-checked a capture
error against whether the session it named ever actually landed anywhere.

Pure and read-only (matches doctor.py's own contract): every function here only
reads logs/capture.jsonl, the source tree, the archive tree, and a read-only catalog
connection (doctor's `_last_capture` pattern). Nothing here writes, alerts, or
dedups -- `cli._run_repair` owns all three, the one place a finding becomes a durable
record and a notification (DESIGN 12: writes and alerts live at the edges, not here).

TWO SPEEDS, on purpose. `known_unrecoverable_count`/`known_unrecoverable_uuids` are
the cheap ones: they read only the "unrecoverable" dedup records `cli._run_repair`
already writes back into capture.jsonl, so `ccw doctor` can call them on every
SessionStart hot path with zero directory walks. Ticket 41 Finding 1 already caused a
real SessionStart timeout from an unrelated bug; this module does not hand doctor a
second way to reproduce that symptom. `find_unrecoverable` is the expensive one -- the
actual source/archive/catalog cross-check -- and only `ccw repair` (daily, off the
interactive path) and the explicit `ccw reconcile` verb call it.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cc_warehouse import sweep
from cc_warehouse.config import Config
from cc_warehouse.status import archived_session_uuids

# Message prefixes meaning this error record is not about a lost SESSION: the session
# it names is already archived (repair/companions/post-archive-write all fire only
# after the archive write succeeded), or it names a sidecar file rather than a
# transcript at all (capture.log_sidecar_trouble). Each prefix is this repo's own
# convention, added at the one call site that writes it (never guessed at here).
_EXCLUDED_PREFIXES = (
    "repair: ",
    "companions: ",
    "post-archive-write failure at ",
    "could not read sidecar ",
    "refused sidecar ",
)

# A permissive, UNANCHORED search: every record written before ticket 42 #5 carries
# its session identity only inside a free-text `message`, e.g. "unreadable transcript
# /path/to/<uuid>.jsonl: ...". This fallback resolved 24 of 29 real error records
# measured live on 2026-09-09, including all 21 genuine losses, and never retires --
# old history stays in this shape permanently.
_UUID_IN_TEXT_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# How long a fresh error record gets before it is eligible for the expensive
# cross-check, so a capture that is about to be retried (or about to be picked up by
# the next sweep) is never treated as a confirmed loss before it had a real chance to
# resolve itself.
_GRACE = timedelta(hours=1)

# How far back an alert-facing caller looks by default. Matches the companions-
# stalled check's own bounded-window posture (doctor._COMPANIONS_WINDOW) and the
# ticket's own 7-14 day suggestion, at the wider end: measured live, a 7-day window
# would have caught 7 of the 21 real losses, a 14-day window caught 14.
DEFAULT_WINDOW = timedelta(days=14)


@dataclass(frozen=True)
class Finding:
    session_uuid: str
    at: str
    message: str


def _iter_records(config: Config) -> list[dict[str, object]]:
    """Every parseable line in logs/capture.jsonl. A missing file or a malformed line
    is not a defect here (R5): it reads as no records, never a crash -- the same
    posture doctor._companions_stalled already takes reading the same file."""
    try:
        text = (config.root / "logs" / "capture.jsonl").read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, object]] = []
    for line in text.splitlines():
        try:
            record = cast("object", json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict):
            out.append(cast("dict[str, object]", record))
    return out


def _resolve_identity(record: dict[str, object]) -> str | None:
    """The session_uuid a record names: the structured field first (exact, ticket 42
    #5), the free-text fallback second (every record written before that field
    existed -- see the module docstring for why the fallback never retires)."""
    field = record.get("session_uuid")
    if isinstance(field, str) and field:
        return field
    message = record.get("message")
    if isinstance(message, str):
        found = _UUID_IN_TEXT_RE.search(message)
        if found:
            return found.group(0)
    return None


def _parse_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def _candidates(
    records: list[dict[str, object]], *, since: datetime | None, now: datetime
) -> list[Finding]:
    """Error records that name a resolvable session, are not excluded by prefix, have
    aged past the grace period, and (when `since` is given) fall inside that window.
    NOT yet cross-checked against source/archive/catalog -- see `find_unrecoverable`."""
    out: list[Finding] = []
    for record in records:
        if record.get("status") != "error":
            continue
        message = record.get("message")
        if isinstance(message, str) and message.startswith(_EXCLUDED_PREFIXES):
            continue
        session_uuid = _resolve_identity(record)
        if session_uuid is None:
            continue
        moment = _parse_at(record.get("at"))
        if moment is None:
            continue
        if since is not None and moment < since:
            continue
        if (now - moment) < _GRACE:
            continue
        out.append(
            Finding(
                session_uuid,
                moment.isoformat(),
                message if isinstance(message, str) else "(no detail)",
            )
        )
    return out


def _catalog_has_session(root: Path, session_uuid: str) -> bool:
    """A read-only existence check, doctor's own `_last_capture` connection pattern --
    never through catalog.open_catalog, whose docstring says "creating if needed"
    (this module must not materialise a warehouse that was never there)."""
    path = root / "catalog.sqlite"
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM session WHERE session_uuid = ? LIMIT 1", (session_uuid,)
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return row is not None


def find_unrecoverable(
    config: Config,
    *,
    since: datetime | None = None,
    home: Path | None = None,
    source: Path | None = None,
    now: datetime | None = None,
) -> tuple[Finding, ...]:
    """The expensive cross-check: which candidate error records name a session
    missing from ALL THREE of the source tree, the archive, and the catalog, oldest
    first.

    Requiring all three to miss is the conservative direction: a lock-contention
    error that later succeeded resolves to a session the archive (or catalog) DOES
    have, so it drops out by evidence rather than by a growing list of exception
    shapes. It also blunts the F4 path-as-identity hazard ticket 25 hit -- a payload
    filed under a folder name that differs from its legacy identity still has a
    catalog row, so the catalog check alone can save it from a false alarm.

    `since=None` (the default) checks the WHOLE log; pass an explicit cutoff (e.g.
    `datetime.now(UTC) - DEFAULT_WINDOW`) to look only at recent activity. The
    source/archive/catalog walk is skipped ENTIRELY when there are zero candidates in
    the requested window -- on a machine with none, this costs one file read only.

    KNOWN COVERAGE LIMIT, stated rather than hidden: `sweep._capture_item` returns an
    unreadable-transcript error WITHOUT writing a capture.jsonl line at all -- only a
    RAISED exception reaches `_log_item_failure`. A sweep-discovered loss of that
    exact shape is invisible here today; ticket 42 proposal #3 is the fix, tracked
    separately rather than folded in (its own review surface, sweep's hot loop)."""
    now = now if now is not None else datetime.now(UTC)
    candidates = _candidates(_iter_records(config), since=since, now=now)
    if not candidates:
        return ()
    walk_root = (
        source
        if source is not None
        else (home if home is not None else Path.home()) / ".claude" / "projects"
    )
    session_paths, _subagent_paths = sweep.source_transcripts(walk_root)
    source_uuids = {
        path.name[: -len(".jsonl")] for path in session_paths if path.name.endswith(".jsonl")
    }
    archived = archived_session_uuids(config.archive_root)
    findings: list[Finding] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.session_uuid in seen:
            continue
        if candidate.session_uuid in source_uuids or candidate.session_uuid in archived:
            continue
        if _catalog_has_session(config.root, candidate.session_uuid):
            continue
        seen.add(candidate.session_uuid)
        findings.append(candidate)
    return tuple(sorted(findings, key=lambda f: f.at))


def known_unrecoverable_uuids(config: Config) -> frozenset[str]:
    """Every session uuid `ccw repair` has already announced as unrecoverable (a
    `status: "unrecoverable"` dedup record it wrote after confirming via
    `find_unrecoverable`). Reads capture.jsonl only -- see `known_unrecoverable_count`'s
    docstring for why this must stay cheap."""
    return frozenset(
        cast(str, record["session_uuid"])
        for record in _iter_records(config)
        if record.get("status") == "unrecoverable" and isinstance(record.get("session_uuid"), str)
    )


def known_unrecoverable_count(config: Config) -> tuple[int, str | None]:
    """Cheap, log-only: how many sessions `ccw repair` has ALREADY confirmed
    unrecoverable, and the most recent one's timestamp.

    Reads capture.jsonl only -- no source/archive/catalog walk -- so `ccw doctor` can
    call this on every SessionStart hot path. `ccw doctor` runs there
    (ccw-freshness-check.py), and a real SessionStart timeout already happened once on
    this project (ticket 41 Finding 1, an unrelated cause); this module does not hand
    doctor a second way to reproduce that symptom.

    On a machine where `ccw repair` has never run its reconciliation pass, this reads
    (0, None), which means "not yet checked", not "no losses" -- the same distinction
    `doctor._last_capture` draws between "never fired" and "fired, but not recently"."""
    latest: str | None = None
    uuids: set[str] = set()
    for record in _iter_records(config):
        if record.get("status") != "unrecoverable":
            continue
        session_uuid = record.get("session_uuid")
        at = record.get("at")
        if isinstance(session_uuid, str):
            uuids.add(session_uuid)
        if isinstance(at, str) and (latest is None or at > latest):
            latest = at
    return len(uuids), latest
