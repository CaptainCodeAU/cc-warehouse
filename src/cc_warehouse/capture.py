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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cc_warehouse import catalog, notify, parser, registry, sidecars, store
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

# Retry budget for a TRANSIENT catalog-write failure under contention (ticket 31.4's
# own follow-up, operator-approved 2026-08-24). The per-hash lock above only
# serializes two captures of the SAME session; a burst of DIFFERENT sessions (many
# Claude Code sessions ending within seconds of each other) can still all reach
# catalog.sqlite at once. `catalog.open_catalog_at` already sets a 5s busy_timeout
# per attempt (R14: SQLite's own reserved lock, via BEGIN IMMEDIATE, is the
# coordination primitive) -- the gap was giving up the moment that one attempt's
# wait was exceeded. Public (not `_`-prefixed) so a caller/test can read the exact
# attempt count without duplicating it.
CATALOG_RETRY_ATTEMPTS = 3
_CATALOG_RETRY_POLL_S = 0.05


def _is_lock_contention(exc: BaseException) -> bool:
    """True only for the transient shape this retry is licensed to paper over
    (R5): a real bug must still fail on the first attempt, not get masked behind
    several silent retries."""
    return isinstance(exc, sqlite3.OperationalError) and (
        "locked" in str(exc).lower() or "busy" in str(exc).lower()
    )


def _retry_on_lock_contention[T](fn: Callable[[], T]) -> T:
    """Call `fn()`, retrying up to CATALOG_RETRY_ATTEMPTS times total if it raises
    the transient "database is locked"/"database is busy" shape. Any other
    exception -- or the last attempt of this one -- propagates unchanged, same as
    before this retry existed."""
    last: sqlite3.OperationalError | None = None
    for attempt in range(CATALOG_RETRY_ATTEMPTS):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not _is_lock_contention(exc):
                raise
            last = exc
            if attempt < CATALOG_RETRY_ATTEMPTS - 1:
                time.sleep(_CATALOG_RETRY_POLL_S)
    assert last is not None  # loop always executes at least once
    raise last

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


def _log_stage_failure(config: Config, digest: str, stage: str, exc: Exception) -> None:
    """Best-effort diagnostic line naming WHICH post-archive-write step failed (ticket 31.4).

    The archive JSONL write (`_archive_source`) already succeeded by the time either
    caller below can raise, so a bare `repr(exc)` at the top-level never-raise boundary
    (`_run_hook`) does not say whether the session ended up cataloged at all. This logs to
    the existing O_APPEND audit log (DESIGN R2's sanctioned exception; no new write path)
    and always re-raises right after, so behavior is unchanged until the next real
    occurrence names its actual exception instead of leaving it unproven."""
    try:
        notify.append_log(
            config,
            {
                "at": datetime.now(UTC).isoformat(),
                "status": "error",
                "session": digest,
                "project": None,
                "message": f"post-archive-write failure at {stage}: {type(exc).__name__}: {exc}",
                "elapsed_ms": None,
            },
        )
    except Exception:
        return


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

    # Fresh identity: the durable write precedes the catalog row, so a row never
    # names a payload nothing holds. Which write that IS moves with the config:
    # the vault while it exists, the archive once it retires (slice 19m).
    if config.keep_objects:
        store.put(config.root, data)
    parsed = parser.parse_session(data)
    source, session_cwd, project_id = _resolve(conn, transcript_path, payload_cwd, parsed, now_iso)
    _archive_source(config, conn, project_id, data)
    _archive_subagents_of(config, conn, project_id, transcript_path, parsed)
    # Ticket 38. Both are wrapped in the never-fatal posture `_archive_project_file`
    # already uses (DESIGN 12): the session is stored by this point, and neither a
    # copier nor a signal may turn that into a reported failure.
    refused: tuple[str, ...] = ()
    try:
        refused = _archive_sidecars_of(config, conn, project_id, transcript_path, parsed)
    except Exception:  # noqa: BLE001 - see DESIGN 12; the session is already stored
        refused = ()
    try:
        _note_unknown_siblings(config, conn, project_id, transcript_path, parsed, refused)
    except Exception:  # noqa: BLE001 - a signal must never be what fails a capture
        pass
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
    try:
        short = _retry_on_lock_contention(
            lambda: catalog.add_session(conn, meta, project_id, now_iso)
        )
    except Exception as exc:
        _log_stage_failure(config, digest, "add_session", exc)
        raise
    elapsed = _elapsed_ms(start)
    try:
        _retry_on_lock_contention(
            lambda: catalog.record_event(conn, digest, "stored", elapsed, "", now_iso)
        )
    except Exception as exc:
        _log_stage_failure(config, digest, "record_event", exc)
        raise
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

    THE PROMISE FLIPS WITH `keep_objects`, and this is the whole point of the
    slice. While the vault exists the payload is already safe by the time this
    runs, so an archive problem must not fail a capture that has already
    succeeded. Once the vault retires, a swallowed failure would mean the hook
    reporting success while NOTHING holds the session, so it RAISES instead and
    the caller reports it.

    The session is not lost either way: `~/.claude/projects` still has it,
    sources being read-only (F9), so a loud failure is one `ccw sweep` from
    recovery. A silent one is equally recoverable and nobody ever goes looking,
    which is the difference that matters.
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
        if not config.keep_objects:
            raise
        return
    _archive_project_file(config, conn, project_id)


