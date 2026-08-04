"""ccw import: adopt a foreign transcript tree (ticket 25.4). DESIGN section 7.

WHY A SEPARATE VERB (principal ruling, 2026-08-04). DESIGN 7 already listed
`ccw import` under the v1.1 cut and `config.py` already reserved an
`[import] inbox` key, so the verb was anticipated. Folding a second source
layout into `ccw migrate` was the alternative and was rejected: migrate is
"one-shot import of THE legacy archive" and would have become two tools wearing
one name.

The module name is `import_tree` because `import` is a keyword; the verb is
`import`.

WHAT MAKES THIS DIFFERENT FROM MIGRATE AND SWEEP, and it is only three things.
Everything else is deliberately theirs:

  1. It PRUNES branches by name, because the real source tree contains the
     operator's own quarantine and importing someone's quarantine back is the
     opposite of help. The prune is reported, never silent.
  2. It REFUSES a sub-agent payload instead of handing it to the session path.
     `migrate` does not, and on a tree that contained one that would file the
     sub-agent under its PARENT'S uuid and let replace-if-larger overwrite the
     parent's transcript (ticket 21a). Measured 2026-08-04: 0 of the 4,754 real
     orphans are sub-agents, so this refuses and reports rather than growing a
     rescue route that nothing exercises.
  3. It has somewhere to put a payload that is NOT a session. Ruling (a) says a
     file is a session when it carries a `sessionId`; exactly 2 of the 4,754 do
     not (they are Cursor transcripts, a different tool's format). They exist in
     one place only, so they are kept, under the reserved `_not-sessions/` home.

Everything else is shared code, on purpose (R9): the walk is `migrate.walk_jsonl`,
the read-only catalog probe is `sweep.cataloged_hashes_readonly`, and every
session goes through `capture.capture_transcript` exactly as the hook does, so
identity, project labels, folder naming, dedupe and the manifest are decided in
one place. The source tree is never written (F9); item failures are named and the
batch continues (R5/R10).
"""

import json
from pathlib import Path

from cc_warehouse import archive, capture, migrate, store, sweep
from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport, ItemOutcome

# Branch names never descended. `_DELETE` is the operator's own quarantine: 6,719
# session directories on the real tree (drift-dedupe, drift-empty-projects,
# duplicates, empty). Checked before this was written: ZERO of the 4,754
# importable sessions exist ONLY inside it, so pruning it loses nothing.
SKIPPED_BRANCHES = frozenset({"_DELETE"})

# The per-file manifest: latest run, one entry per source FILE, written via the
# store's one write primitive (R2). A pruned branch is reported in the batch but
# is deliberately absent here, because it is not a file.
_LOGS_DIR = "logs"
_MANIFEST_NAME = "import-manifest.json"

# DESIGN section 13: one lock per import, O_EXCL, its own name so an import and a
# sweep do not exclude each other (they are independent, and capture's own
# hash-idempotence makes them safe to overlap).
_IMPORT_LOCK = "import"
_LOCK_HELD_ITEM = "locks/import"

# Distinct actions, so the end report can tell a refusal from a failure and from
# a no-op. None of these is "error", so none of them makes the exit code non-zero
# (R10): a skipped quarantine and a rescued non-session are both correct outcomes.
LOCK_HELD_ACTION = "lock-held"
SUBAGENT_ACTION = "skipped-subagent"
NOT_A_SESSION_ACTION = "not-a-session"
SKIPPED_BRANCH_ACTION = "skipped-branch"
_WOULD_STORE = "would-store"
_WOULD_SKIP = "would-skip"
_WOULD_KEEP = "would-keep-not-a-session"
_WOULD_REFUSE = "would-refuse-subagent"


def _read(path: Path) -> bytes | ItemOutcome:
    """The payload, or a named error item. Never raises (R5/R10/F7)."""
    try:
        return path.read_bytes()
    except OSError as exc:
        return ItemOutcome(path.name, "error", f"unreadable: {exc.strerror or exc}")


def _kind(data: bytes) -> str:
    """`subagent` | `session` | `not-a-session`, decided from CONTENT (F4).

    Both predicates are `archive`'s, not re-derived here: the sub-agent
    discriminator in particular was wrong twice before it was measured, and a
    second copy would be a second chance to get it wrong differently.

    A payload the parser cannot read at all is called `not-a-session` rather than
    allowed to raise: it still gets rescued, into a home that makes no claim
    about what it is. Measured 2026-08-04 over all 4,754 real orphans: zero
    reach this branch.
    """
    try:
        if archive.is_subagent(data):
            return "subagent"
        return "session" if archive.is_session(data) else "not-a-session"
    except Exception:  # noqa: BLE001 - R10: classify, never abandon the batch
        return "not-a-session"


