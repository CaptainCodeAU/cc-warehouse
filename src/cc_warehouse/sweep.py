"""ccw sweep: capture transcripts the hook missed and adopt orphan store objects.

Slice 5. The sweep carries ZERO capture logic of its own (R9/F8): it walks the source
tree and hands each transcript to the ONE store-and-catalog routine,
capture.capture_transcript, exactly as the hook does. A locks/sweep O_EXCL lock keeps a
sweep from racing a second sweep (R14/F3); capture's own hash-idempotence (F1/F3) makes
racing the hook harmless. Item failures are reported and the batch continues past them
(R5/R10); sources stay read-only (F9). See DESIGN sections 4 and 13.
"""

import os
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cc_warehouse import capture, catalog, notify, parser, registry, store
from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport, ItemOutcome

# DESIGN sections 4/13: one lock per sweep, O_EXCL, stale after a recorded PID dies.
_SWEEP_LOCK = "sweep"

# A live lock holder is reported as a named item so the CLI end report and exit code
# name the refusal (R10); the item is the lock's path token.
_LOCK_HELD_ITEM = "locks/sweep"

# The lock-held outcome carries this DISTINCT action (not "error") so the CLI can refuse
# with a distinct line and a non-zero exit WITHOUT counting a no-op that processed zero
# items as a batch item. Public because the CLI end report keys on it (DESIGN section 4).
LOCK_HELD_ACTION = "lock-held"

# SPEC section 8: agent-* transcripts are skipped by the default sweep (the store still
# accepts them via the hook; a config opt-in to include them lands with slice 13).
_AGENT_PREFIX = "agent-"

# Claude Code transcripts and v1 store objects share this suffix (store.put default ext).
_JSONL_SUFFIX = ".jsonl"


def _default_source() -> Path:
    """Where Claude Code writes SessionEnd transcripts (DESIGN section 4)."""
    return Path.home() / ".claude" / "projects"


def _walk_source(
    walk_root: Path, *, skip_agents: bool = True, limit: int | None = None
) -> tuple[list[Path], list[ItemOutcome]]:
    """The jsonl transcripts under walk_root plus a NAMED error item per directory that
    could not be listed; both sorted for determinism, agent-* skipped.

    Walks with os.walk(onerror=...) rather than Path.rglob because rglob SILENTLY swallows
    a PermissionError on a subdirectory, dropping an unreadable source tree with no report
    (an F7 under-capture that still exits 0). The onerror callback turns each directory
    OSError into a reported item (its .filename is the unreadable path) so the CLI names it
    and the exit code is non-zero, while the walk continues for the readable siblings
    (R5/R10). A missing source directory yields an empty walk rather than a crash (R5).

    `limit` (ticket 28.3, `ccw sweep --limit N`) caps the TRANSCRIPT list only, taken
    after the deterministic sort so a run is reproducible; the error list is never
    truncated, since a directory ccw could not list is worth reporting regardless of how
    small a slice was asked for. It is the walk-level knob for exercising a slice of a
    large source tree, not a promise about how many end up STORED - `already_known`
    skips and window filtering still apply to whatever this returns."""
    if not walk_root.is_dir():
        return [], []
    errors: list[ItemOutcome] = []

    def _on_error(exc: OSError) -> None:
        name = exc.filename if isinstance(exc.filename, str) else str(walk_root)
        errors.append(
            ItemOutcome(name, "error", f"unreadable source directory: {exc.strerror or exc}")
        )

    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(walk_root, onerror=_on_error):
        base = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(_JSONL_SUFFIX):
                continue
            if skip_agents and filename.startswith(_AGENT_PREFIX):
                continue
            path = base / filename
            if not path.is_file():
                continue
            found.append(path)
    transcripts = sorted(found)
    if limit is not None:
        transcripts = transcripts[:limit]
    return transcripts, sorted(errors, key=lambda outcome: outcome.item)