def _archive_project_file(
    config: Config, conn: sqlite3.Connection, project_id: int
) -> None:
    """Refresh this project's `project.json` beside its folder (ticket 28.21).

    WHY IT LIVES HERE. `archive.write_project_files` had exactly one caller, the
    `ccw archive` verb, so every project folder created by capture or import
    afterwards had no sidecar. Measured on the real archive 2026-08-05: a rebuild
    recovered 114 of 4,913 aliases, 2.3%. The label survives regardless because
    it is the folder name; `project_alias` does not, and it is what stops a
    renamed project splitting in two on the next capture. Writing it on the path
    that CREATES the folder is the fix; re-running the bulk verb is a mop.

    BEST EFFORT, DELIBERATELY, AND UNLIKE THE PAYLOAD WRITE ABOVE. That one
    raises when `keep_objects` is false, because then nothing else holds the
    session. A sidecar is an INDEX AID: the session is safe without it and the
    next bulk run or the next capture rewrites it, so failing a capture that has
    already stored its payload would be the wrong trade (DESIGN 12). Separate
    try, never re-raised.
    """
    if config.archive_root is None:
        return
    try:
        from cc_warehouse import archive

        record = archive.project_record(conn, project_id)
        if record is not None:
            archive.write_project_file(config.archive_root, record.label, record.aliases)
    except Exception:  # noqa: BLE001 - see the docstring: never costs a capture
        return


def _label_of(conn: sqlite3.Connection, project_id: int) -> str:
    """This project's archive label, or the unlabeled fallback. One reader rather
    than the three copies of this two-line query the module had grown (R9)."""
    row = conn.execute("SELECT label FROM project WHERE id = ?", (project_id,)).fetchone()
    return str(row[0]) if row else "_unlabeled"


def _archive_subagents_of(
    config: Config,
    conn: sqlite3.Connection,
    project_id: int,
    transcript_path: Path,
    parsed: parser.ParsedSession,
) -> None:
    """Bring this session's sub-agent transcripts with it (ticket 21d).

    Claude Code writes them to `<session-uuid>/subagents/agent-*.jsonl` beside
    the transcript. A session captured without them leaves work behind in
    `~/.claude`, and `~/.claude` is being cleared - so "the sweep will get it
    later" is not a plan, it is a hope.

    Ordering is free here, unlike in the sweep: the parent's own folder was
    written moments ago by _archive_source, so every sub-agent nests rather than
    orphaning.

    Never fatal while a fallback exists, for the same reason the parent's own
    archive write is not: the session is already stored and DESIGN 12 forbids the
    capture path turning a stored session into a reported failure.
    """
    if config.archive_root is None or not config.archive_subagents:
        return
    directory = sidecars.locate(transcript_path, parsed.session_uuid)
    if directory is None:
        return
    from cc_warehouse import archive

    subagents = directory / archive.SUBAGENTS_DIR
    if not subagents.is_dir():
        return
    label = _label_of(conn, project_id)
    # RECURSIVE since ticket 38. Claude Code also writes Workflow-tool sub-agents
    # at `subagents/workflows/wf_<id>/agent-*.jsonl` - 432 files, 33 MB, 211
    # distinct transcripts - and a non-recursive glob reached none of them. The
    # daily sweep's os.walk did, so all 211 are already in the archive: a hook-path
    # gap with a working net. Fixed anyway, because a net is not a plan.
    for child in sorted(subagents.rglob("*.jsonl")):
        try:
            payload = child.read_bytes()
            if not archive.is_subagent(payload):
                continue
            meta_path = child.parent / f"{child.stem}.meta.json"
            archive.write_subagent(
                config.archive_root,
                label,
                payload,
                config.archive_timezone,
                meta=meta_path.read_bytes() if meta_path.is_file() else None,
                companions=forked_skill_companions(child),
            )
        except Exception:  # noqa: BLE001, PERF203 - one bad sub-agent never costs the capture
            continue


