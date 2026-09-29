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

from cc_warehouse import archive, sweep
from cc_warehouse.config import Config
from cc_warehouse.status import archived_session_uuids

# Message prefixes meaning this error record is not about a lost SESSION: the session
# it names is already archived (repair/companions/post-archive-write all fire only
# after the archive write succeeded), or it names a sidecar file rather than a
# transcript at all (capture.log_sidecar_trouble). Each prefix is this repo's own
# convention, added at the one call site that writes it (never guessed at here).
#
# "sweep: "/"build: " (ticket 42 #2, cli._log_run_summary) are per-RUN summaries, not
# per-session records -- they name no session and no UUID ever appears in one, so
# nothing here would have matched them anyway, but excluding the prefix outright is
# cheaper than relying on that and makes the intent explicit. `ccw archive` has NO
# such summary (see cli._run_archive's own scope note: writing one would violate its
# "leaves the source warehouse byte-identical" contract), so there is no "archive: "
# to exclude. These do NOT collide with the per-item failure prefixes this module
# already resolves through the UUID-in-text fallback below: sweep's own per-item
# failure is "sweep item <name> failed: " (sweep.py's `_log_item_failure`, note
# "item", no colon after "sweep") and build's is "build failed: " / "sweep-triggered
# build failed: " (cli.py's `_log_build_failure`) -- neither starts with "sweep: " or
# "build: ".
_EXCLUDED_PREFIXES = (
    "repair: ",
    "companions: ",
    "post-archive-write failure at ",
    "could not read sidecar ",
    "refused sidecar ",
    "sweep: ",
    "build: ",
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


# EMPTY SESSIONS ARE NOT LOSSES (W-20260929-A60; ruling: Gavin, 2026-09-29, option
# B). A session opened and closed without a word never gets a transcript, and its
# SessionEnd hook still logs "unreadable transcript", so every such session used to
# be announced as permanently unrecoverable. Nothing was lost. The only instrument
# that knows what a session SAID without its transcript is `~/.claude/history.jsonl`
# (one row per typed input), so:
#   - every history row for the session is exactly `/quit` or `/exit` (surrounding
#     whitespace stripped, case kept: " /quit" is a real row, "/QUIT" is not in the
#     ruling) with no pasted content -> empty;
#   - ZERO rows -> empty ONLY when `~/.claude/session-env/<uuid>` is a directory.
#     Zero rows alone proves nothing: measured 2026-09-29, 3,550 real September
#     headless (`sdk-cli`) sessions with typed prompts had no history rows at all,
#     while 763 of 770 interactive sessions had a session-env dir.
# Every doubt fails toward ALERTING (a false alarm beats a silent real loss): no
# history file, an unreadable one, a history whose oldest row is not older than the
# error (rows for this session may have been cut), or a session-env that is not a
# directory. Other slash commands (`/clear`, `/model`, ...) are outside the ruling.
_EMPTY_SESSION_INPUTS = frozenset({"/quit", "/exit"})


@dataclass(frozen=True)
class _History:
    by_session: dict[str, bytes]
    oldest: datetime | None


def _read_history(home: Path) -> _History | None:
    """`history.jsonl` grouped by session through the sweep's own splitter (R9), or
    None when it cannot be read, which callers treat as "cannot vouch"."""
    try:
        data = (home / ".claude" / "history.jsonl").read_bytes()
    except OSError:
        return None
    by_session = archive.split_history_by_session(data)
    oldest: datetime | None = None
    for lines in by_session.values():
        for row in _rows(lines):
            stamp = row.get("timestamp")
            if isinstance(stamp, int | float) and not isinstance(stamp, bool):
                moment = datetime.fromtimestamp(stamp / 1000, UTC)
                if oldest is None or moment < oldest:
                    oldest = moment
    return _History(by_session, oldest)


def _rows(lines: bytes) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for line in lines.splitlines():
        try:
            row = cast("object", json.loads(line))
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(cast("dict[str, object]", row))
    return out


class HistoryOnce:
    """`history.jsonl` read at most once, and only on first demand, so one `ccw
    repair` can hand the same read to `find_unrecoverable` and `find_retractable`."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self._read = False
        self._history: _History | None = None

    def get(self) -> _History | None:
        if not self._read:
            self._history = _read_history(self.home)
            self._read = True
        return self._history


def _said_nothing(history: _History | None, home: Path, finding: "Finding") -> bool:
    """Whether the session a finding names provably said nothing (the ruling above).
    False whenever the evidence is missing or doubtful."""
    if history is None:
        return False
    lines = history.by_session.get(finding.session_uuid)
    if lines is None:
        ended = _parse_at(finding.at)
        if history.oldest is None or ended is None or history.oldest >= ended:
            return False
        return (home / ".claude" / "session-env" / finding.session_uuid).is_dir()
    for row in _rows(lines):
        display = row.get("display")
        if row.get("pastedContents"):
            return False
        if not isinstance(display, str) or display.strip() not in _EMPTY_SESSION_INPUTS:
            return False
    return True


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
    history: HistoryOnce | None = None,
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

    A session that misses all three but provably SAID NOTHING (`_said_nothing`, the
    2026-09-29 ruling above `Finding`) is dropped too: no transcript was ever
    written, so nothing was lost. `history.jsonl` is read at most once per call,
    and only when some candidate has already missed all three instruments; a
    caller passing its own `history` shares that one read with other checks.

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
    reader = (
        history if history is not None else HistoryOnce(home if home is not None else Path.home())
    )
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
        if _said_nothing(reader.get(), reader.home, candidate):
            continue
        findings.append(candidate)
    return tuple(sorted(findings, key=lambda f: f.at))


# RETRACTION (W-20260929-A61; ruling: Gavin, 2026-09-29, option b). The empty-
# session ruling above stops NEW announcements, but a session `ccw repair` had
# already announced stays in the append-only ledger. Repair therefore appends one
# `unrecoverable-retracted` record per recorded uuid `_said_nothing` now calls
# empty, and the cheap readers below subtract it. No ledger line is ever rewritten.
# The LATEST unrecoverable-or-retracted record for a uuid decides its state, in
# file order (the log is append-only, so file order is write order): a uuid
# announced again after a retraction is back on record, and a retraction naming a
# uuid with no unrecoverable record before it changes nothing.
UNRECOVERABLE = "unrecoverable"
RETRACTED = "unrecoverable-retracted"
# W-20260929-A82: `ccw repair` left a folder untouched because a file changed in a
# way ccw cannot explain. The dedup record for its alert, keyed on (session_uuid,
# message); its message starts "repair: ", so `_candidates` never reads it as a
# capture error (_EXCLUDED_PREFIXES).
REPAIR_REFUSED = "repair-refused"
# The folder verified clean again (restored, or re-rendered because ccw can now
# explain it). Closes every open refusal for that session_uuid, so the same
# problem appearing later alerts again (W-20260929-A82 item 6).
REPAIR_REFUSAL_RESOLVED = "repair-refusal-resolved"
# One per `ccw repair` run: the count the start-up hook reads (item 6).
REPAIR_SUMMARY = "repair-summary"


@dataclass(frozen=True)
class OpenRefusal:
    """A session repair has refused and not yet seen verify clean: when it was
    first refused, and every problem-set message announced for it since."""

    first_at: str
    messages: frozenset[str]


def _on_record(records: list[dict[str, object]]) -> dict[str, str | None]:
    """Each uuid currently on record as unrecoverable, mapped to the newest `at`
    of its unrecoverable records since its last retraction."""
    state: dict[str, str | None] = {}
    for record in records:
        status = record.get("status")
        session_uuid = record.get("session_uuid")
        if not isinstance(session_uuid, str):
            continue
        if status == RETRACTED:
            state.pop(session_uuid, None)
        elif status == UNRECOVERABLE:
            at = record.get("at")
            latest = state.get(session_uuid)
            if isinstance(at, str) and (latest is None or at > latest):
                latest = at
            state[session_uuid] = latest
    return state


def find_retractable(
    config: Config,
    *,
    home: Path | None = None,
    now: datetime | None = None,
    history: HistoryOnce | None = None,
) -> tuple[Finding, ...]:
    """Recorded-unrecoverable sessions that `_said_nothing` now calls empty, oldest
    first. Read-only: `cli._run_repair` writes the retraction records.

    Each is judged on its EARLIEST resolvable error record, the strictest `at` for
    the zero-rows arm's history-coverage guard. A recorded uuid with no such error
    record cannot be judged and stays on record (R5). `history.jsonl` is read only
    when at least one uuid is still on record, and at most once (shared through
    `history`)."""
    records = _iter_records(config)
    on_record = _on_record(records)
    if not on_record:
        return ()
    now = now if now is not None else datetime.now(UTC)
    earliest: dict[str, Finding] = {}
    for candidate in _candidates(records, since=None, now=now):
        if candidate.session_uuid in on_record and candidate.session_uuid not in earliest:
            earliest[candidate.session_uuid] = candidate
    if not earliest:
        return ()
    reader = (
        history if history is not None else HistoryOnce(home if home is not None else Path.home())
    )
    retractable = [f for f in earliest.values() if _said_nothing(reader.get(), reader.home, f)]
    return tuple(sorted(retractable, key=lambda f: f.at))


def known_unrecoverable_uuids(config: Config) -> frozenset[str]:
    """Every session uuid `ccw repair` has announced as unrecoverable (a `status:
    "unrecoverable"` dedup record it wrote after confirming via `find_unrecoverable`)
    and not since retracted. Reads capture.jsonl only -- see
    `known_unrecoverable_count`'s docstring for why this must stay cheap."""
    return frozenset(_on_record(_iter_records(config)))


def open_refusals(config: Config) -> dict[str, OpenRefusal]:
    """Every session `ccw repair` has refused and not since seen verify clean
    (W-20260929-A82). Repair re-checks each of these on every run, whether or
    not it is still in the 25-folder sample, so a refusal cannot clear itself
    just because newer sessions pushed it out. Reads capture.jsonl only."""
    state: dict[str, OpenRefusal] = {}
    for record in _iter_records(config):
        status = record.get("status")
        session_uuid = record.get("session_uuid")
        if not isinstance(session_uuid, str):
            continue
        if status == REPAIR_REFUSAL_RESOLVED:
            state.pop(session_uuid, None)
        elif status == archive.WRITER_HELD:
            # A writer skipped the folder (unreadable manifest): open it for
            # repair to re-check and alert on, keeping the first sighting.
            at = record.get("at")
            prev = state.get(session_uuid)
            if prev is None and isinstance(at, str):
                state[session_uuid] = OpenRefusal(at, frozenset[str]())
        elif status == REPAIR_REFUSED:
            at = record.get("at")
            message = record.get("message")
            prev = state.get(session_uuid)
            first = prev.first_at if prev is not None else (at if isinstance(at, str) else "")
            messages = prev.messages if prev is not None else frozenset[str]()
            if isinstance(message, str):
                messages = messages | {message}
            state[session_uuid] = OpenRefusal(first, messages)
    return state


def known_refusals(config: Config) -> frozenset[tuple[str, str]]:
    """Every (session_uuid, message) `ccw repair` has already alerted on, among
    refusals still open. THE DEDUP IS THE LOG COMPARE, the same principle
    `cli._announce_unrecoverable` states: the same folder with the same problems
    stays silent on every later run, a different problem set on it re-fires, and
    after the folder verifies clean the same problem alerts again."""
    return frozenset(
        (session_uuid, message)
        for session_uuid, refusal in open_refusals(config).items()
        for message in refusal.messages
    )


def known_unrecoverable_count(config: Config) -> tuple[int, str | None]:
    """Cheap, log-only: how many sessions `ccw repair` has ALREADY confirmed
    unrecoverable and not retracted, and the most recent such record's timestamp.

    Reads capture.jsonl only -- no source/archive/catalog walk, no history.jsonl --
    so `ccw doctor` can call this on every SessionStart hot path. `ccw doctor` runs
    there (ccw-freshness-check.py), and a real SessionStart timeout already happened
    once on this project (ticket 41 Finding 1, an unrelated cause); this module does
    not hand doctor a second way to reproduce that symptom
    (tests/test_reconcile.py::test_the_cheap_count_never_reads_history).

    On a machine where `ccw repair` has never run its reconciliation pass, this reads
    (0, None), which means "not yet checked", not "no losses" -- the same distinction
    `doctor._last_capture` draws between "never fired" and "fired, but not recently"."""
    on_record = _on_record(_iter_records(config))
    stamps = [at for at in on_record.values() if at is not None]
    return len(on_record), max(stamps) if stamps else None