def _cataloged_hashes(root: Path) -> frozenset[str]:
    """Session hashes already in the catalog: one SELECT on the read path (R6/F5)."""
    conn = catalog.open_catalog(root)
    try:
        rows = cast(
            list[tuple[object, ...]],
            conn.execute("SELECT hash FROM session").fetchall(),
        )
    finally:
        conn.close()
    return frozenset(cast(str, row[0]) for row in rows)


def _orphan_object_paths(root: Path, cataloged: frozenset[str]) -> list[Path]:
    """Store objects whose content hash is not yet cataloged (DESIGN section 13).

    Object addresses are content-named (objects/<hh>/<sha256>.jsonl), so each object's
    hash is read from its path and cross-checked against `cataloged` without opening the
    object; only the orphans are handed to capture_transcript, which reads and re-adopts
    them (safe and idempotent because the hash names the object, F1/F3)."""
    objects = root / "objects"
    if not objects.is_dir():
        return []
    orphans: list[Path] = []
    for path in sorted(objects.rglob("*")):
        if not path.is_file():
            continue
        digest = path.name.split(".", 1)[0]
        if not store.is_sha256_hex(digest):
            continue
        if path.parent.parent != objects or path.parent.name != digest[:2]:
            continue
        if digest in cataloged:
            continue
        orphans.append(path)
    return orphans


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def _content_hash(path: Path) -> str | None:
    """The candidate's sha256, or None on an unreadable file.

    None is treated as "unknown", never as "already known" (ticket 31.3): a
    read failure here still falls through to the ordinary path, which reports
    it as an `error` item with a real message (R5/R10) rather than silently
    dropping it as a false skip."""
    try:
        return store.sha256_hex(path.read_bytes())
    except OSError:
        return None


def _record_sweep_unchanged(root: Path, count: int, elapsed_ms: int) -> None:
    """One aggregate `capture_event` row for a whole run's worth of
    already-known items, replacing the ~16,400/day one-row-per-item cost
    measured 2026-08-20 (ticket 31.3). `action` is deliberately NOT
    `skipped_unchanged` - that name means "this one payload was unchanged";
    this row names none, so `session_hash` is NULL and it gets its own
    action string, never miscountable as one session's own event (R10/F6).
    Keeps `ccw doctor`'s `fired` check (MAX(at) FROM capture_event) moving on
    a day nothing new is stored."""
    conn = catalog.open_catalog(root)
    try:
        now_iso = datetime.now(UTC).isoformat()
        catalog.record_event(
            conn, None, "sweep-unchanged", elapsed_ms, f"{count} unchanged", now_iso
        )
    finally:
        conn.close()


def _is_subagent_file(path: Path) -> bool:
    """Cheap pre-read check used only for ORDERING, never for identity.

    Identity is decided from content by archive.is_subagent (F4). This just
    decides which pass a file goes in, and being wrong here costs a pass, not a
    misfiling: the second pass re-checks properly and falls back.
    """
    from cc_warehouse import archive

    try:
        return archive.is_subagent(path.read_bytes())
    except OSError:
        return False


def _project_dir_of_subagent(path: Path) -> Path:
    """The project directory a sub-agent transcript belongs to.

    Walks UP to the `subagents/` directory rather than counting a fixed number of
    levels, because Claude Code writes two depths: `subagents/agent-*.jsonl` and
    `subagents/workflows/wf_<id>/agent-*.jsonl`. The fixed count was right for the
    first and wrong for the second, and the second is 211 real transcripts.
    """
    from cc_warehouse import archive

    for ancestor in path.parents:
        if ancestor.name == archive.SUBAGENTS_DIR:
            return ancestor.parent.parent
    return path.parent.parent.parent