def forked_skill_companions(transcript: Path) -> tuple[tuple[str, bytes], ...]:
    """The `.forked-skill.json` / `.forked-skill.marker.json` files beside one
    sub-agent transcript (ticket 38; 10 of each in the live tree, copied by
    nothing until now).

    Same argument as `meta.json`: they are the only record of what the agent was
    set up to be. An unreadable one is skipped rather than raised - a companion is
    an extra, and losing it must not cost the transcript itself (R5).
    """
    out: list[tuple[str, bytes]] = []
    for suffix in (".forked-skill.json", ".forked-skill.marker.json"):
        path = transcript.parent / f"{transcript.stem}{suffix}"
        try:
            out.append((path.name, path.read_bytes()))
        except OSError:  # noqa: PERF203 - an extra never costs the transcript
            continue
    return tuple(out)


def _archive_sidecars_of(
    config: Config,
    conn: sqlite3.Connection,
    project_id: int,
    transcript_path: Path,
    parsed: parser.ParsedSession,
) -> tuple[str, ...]:
    """Bring this session's OTHER sidecar folders with it: `tool-results/` and
    `workflows/` (ticket 38). Returns the relative paths that were refused.

    The twin of `_archive_subagents_of`, with one deliberate difference: EVERY
    refusal and every per-file error is recorded. A sub-agent has a folder of its
    own and a `SubagentResult` a caller can read; a tool result has neither, and
    silence about it is precisely what let this whole class of data sit
    uncollected for four months.

    Ordering is free here, as it is for sub-agents: the parent's own folder was
    written moments ago by `_archive_source`, so there is always somewhere for
    these to land. A None parent means that write failed, and the conservative
    branch is to leave the files where they are (R5) rather than invent a home.

    Never fatal (DESIGN 12): the session is already stored, and a copier must not
    turn that into a reported failure.
    """
    if config.archive_root is None or not config.archive_tool_results:
        return ()
    directory = sidecars.locate(transcript_path, parsed.session_uuid)
    if directory is None:
        return ()
    from cc_warehouse import archive

    label = _label_of(conn, project_id)
    parent = archive.session_folder(
        config.archive_root, label, parsed.session_uuid, config.archive_timezone
    )
    if parent is None:
        return ()
    refused: list[str] = []
    for name in sorted(sidecars.SESSION_SIDECARS - {archive.SUBAGENTS_DIR}):
        source = directory / name
        if not source.is_dir():
            continue
        copied = archive.copy_companion_dir(parent, name, source)
        refused.extend(f"{name}/{item}" for item in copied.refused)
        for item in copied.refused:
            log_sidecar_trouble(config, parsed, "refused", name, item)
        for item in copied.errors:
            log_sidecar_trouble(config, parsed, "error", name, item)
    return tuple(refused)


def log_sidecar_trouble(
    config: Config, parsed: parser.ParsedSession, status: str, sidecar: str, detail: str
) -> None:
    """One audit line per refused or unreadable sidecar file (F6, R10).

    `notify.append_log` rather than `notify.report`: this is a durable local
    record, not an event worth a webhook or a spoken sentence. The attention sink
    is a separate decision made by `announce_sidecar_anomaly`.

    PUBLIC because the sweep's third pass needs the SAME line (R9). It did not
    have one until 2026-09-08: the hook path logged every refusal and the sweep
    path logged none, so the first real refusal on the operator's machine showed
    up in `sidecars.json` and in `ccw doctor` and left the audit log empty. The
    two records answer different questions and a reader needs both - the notice
    says what is true NOW for one session, the log says what HAPPENED and when,
    across all of them, and only the log can be counted afterwards.
    """
    verb = "refused" if status == "refused" else "could not read"
    notify.append_log(
        config,
        {
            "at": datetime.now(UTC).isoformat(),
            "status": status,
            "session": (parsed.session_uuid or "")[:8] or None,
            "project": None,
            "message": f"{verb} sidecar {sidecar}/{detail}",
            "elapsed_ms": None,
        },
    )


