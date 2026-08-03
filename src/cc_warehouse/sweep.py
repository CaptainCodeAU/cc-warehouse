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
from collections.abc import Callable
from pathlib import Path
from typing import cast

from cc_warehouse import capture, catalog, parser, registry, store
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
    walk_root: Path, *, skip_agents: bool = True
) -> tuple[list[Path], list[ItemOutcome]]:
    """The jsonl transcripts under walk_root plus a NAMED error item per directory that
    could not be listed; both sorted for determinism, agent-* skipped.

    Walks with os.walk(onerror=...) rather than Path.rglob because rglob SILENTLY swallows
    a PermissionError on a subdirectory, dropping an unreadable source tree with no report
    (an F7 under-capture that still exits 0). The onerror callback turns each directory
    OSError into a reported item (its .filename is the unreadable path) so the CLI names it
    and the exit code is non-zero, while the walk continues for the readable siblings
    (R5/R10). A missing source directory yields an empty walk rather than a crash (R5)."""
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
    return sorted(found), sorted(errors, key=lambda outcome: outcome.item)


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
    meta_path = path.with_suffix(".meta.json")
    meta = meta_path.read_bytes() if meta_path.is_file() else None
    # The project dir is two levels above `subagents/`; deriving from the
    # sub-agent's own parent would produce a label made of the session uuid.
    project_dir = path.parent.parent.parent
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
            config.archive_root, label, data, config.archive_timezone, meta=meta
        )
    except Exception as exc:  # noqa: BLE001 - R10: name it and carry on
        return ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}")
    action = "archived-subagent-orphaned" if result.orphaned else "archived-subagent"
    return ItemOutcome(path.name, action, str(result.directory))


def _capture_item(config: Config, path: Path) -> ItemOutcome:
    """Hand one path to the shared capture routine (R9) and record its outcome.

    capture_transcript never raises on an unreadable item; it returns an `error` result,
    so the batch reports the item by name and continues (R5/R10/F7)."""
    result = capture.capture_transcript(config, path, session_id=None, cwd=None)
    return ItemOutcome(path.name, result.action, result.detail)


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


def _cataloged_hashes_readonly(root: Path) -> frozenset[str]:
    """Session hashes already captured, WITHOUT creating anything (ticket 23).

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
    transcripts, outcomes = _walk_source(walk_root, skip_agents=not config.archive_subagents)
    already = _cataloged_hashes_readonly(config.root)
    for path in (p for p in transcripts if _in_window(p, window)):
        try:
            digest = store.sha256_hex(path.read_bytes())
        except OSError as exc:
            outcomes.append(ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}"))
            continue
        action = "would-skip" if digest in already else "would-store"
        outcomes.append(ItemOutcome(path.name, action, str(path)))
    outcomes.extend(
        ItemOutcome(path.name, "would-store", str(path))
        for path in _orphan_object_paths(config.root, already)
    )
    return BatchReport(tuple(outcomes))


def sweep(
    config: Config,
    source: Path | None = None,
    window: "Callable[[str | None], bool] | None" = None,
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
    `ccw build` lacks, which is why block 5 refuses the pair there."""
    walk_root = source if source is not None else _default_source()
    if not store.acquire_lock(config.root, _SWEEP_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, LOCK_HELD_ACTION, "sweep lock held by a live holder"),)
        )
    try:
        transcripts, outcomes = _walk_source(
            walk_root, skip_agents=not config.archive_subagents
        )
        # TWO PASSES, and the order is load-bearing. A sub-agent nests inside
        # its parent's folder, so the parent has to exist first; a single pass in
        # filename order files most sub-agents as orphans purely because they
        # sorted earlier. Sessions first, sub-agents second.
        wanted = [p for p in transcripts if _in_window(p, window)]
        deferred: list[Path] = []
        for path in wanted:
            if _is_subagent_file(path):
                deferred.append(path)
                continue
            outcomes.append(_capture_item(config, path))
        for path in deferred:
            handled = _archive_subagent(config, path)
            outcomes.append(handled if handled is not None else _capture_item(config, path))
        cataloged = _cataloged_hashes(config.root)
        outcomes.extend(
            _capture_item(config, path)
            for path in _orphan_object_paths(config.root, cataloged)
        )
        return BatchReport(tuple(outcomes))
    finally:
        store.release_lock(config.root, _SWEEP_LOCK)