def _import_one(config: Config, path: Path) -> tuple[ItemOutcome, str]:
    """Import one file; returns its outcome and its content hash (for the manifest)."""
    data = _read(path)
    if isinstance(data, ItemOutcome):
        return data, ""
    kind = _kind(data)
    # The digest is computed only on the branches that need it. On the SESSION
    # branch capture returns its own, and hashing here as well would hash the
    # whole corpus twice: 392 MiB on the real tree, for a value immediately
    # overwritten.
    if kind == "subagent":
        return (
            ItemOutcome(
                path.name,
                SUBAGENT_ACTION,
                "sub-agent transcript; import handles sessions only",
            ),
            store.sha256_hex(data),
        )
    if kind == "not-a-session":
        digest = store.sha256_hex(data)
        if config.archive_root is None:
            return (
                ItemOutcome(path.name, "skipped", "not a session, and no archive_root is set"),
                digest,
            )
        try:
            target = archive.write_not_a_session(config.archive_root, data, stem=path.stem)
        except OSError as exc:  # R10: name it and carry on
            return ItemOutcome(path.name, "error", f"{type(exc).__name__}: {exc}"), digest
        return ItemOutcome(path.name, NOT_A_SESSION_ACTION, str(target)), digest
    result = capture.capture_transcript(config, path, session_id=None, cwd=None)
    return ItemOutcome(path.name, result.action, result.detail), result.sha256


def plan(
    config: Config,
    source_root: Path,
    *,
    skip: frozenset[str] = SKIPPED_BRANCHES,
) -> BatchReport:
    """What a real import WOULD do, writing nothing at all (`--dry-run`).

    A SEPARATE FUNCTION rather than a flag threaded through `import_tree`, for
    the reason `sweep.plan` documents and paid for: `store.acquire_lock` does
    `lock.parent.mkdir(parents=True)`, so merely taking the lock CREATES
    `<root>/locks/`, and `catalog.open_catalog` creates the database when absent.
    A rehearsal that leaves a warehouse behind has already failed at the one
    thing it exists to do. So this takes no lock and opens the catalog read-only.

    Each candidate is NAMED, because a count alone cannot be checked against the
    run that follows it, and every action is spelled `would-*` so a plan can
    never be misread as a result in the same report shape.
    """
    paths, outcomes, pruned = migrate.walk_jsonl(source_root, skip_dirs=skip)
    already = sweep.cataloged_hashes_readonly(config.root)
    outcomes.extend(
        ItemOutcome(str(directory), SKIPPED_BRANCH_ACTION, "pruned by name")
        for directory in pruned
    )
    for path in paths:
        data = _read(path)
        if isinstance(data, ItemOutcome):
            outcomes.append(data)
            continue
        kind = _kind(data)
        if kind == "subagent":
            outcomes.append(ItemOutcome(path.name, _WOULD_REFUSE, str(path)))
        elif kind == "not-a-session":
            outcomes.append(ItemOutcome(path.name, _WOULD_KEEP, str(path)))
        else:
            seen = store.sha256_hex(data) in already
            action = _WOULD_SKIP if seen else _WOULD_STORE
            outcomes.append(ItemOutcome(path.name, action, str(path)))
    return BatchReport(tuple(outcomes))


def import_tree(
    config: Config,
    source_root: Path,
    *,
    skip: frozenset[str] = SKIPPED_BRANCHES,
) -> BatchReport:
    """Import every session payload under source_root through the shared capture
    routine, pruning `skip` branches and reporting what was pruned.

    Idempotent by construction rather than by bookkeeping: capture decides
    identity by sha256 (F1), the archive applies replace-if-larger per uuid, and
    a rescued non-session is written to a content-addressed name. Re-running over
    the same tree therefore writes nothing new, which is what makes it safe to
    run again after a partial run.
    """
    if not store.acquire_lock(config.root, _IMPORT_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, LOCK_HELD_ACTION, "import lock held by a live holder"),)
        )
    try:
        paths, walk_errors, pruned = migrate.walk_jsonl(source_root, skip_dirs=skip)
        outcomes: list[ItemOutcome] = list(walk_errors)
        entries: list[dict[str, object]] = [
            {"source": outcome.item, "hash": "", "outcome": outcome.action}
            for outcome in walk_errors
        ]
        outcomes.extend(
            ItemOutcome(str(directory), SKIPPED_BRANCH_ACTION, "pruned by name")
            for directory in pruned
        )
        for path in paths:
            outcome, digest = _import_one(config, path)
            outcomes.append(outcome)
            entries.append({"source": str(path), "hash": digest, "outcome": outcome.action})
        logs_dir = config.root / _LOGS_DIR
        logs_dir.mkdir(parents=True, exist_ok=True)
        store.atomic_write(logs_dir / _MANIFEST_NAME, json.dumps(entries, indent=2).encode())
        return BatchReport(tuple(outcomes))
    finally:
        store.release_lock(config.root, _IMPORT_LOCK)
