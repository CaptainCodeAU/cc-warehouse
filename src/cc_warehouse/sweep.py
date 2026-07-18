"""ccw sweep: capture transcripts the hook missed and adopt orphan store objects.

Slice 5. The sweep carries ZERO capture logic of its own (R9/F8): it walks the source
tree and hands each transcript to the ONE store-and-catalog routine,
capture.capture_transcript, exactly as the hook does. A locks/sweep O_EXCL lock keeps a
sweep from racing a second sweep (R14/F3); capture's own hash-idempotence (F1/F3) makes
racing the hook harmless. Item failures are reported and the batch continues past them
(R5/R10); sources stay read-only (F9). See DESIGN sections 4 and 13.
"""

import os
from pathlib import Path
from typing import cast

from cc_warehouse import capture, catalog, store
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


def _walk_source(walk_root: Path) -> tuple[list[Path], list[ItemOutcome]]:
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
            if filename.startswith(_AGENT_PREFIX):
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


def _capture_item(config: Config, path: Path) -> ItemOutcome:
    """Hand one path to the shared capture routine (R9) and record its outcome.

    capture_transcript never raises on an unreadable item; it returns an `error` result,
    so the batch reports the item by name and continues (R5/R10/F7)."""
    result = capture.capture_transcript(config, path, session_id=None, cwd=None)
    return ItemOutcome(path.name, result.action, result.detail)


def sweep(config: Config, source: Path | None = None) -> BatchReport:
    """Capture whatever the hook missed, then adopt orphan store objects (slice 5).

    Walks `source` (default ~/.claude/projects), skipping agent-* transcripts, and hands
    each file to capture.capture_transcript under a locks/sweep O_EXCL lock; item failures
    (including a source subdirectory that cannot be listed) are reported and the batch
    continues (R5/R10). A live lock holder makes the sweep a no-op that reports a lock-held
    refusal and captures nothing (R14/F3). After the source walk, store objects with no
    catalog row are re-adopted through the same routine (DESIGN section 13). Sources are
    read-only throughout (F9)."""
    walk_root = source if source is not None else _default_source()
    if not store.acquire_lock(config.root, _SWEEP_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, LOCK_HELD_ACTION, "sweep lock held by a live holder"),)
        )
    try:
        transcripts, outcomes = _walk_source(walk_root)
        outcomes.extend(_capture_item(config, path) for path in transcripts)
        cataloged = _cataloged_hashes(config.root)
        outcomes.extend(
            _capture_item(config, path)
            for path in _orphan_object_paths(config.root, cataloged)
        )
        return BatchReport(tuple(outcomes))
    finally:
        store.release_lock(config.root, _SWEEP_LOCK)
