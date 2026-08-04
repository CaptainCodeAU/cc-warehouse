"""ccw migrate: one-shot legacy archive import (slice 10). DESIGN section 10.

The source tree is read-only forever; `retire` performs the single sanctioned
old-world write (one rename).
"""

import json
import os
from pathlib import Path

from cc_warehouse import capture, store
from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport, ItemOutcome

# Claude Code transcripts and v1 store objects share this suffix. migrate accounts for
# every REGULAR .jsonl under the archive, INCLUDING agent-* (unlike sweep, which skips
# them); a .jsonl dirent that is not a regular file (dangling/looping symlink, FIFO,
# socket, device) is reported as a named error rather than imported, so every source file
# lands in the per-file manifest either as an import outcome or an error (DESIGN section
# 10).
_JSONL_SUFFIX = ".jsonl"

# The migration manifest: latest run, one entry per source file, written via the store.
_LOGS_DIR = "logs"
_MANIFEST_NAME = "migrate-manifest.json"

# DESIGN section 13: one lock per migrate, O_EXCL, so two concurrent runs cannot race the
# shared manifest (last-writer-wins would erase one run's per-file accounting). Mirrors the
# sweep lock exactly (R14/F3).
_MIGRATE_LOCK = "migrate"

# A live lock holder is reported as a named item so the CLI end report and exit code name
# the refusal (R10); the item is the lock's path token.
_LOCK_HELD_ITEM = "locks/migrate"

# The lock-held outcome carries this DISTINCT action (not "error") so the CLI can refuse
# with a distinct line and a non-zero exit WITHOUT counting a no-op that imported zero
# items as a batch item. Public because the CLI end report keys on it (DESIGN section 13).
LOCK_HELD_ACTION = "lock-held"


def walk_jsonl(
    source_root: Path, *, skip_dirs: frozenset[str] = frozenset()
) -> tuple[list[Path], list[ItemOutcome], list[Path]]:
    """The regular jsonl transcripts under source_root plus a NAMED error item per
    directory that could not be listed and per .jsonl dirent that is not a regular file;
    both sorted for determinism. Third element: the directories PRUNED by `skip_dirs`.

    PUBLIC since ticket 25.4, when `ccw import` needed exactly this walk. It is already
    depth-agnostic (measured on the real legacy exporter tree: sessions sit at depths 1
    through 4, not the uniform two levels the ticket assumed), so import reuses it rather
    than adding a third copy of the same os.walk (R9). `skip_dirs` prunes `dirnames`
    IN PLACE rather than filtering afterwards, so a skipped branch is never descended:
    the real `_DELETE/` quarantine holds 6,719 session directories, and walking them to
    throw the results away would be the slow way to do nothing.

    Walks with os.walk(onerror=...) rather than Path.rglob because rglob SILENTLY swallows
    a PermissionError on a subdirectory, dropping an unreadable source tree with no report
    (an F7 under-capture that still exits 0). The onerror callback turns each directory
    OSError into a reported item (its .filename is the unreadable path) so the CLI names it
    and the exit code is non-zero, while the walk continues for the readable siblings
    (R5/R10). A .jsonl dirent that is NOT a regular file (a dangling/looping symlink, FIFO,
    socket, or device) is likewise reported as a named error rather than silently dropped
    (F7/R10) and is NEVER handed to capture (reading a FIFO named *.jsonl would block
    migrate forever); a symlink that resolves to a real regular file still imports normally
    because is_file follows links. Unlike the sweep this keeps agent-* transcripts: the
    manifest must account for every archive file (DESIGN section 10)."""
    if not source_root.is_dir():
        return [], [], []
    errors: list[ItemOutcome] = []
    skipped: list[Path] = []

    def _on_error(exc: OSError) -> None:
        name = exc.filename if isinstance(exc.filename, str) else str(source_root)
        errors.append(
            ItemOutcome(name, "error", f"unreadable source directory: {exc.strerror or exc}")
        )

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(source_root, onerror=_on_error):
        base = Path(dirpath)
        if skip_dirs:
            pruned = [name for name in dirnames if name in skip_dirs]
            skipped.extend(base / name for name in pruned)
            dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        for filename in filenames:
            if not filename.endswith(_JSONL_SUFFIX):
                continue
            path = base / filename
            if not path.is_file():
                # A .jsonl dirent that is not a regular file is reported by name rather
                # than silently dropped (F7/R10); it is NEVER handed to capture (reading a
                # FIFO would block migrate forever).
                errors.append(ItemOutcome(str(path), "error", "not a regular file"))
                continue
            found.append(path)
    return sorted(found), sorted(errors, key=lambda outcome: outcome.item), sorted(skipped)


def migrate(config: Config, source_root: Path) -> BatchReport:
    """Import every session payload under source_root via the shared capture routine;
    hash dedupe collapses duplicate copies; every source file is accounted for.

    Carries ZERO capture logic of its own (R9/F8): each transcript is handed to
    capture.capture_transcript exactly as the hook does, so duplicate archive copies
    collapse to one object by sha256 (F1). Item failures are reported by name and the
    batch continues past them (R5/R10); the source tree is never written (F9). A per-file
    manifest (source path, hash, outcome) plus any directory that could not be listed is
    recorded to <root>/logs/migrate-manifest.json through the one store write primitive
    (R2). A locks/migrate O_EXCL lock serializes concurrent migrate runs so two cannot race
    the shared manifest (R14/F3); a live holder makes migrate a no-op that reports a
    lock-held refusal and imports nothing. The lock wraps the import only; retire is the
    single sanctioned rename and guards its own concurrency (DESIGN section 10)."""
    if not store.acquire_lock(config.root, _MIGRATE_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, LOCK_HELD_ACTION, "migrate lock held by a live holder"),)
        )
    try:
        paths, walk_errors, _skipped = walk_jsonl(source_root)
        outcomes: list[ItemOutcome] = list(walk_errors)
        entries: list[dict[str, object]] = [
            {"source": outcome.item, "hash": "", "outcome": outcome.action}
            for outcome in walk_errors
        ]
        for path in paths:
            result = capture.capture_transcript(config, path, session_id=None, cwd=None)
            outcomes.append(ItemOutcome(path.name, result.action, result.detail))
            entries.append({"source": str(path), "hash": result.sha256, "outcome": result.action})
        logs_dir = config.root / _LOGS_DIR
        logs_dir.mkdir(parents=True, exist_ok=True)
        store.atomic_write(logs_dir / _MANIFEST_NAME, json.dumps(entries, indent=2).encode())
        return BatchReport(tuple(outcomes))
    finally:
        store.release_lock(config.root, _MIGRATE_LOCK)


def retire(source_root: Path, *, year_month: str) -> Path:
    """Rename source_root to _RETIRED_<YYYY-MM>_<name>; returns the new path.

    The single sanctioned old-world write in the whole tool (DESIGN section 10): the
    archive contents are untouched, only its root directory name changes. REFUSES when the
    target name already exists rather than rename onto it: os.rename would silently remove
    an existing empty dir (a delete outside R4's closed list) or raise on a non-empty one
    (R5/F2/F9), so this is the ONE clean rename and never clobbers."""
    new_path = source_root.parent / f"_RETIRED_{year_month}_{source_root.name}"
    if new_path.exists() or new_path.is_symlink():
        raise FileExistsError(f"retire target already exists: {new_path}")
    os.rename(source_root, new_path)
    return new_path