def _archive_subagent(config: Config, path: Path) -> ItemOutcome | None:
    """A sub-agent transcript goes to its session's folder, not to the store.

    Sub-agents are NOT sessions (ticket 21a): they carry their PARENT'S
    sessionId, so the ordinary capture path would file one under the parent's
    name and let replace-if-larger overwrite the parent's transcript. They also
    get no catalog row - the catalog indexes sessions, and a sub-agent is part
    of one rather than one of its own.

    Returns None when this is not a sub-agent, so the caller falls through to
    the ordinary path.
    """
    from cc_warehouse import archive

    try:
        data = path.read_bytes()
    except OSError as exc:
        return ItemOutcome(path.name, "error", f"unreadable: {exc}")
    if not archive.is_subagent(data):
        return None
    if config.archive_root is None:
        return ItemOutcome(path.name, "skipped", "sub-agent, but no archive_root is set")
    meta_path = path.parent / f"{path.stem}.meta.json"
    meta = meta_path.read_bytes() if meta_path.is_file() else None
    # The project dir is two levels above `subagents/`; deriving from the
    # sub-agent's own parent would produce a label made of the session uuid.
    #
    # FOUND BY `subagents/` ITSELF (ticket 38): a Workflow-tool sub-agent sits at
    # `subagents/workflows/wf_<id>/agent-*.jsonl`, two levels deeper, so a fixed
    # `parent.parent.parent` computed a label from `wf_<id>` for 211 of them. The
    # catalog lookup below usually rescued it; that is a net, not a plan.
    project_dir = _project_dir_of_subagent(path)
    label = registry.derive_label(str(project_dir))
    try:
        conn = catalog.open_catalog(config.root)
        try:
            parent = archive.parent_uuid_of(data)
            row = conn.execute(
                "SELECT p.label FROM session s JOIN project p ON p.id = s.project_id"
                " WHERE s.session_uuid = ? LIMIT 1",
                (parent,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            label = str(row[0])
        result = archive.write_subagent(
            config.archive_root,
            label,
            data,
            config.archive_timezone,
            meta=meta,
            companions=capture.forked_skill_companions(path),
        )
    except Exception as exc:  # noqa: BLE001 - R10: name it and carry on
        return ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}")
    if result.unchanged:
        # Ticket 37: sub-agents never enter the hash pre-filter (no catalog
        # row; the follow-up is in that ticket), so every sweep reaches
        # write_subagent for every one of them. An unchanged one must read as
        # unchanged, not as archived (F6).
        return ItemOutcome(path.name, "skipped_unchanged", str(result.directory))
    if result.refused:
        # Sub-agents have no manifest.json to record a refusal in, so the
        # sweep report is the only place it can be seen (F6).
        why = "smaller than archived" if result.refused_smaller else "same size, different bytes"
        return ItemOutcome(path.name, "refused-subagent", f"{why}: {result.directory}")
    action = "archived-subagent-orphaned" if result.orphaned else "archived-subagent"
    return ItemOutcome(path.name, action, str(result.directory))


# The outcomes that mean "the archive grew, even though nothing was stored".
# `cli.py` reads this to decide whether the post-sweep build has to run: a
# back-fill stores 0 sessions, and without it the manifest would never list the
# files that were just copied.
SIDECAR_ARCHIVED_ACTIONS = frozenset({"archived-sidecars", "archived-stranded-sidecars"})


def _project_dirs(walk_root: Path) -> list[Path]:
    """The project directories directly under the source root.

    Derived from the ROOT rather than from `{p.parent for p in transcripts}`,
    which is the tempting shortcut and is wrong for exactly the case the stranded
    pass exists for: a project dir holding sidecar dirs and no transcript at all
    contributes no parent to that set, so it would be invisible to the one pass
    that was supposed to find it.
    """
    try:
        return sorted(p for p in walk_root.iterdir() if p.is_dir())
    except OSError:
        return []


def _sidecar_dir_names(project_dir: Path) -> frozenset[str]:
    """The names of the `<uuid>/` dirs in one project dir, listed once.

    THE CHEAP PRE-FILTER for pass three, and it has to be cheap: the pass runs
    for every one of ~24,000 source transcripts on a daily sweep, and only ~1,196
    of them have a sidecar dir at all. Reading and parsing every transcript to ask
    "what is your session uuid" would be 4.2 GB of I/O to answer a question a
    single scandir per project dir answers for free.

    A NAME MATCH IS A FILTER, NEVER AN IDENTITY (F4, and ruling (c) says so in as
    many words). A hit here only means "open this one file"; what actually decides
    where a sidecar lands is the uuid parsed from the transcript's own content.
    """
    try:
        return frozenset(p.name for p in project_dir.iterdir() if p.is_dir())
    except OSError:
        return frozenset()


def _sidecar_candidate(path: Path, names: frozenset[str]) -> bool:
    """Whether this transcript is worth opening for the sidecar pass.

    Two spellings, because Claude Code writes both. `<uuid>.jsonl` gives the stem;
    `<uuid>.orphaned-<n>-<hash>.jsonl` (one exists live) gives the first
    dot-separated component. Neither is used to decide identity.
    """
    return path.stem in names or path.name.split(".", 1)[0] in names


def _archived_session_folders(archive_root: Path) -> dict[str, Path]:
    """Every archived session's uuid mapped to its folder.

    One two-level listing, the same shape `doctor._overdue` already pays for. It
    exists for the stranded pass: "no transcript BESIDE this dir" is NOT the same
    question as "no transcript anywhere", and 4 of the 39 real stranded dirs have
    a session folder in the archive already. Filing those under `_not-sessions/`
    would put a known session's data in the drawer reserved for unknowns.
    """
    from cc_warehouse import build

    out: dict[str, Path] = {}
    try:
        label_dirs = sorted(p for p in archive_root.iterdir() if p.is_dir())
    except OSError:
        return out
    for label_dir in label_dirs:
        if label_dir.name in build.RESERVED_LABELS:
            continue
        try:
            folders = sorted(p for p in label_dir.iterdir() if p.is_dir())
        except OSError:  # noqa: PERF203 - one unreadable label never costs the rest
            continue
        for folder in folders:
            _stamp, _sep, tail = folder.name.partition("_")
            if tail:
                out.setdefault(tail, folder)
    return out


def _log_item_failure(config: Config, path: Path, exc: Exception) -> None:
    """Best-effort diagnostic line for a sweep item that failed capture, reviewable
    later next to the hook path's own stage-failure lines (notify.append_log,
    DESIGN R2's sanctioned exception; the SAME log, `logs/capture.jsonl`, not a new
    write path -- see capture.py's `_log_stage_failure`, the twin this mirrors)."""
    try:
        notify.append_log(
            config,
            {
                "at": datetime.now(UTC).isoformat(),
                "status": "error",
                "session": None,
                "project": None,
                "message": f"sweep item {path.name} failed: {type(exc).__name__}: {exc}",
                "elapsed_ms": None,
            },
        )
    except Exception:
        return


def _capture_item(config: Config, path: Path) -> ItemOutcome:
    """Hand one path to the shared capture routine (R9) and record its outcome.

    capture_transcript itself only guarantees a graceful `error` result for one
    case (an unreadable file) -- its own docstring says any DEEPER failure (e.g.
    transient catalog lock contention that exhausts its retry budget) propagates
    to the caller's never-raise boundary. The hook path (`_run_hook`) has one;
    this loop did not (ticket 31.4's other flagged gap, 2026-08-24): one such
    failure used to abort the ENTIRE sweep batch mid-run, silently, with every
    session still queued simply never attempted. Wrapping it here, matching
    `_archive_subagent`'s own error handling a few lines above, closes that: name
    the item, log it for later review, and let the batch continue (R5/R10/F6)."""
    try:
        result = capture.capture_transcript(config, path, session_id=None, cwd=None)
    except Exception as exc:  # noqa: BLE001 - R10: name it and carry on
        _log_item_failure(config, path, exc)
        return ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}")
    return ItemOutcome(path.name, result.action, result.detail)