def _note_unknown_siblings(
    config: Config,
    conn: sqlite3.Connection,
    project_id: int,
    transcript_path: Path,
    parsed: parser.ParsedSession,
    refused: Sequence[str],
) -> None:
    """Record anything beside this transcript that nothing copied, and say so once.

    THE DEDUP IS THE NOTICE COMPARE, not a timer and not a counter.
    `write_sidecar_notice` returns True only when the file's bytes actually
    changed, so a machine with a permanent anomaly logs it on the run that finds
    it and then stays quiet. That is the ticket 24.7 lesson, learned here the hard
    way: a threshold on a figure that sits permanently non-zero on a healthy
    install printed an ALERT every single session.

    A notice that changed to EMPTY is not announced. The anomaly going away is
    good news, and good news does not need an interruption.
    """
    if config.archive_root is None:
        return
    from cc_warehouse import archive

    label = _label_of(conn, project_id)
    parent = archive.session_folder(
        config.archive_root, label, parsed.session_uuid, config.archive_timezone
    )
    if parent is None:
        return
    scan = sidecars.scan(transcript_path, parsed.session_uuid)
    if not archive.write_sidecar_notice(parent, scan, refused):
        return
    announce_sidecar_anomaly(config, parsed.session_uuid, transcript_path.name, scan, refused)


def announce_sidecar_anomaly(
    config: Config,
    session_uuid: str | None,
    fallback: str,
    scan: sidecars.SidecarScan,
    refused: Sequence[str] = (),
) -> None:
    """Say once, through every sink, that data beside a transcript is not in the archive.

    Ruling (e). The audit log is the durable half; the desktop notification and
    the spoken sentence are the half that actually reaches a human, because the
    `sidecars` doctor line is non-blocking by design and therefore never paints a
    banner. Shared by the hook path and the sweep's third pass rather than written
    twice (R9): they announce the same fact and must word it the same way.

    TWO KINDS OF ANOMALY, and they get DIFFERENT SENTENCES because they need
    different actions. An unknown sibling means nobody has written a copier yet.
    A refusal means the copier exists and two different files claimed one name, so
    "add a copier" would be wrong advice.

    REFUSALS WERE NOT EXPECTED TO HAPPEN AT ALL, and that is why they are here.
    The plan reasoned that a persisted-output filename is per invocation, so a
    natural collision should be impossible. The first acceptance sweep on the real
    corpus produced one inside twenty minutes: a live session's file held 38,537
    bytes when it was copied and 38,519 DIFFERENT bytes under the same name on the
    next sweep - not a prefix, so not a truncated write. Data that exists and that
    the archive is declining to hold is exactly what ruling (e) exists to surface.

    THE CALLER OWNS THE DEDUP. Both call sites reach here only when the session's
    notice file CHANGED, so this fires at most once per new anomaly and can never
    become a daily nag (the ticket 24.7 lesson).

    Every sink is best-effort and none may raise into capture (DESIGN 12).
    """
    short = (session_uuid or "")[:8]
    where = short or fallback
    parts: list[str] = []
    if scan.has_anomaly:
        names = ", ".join((*scan.unknown, *scan.unknown_inside_subagents))
        parts.append(f"unarchived sibling(s) beside {where}: {names}. Add a copier in sidecars.py.")
    if refused:
        parts.append(
            f"sidecar(s) beside {where} refused, a different file already holds that name:"
            f" {', '.join(sorted(refused))}."
        )
    if not parts:
        return
    sentence = "cc-warehouse: " + " ".join(parts)
    try:
        if scan.has_anomaly:
            # Only the UNKNOWN-sibling half logs here. A refusal already has its
            # own `refused` line from `log_sidecar_trouble`, and logging it twice
            # would make the audit log disagree with itself about how many
            # happened.
            names = ", ".join((*scan.unknown, *scan.unknown_inside_subagents))
            notify.append_log(
                config,
                {
                    "at": datetime.now(UTC).isoformat(),
                    "status": "unarchived-sibling",
                    "session": short or None,
                    "project": None,
                    "message": f"unarchived sibling(s) beside {where}: {names}",
                    "elapsed_ms": None,
                },
            )
        notify.alert(config, "cc-warehouse", sentence)
        notify.speak(config, sentence)
    except Exception:  # noqa: BLE001 - a signal never fails a capture (DESIGN 12)
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