def _archive_sidecars(config: Config, path: Path) -> ItemOutcome | None:
    """Pass three for ONE transcript: mirror its sidecar dirs into its folder.

    Returns None when there is nothing to do, so the caller records nothing rather
    than filling a 24,000-item report with no-ops.

    THE LABEL COMES FROM THE CATALOG, not from the sidecar's own path. A stranded
    dir's transcript can live under a DIFFERENT project dir than the sidecar (2 do
    in the live tree), and deriving a label from where the files sit would compute
    an archive folder that does not exist. When no folder is found the files are
    LEFT WHERE THEY ARE and reported, never given an invented home (R5, F4).
    """
    from cc_warehouse import archive, sidecars

    if config.archive_root is None or not config.archive_tool_results:
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ItemOutcome(path.name, "error", f"unreadable: {exc}")
    parsed = parser.parse_session(data)
    directory = sidecars.locate(path, parsed.session_uuid)
    if directory is None:
        return None
    wanted = sorted(sidecars.SESSION_SIDECARS - {archive.SUBAGENTS_DIR})
    present = [name for name in wanted if (directory / name).is_dir()]
    scan = sidecars.scan(path, parsed.session_uuid)
    # NO EARLY RETURN when there is nothing to copy and no anomaly, and the
    # missing one was a real bug: a session whose anomaly has been FIXED has
    # nothing to copy and nothing to flag, and skipping it here left its
    # `sidecars.json` claiming the anomaly forever. `write_sidecar_notice` is the
    # one that decides whether to write, and it already knows to leave a clean
    # session with no notice at all.
    label = registry.derive_label(str(path.parent))
    try:
        conn = catalog.open_catalog(config.root)
        try:
            row = conn.execute(
                "SELECT p.label FROM session s JOIN project p ON p.id = s.project_id"
                " WHERE s.session_uuid = ? LIMIT 1",
                (parsed.session_uuid,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            label = str(row[0])
        folder = archive.session_folder(
            config.archive_root, label, parsed.session_uuid, config.archive_timezone
        )
        if folder is None:
            # Reported only when there was something to do. A session with an
            # empty sidecar dir and no archive folder is not a problem worth a
            # line in a 24,000-item report.
            if not present and not scan.has_anomaly:
                return None
            return ItemOutcome(path.name, "skipped-sidecars-no-parent", str(directory))
        refused: list[str] = []
        written = 0
        for name in present:
            copied = archive.copy_sidecar_dir(folder, name, directory / name)
            written += copied.written
            refused.extend(f"{name}/{item}" for item in copied.refused)
        changed = archive.write_sidecar_notice(folder, scan, refused)
    except Exception as exc:  # noqa: BLE001 - R10: name it and carry on
        return ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}")

    if changed and scan.has_anomaly:
        _log_sidecar_anomaly(config, parsed.session_uuid, path, scan)
    if refused:
        return ItemOutcome(path.name, "refused-sidecar", ", ".join(refused))
    if written:
        return ItemOutcome(path.name, "archived-sidecars", f"{written} file(s) -> {folder}")
    if scan.has_anomaly:
        return ItemOutcome(path.name, "sidecar-anomaly", ", ".join(scan.unknown))
    return None


def _log_sidecar_anomaly(
    config: Config, session_uuid: str | None, path: Path, scan: "object"
) -> None:
    """Announce a new unknown sibling the sweep found, through capture's own
    announcer rather than a second copy of the same three sinks (R9).

    Guarded by the notice having actually CHANGED, so the daily job announces an
    anomaly once and then stays quiet about it forever after - the ticket 24.7
    lesson, which this project learned by printing ALERT every session on a
    perfectly healthy install."""
    from cc_warehouse import sidecars

    assert isinstance(scan, sidecars.SidecarScan)
    capture.announce_unarchived_siblings(config, session_uuid, path.name, scan)


def _archive_stranded(config: Config, walk_root: Path) -> list[ItemOutcome]:
    """Sidecar dirs with no transcript beside them (ruling (d)).

    Two destinations, and telling them apart is the refinement execution forced.
    A dir whose name matches a session the archive already holds goes into THAT
    session's folder - it is not homeless, its transcript simply moved. Only a dir
    the archive has never heard of goes under `_not-sessions/stranded-sidecars/`,
    where its name is recorded as a label and never trusted as identity (F4).
    """
    from cc_warehouse import archive, sidecars

    if config.archive_root is None or not config.archive_tool_results:
        return []
    known = _archived_session_folders(config.archive_root)
    wanted = sorted(sidecars.SESSION_SIDECARS - {archive.SUBAGENTS_DIR})
    outcomes: list[ItemOutcome] = []
    for project_dir in _project_dirs(walk_root):
        for stranded in sidecars.stranded_dirs(project_dir):
            try:
                folder = known.get(stranded.name)
                if folder is not None:
                    written = sum(
                        archive.copy_sidecar_dir(folder, name, stranded / name).written
                        for name in wanted
                        if (stranded / name).is_dir()
                    )
                    if written:
                        outcomes.append(
                            ItemOutcome(
                                stranded.name, "archived-sidecars", f"{written} file(s) -> {folder}"
                            )
                        )
                    continue
                copied = archive.write_stranded_sidecars(config.archive_root, stranded)
                if copied.written:
                    outcomes.append(
                        ItemOutcome(
                            stranded.name,
                            "archived-stranded-sidecars",
                            f"{copied.written} file(s)",
                        )
                    )
            except Exception as exc:  # noqa: BLE001, PERF203 - R10: name it and carry on
                outcomes.append(ItemOutcome(stranded.name, "error", f"{type(exc).__name__}: {exc}"))
    return outcomes


def _plan_sidecars(config: Config, walk_root: Path, wanted: "list[Path]") -> list[ItemOutcome]:
    """What pass three WOULD do, writing nothing (`--dry-run`).

    Reads directory entries only and never opens the catalog, so it cannot
    materialise the warehouse it is describing - the property `plan()`'s own
    docstring exists to protect.
    """
    from cc_warehouse import sidecars

    if config.archive_root is None or not config.archive_tool_results:
        return []
    outcomes: list[ItemOutcome] = []
    names_by_dir: dict[Path, frozenset[str]] = {}
    for path in wanted:
        names = names_by_dir.setdefault(path.parent, _sidecar_dir_names(path.parent))
        if not _sidecar_candidate(path, names):
            continue
        directory = path.parent / (path.stem if path.stem in names else path.name.split(".", 1)[0])
        present = [
            name
            for name in sorted(sidecars.SESSION_SIDECARS - {"subagents"})
            if (directory / name).is_dir()
        ]
        if present:
            outcomes.append(
                ItemOutcome(path.name, "would-archive-sidecars", ", ".join(present))
            )
    for project_dir in _project_dirs(walk_root):
        outcomes.extend(
            ItemOutcome(d.name, "would-archive-sidecars", "no transcript beside this dir")
            for d in sidecars.stranded_dirs(project_dir)
        )
    return outcomes


def _in_window(path: Path, keep: "Callable[[str | None], bool] | None") -> bool:
    """Whether this transcript's R12 FIRST timestamp falls inside the window.

    Read from the PAYLOAD, never from the file's mtime (R12): a copied or
    restored transcript keeps its recorded time and would otherwise sweep into
    the wrong window. An unreadable or timestamp-less file is left OUT of a
    bounded window and swept by the next unwindowed run, because narrowing an
    import must never be the thing that loses a session.
    """
    if keep is None:
        return True
    try:
        return keep(parser.parse_session(path.read_bytes()).first_ts)
    except OSError:
        return False


def source_transcripts(walk_root: Path | None = None) -> tuple[list[Path], list[Path]]:
    """(session transcripts, sub-agent transcripts) under the source tree.

    Filtering on the `agent-` prefix is legitimate HERE AND ONLY HERE. The F4
    fence (test_no_module_identifies_a_subagent_by_filename) exempts this module
    by name, on the stated ground that it walks a source tree: "sweep may FILTER
    on the prefix, but nothing may DECIDE what a payload is from its name."

    Callers that need the split ask for it here rather than re-deriving it, so
    the prefix lives in one file (R9). This is a CHEAP name-based split for
    counting and ordering; identity is still decided from content by
    archive.is_subagent, which is what protects the parent transcript from being
    overwritten (ticket 21a).
    """
    root = walk_root if walk_root is not None else _default_source()
    found, _errors = _walk_source(root, skip_agents=False)
    sessions = [p for p in found if not p.name.startswith(_AGENT_PREFIX)]
    subagents = [p for p in found if p.name.startswith(_AGENT_PREFIX)]
    return sessions, subagents


def cataloged_hashes_readonly(root: Path) -> frozenset[str]:
    """Session hashes already captured, WITHOUT creating anything (ticket 23).

    PUBLIC since ticket 25.4: `ccw import --dry-run` needs the same read-only
    answer, and a second implementation would be a second chance to reintroduce
    the create-on-read defect this function exists to avoid (R9).

    `_cataloged_hashes` goes through `catalog.open_catalog`, whose docstring says
    "creating if needed" - which is right for a real sweep and fatal for a
    rehearsal, because it would leave a database behind on a warehouse that does
    not exist yet. An absent catalog means nothing has been captured, so every
    candidate is new.
    """
    path = root / "catalog.sqlite"
    if not path.is_file():
        return frozenset()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return frozenset()
    try:
        rows = cast(
            list[tuple[object, ...]], conn.execute("SELECT hash FROM session").fetchall()
        )
    except sqlite3.Error:
        return frozenset()
    finally:
        conn.close()
    return frozenset(cast(str, row[0]) for row in rows)


def plan(
    config: Config,
    source: Path | None = None,
    window: "Callable[[str | None], bool] | None" = None,
    limit: int | None = None,
) -> BatchReport:
    """What a real sweep WOULD do, writing nothing at all (`--dry-run`).

    THE PROPERTY, and it is the whole reason this is a separate function rather
    than a flag threaded through `sweep`: a rehearsal must not touch the
    warehouse. Two paths in the real sweep would, and neither is obvious from
    reading it:

        store.acquire_lock       does lock.parent.mkdir(parents=True), so taking
                                 the sweep lock CREATES <root>/locks/
        catalog.open_catalog     creates catalog.sqlite when absent

    So this takes no lock and opens the catalog read-only. Not locking is safe
    because nothing is mutated; the cost is that a concurrent real sweep could
    make the report stale, which is the honest trade for a report that cannot
    itself change the thing it describes.

    Each candidate is named, because a count alone cannot be checked against the
    run that follows it. Outcomes carry `would-store` or `would-skip` rather than
    `stored`, so a plan is never mistaken for a result in the same report shape.
    """
    walk_root = source if source is not None else _default_source()
    transcripts, outcomes = _walk_source(
        walk_root, skip_agents=not config.archive_subagents, limit=limit
    )
    already = cataloged_hashes_readonly(config.root)
    wanted = [p for p in transcripts if _in_window(p, window)]
    for path in wanted:
        try:
            digest = store.sha256_hex(path.read_bytes())
        except OSError as exc:
            outcomes.append(ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}"))
            continue
        action = "would-skip" if digest in already else "would-store"
        outcomes.append(ItemOutcome(path.name, action, str(path)))
    outcomes.extend(_plan_sidecars(config, walk_root, wanted))
    outcomes.extend(
        ItemOutcome(path.name, "would-store", str(path))
        for path in _orphan_object_paths(config.root, already)
    )
    return BatchReport(tuple(outcomes))


def sweep(
    config: Config,
    source: Path | None = None,
    window: "Callable[[str | None], bool] | None" = None,
    limit: int | None = None,
) -> BatchReport:
    """Capture whatever the hook missed, then adopt orphan store objects (slice 5).

    Walks `source` (default ~/.claude/projects), skipping agent-* transcripts, and hands
    each file to capture.capture_transcript under a locks/sweep O_EXCL lock; item failures
    (including a source subdirectory that cannot be listed) are reported and the batch
    continues (R5/R10). A live lock holder makes the sweep a no-op that reports a lock-held
    refusal and captures nothing (R14/F3). After the source walk, store objects with no
    catalog row are re-adopted through the same routine (DESIGN section 13). Sources are
    read-only throughout (F9).

    A `window` narrows the import to sessions whose R12 first timestamp falls
    inside it (DESIGN 15 entry, block 5). Safe on sweep precisely because import
    is ADDITIVE and re-runnable: narrowing loses nothing, since a later
    unwindowed sweep still picks up whatever was skipped. That is the property
    `ccw build` lacks, which is why block 5 refuses the pair there.

    CHEAP PRE-FILTER (ticket 31.3), before anything else runs for a candidate:
    its content hash is checked against a snapshot of the catalog taken once,
    up front. A hit is reported `skipped_unchanged` (R10) without ever
    reaching `_is_subagent_file`'s JSON parse, `capture_transcript`, a
    per-hash lock, or a database write - the machinery measured 2026-08-20 to
    dominate a daily run's real cost, not the read+hash itself (see
    harness/tickets/31-sweep-full-corpus-cost.md). The snapshot is taken
    ONCE and never updated mid-run: a session captured elsewhere DURING this
    sweep is simply absent from it and takes the full path (fails toward more
    work, never less), and two identical files both new to this run still go
    stored + duplicate-invocation exactly as before, because neither is in
    the snapshot yet either. R1 is unaffected (the hash decided is the same
    one `capture._capture_locked` decides on) and so is R9 (capture_transcript
    remains the only thing that stores or catalogs).

    `limit` (ticket 28.3, `ccw sweep --limit N`) caps the WALK to the first N
    transcripts in sorted order, for exercising a slice of a large source tree
    (a real deployment can be tens of thousands of files) rather than the whole
    thing. It bounds candidates considered, not sessions stored: some of the N
    may already be `skipped_unchanged`. The orphan-object catch-up pass below is
    unaffected - it reads `objects/`, not the source tree, and is not the cost
    this flag exists to bound."""
    walk_root = source if source is not None else _default_source()
    if not store.acquire_lock(config.root, _SWEEP_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, LOCK_HELD_ACTION, "sweep lock held by a live holder"),)
        )
    try:
        transcripts, outcomes = _walk_source(
            walk_root, skip_agents=not config.archive_subagents, limit=limit
        )
        already_known = _cataloged_hashes(config.root)
        # TWO PASSES, and the order is load-bearing. A sub-agent nests inside
        # its parent's folder, so the parent has to exist first; a single pass in
        # filename order files most sub-agents as orphans purely because they
        # sorted earlier. Sessions first, sub-agents second.
        wanted = [p for p in transcripts if _in_window(p, window)]
        deferred: list[Path] = []
        skipped = 0
        skip_elapsed_ms = 0
        for path in wanted:
            start = time.monotonic()
            digest = _content_hash(path)
            if digest is not None and digest in already_known:
                outcomes.append(ItemOutcome(path.name, "skipped_unchanged", ""))
                skipped += 1
                skip_elapsed_ms += _elapsed_ms(start)
                continue
            if _is_subagent_file(path):
                deferred.append(path)
                continue
            outcomes.append(_capture_item(config, path))
        for path in deferred:
            handled = _archive_subagent(config, path)
            outcomes.append(handled if handled is not None else _capture_item(config, path))
        # PASS THREE (ticket 38), over EVERY session path the walk yielded,
        # including the ones the pre-filter reported `skipped_unchanged`. A
        # sidecar can arrive after the last capture with the transcript's hash
        # unchanged, so a pass that only looked at newly stored sessions would
        # never see it - which is exactly how 1,067 directories went uncopied for
        # four months. Runs LAST because a sidecar nests inside its session's
        # folder and the folder has to exist first (ticket 21.4's lesson).
        names_by_dir: dict[Path, frozenset[str]] = {}
        for path in wanted:
            names = names_by_dir.setdefault(path.parent, _sidecar_dir_names(path.parent))
            if not _sidecar_candidate(path, names):
                continue
            handled = _archive_sidecars(config, path)
            if handled is not None:
                outcomes.append(handled)
        outcomes.extend(_archive_stranded(config, walk_root))
        cataloged = _cataloged_hashes(config.root)
        outcomes.extend(
            _capture_item(config, path)
            for path in _orphan_object_paths(config.root, cataloged)
        )
        if skipped:
            _record_sweep_unchanged(config.root, skipped, skip_elapsed_ms)
        return BatchReport(tuple(outcomes))
    finally:
        store.release_lock(config.root, _SWEEP_LOCK)
