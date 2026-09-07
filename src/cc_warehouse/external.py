"""Where a session's content lives OUTSIDE its own directory, and how to find it.

Ticket 39. The sibling of `sidecars.py`, and the difference is the whole reason
this is a second module rather than three more names in that one.

`sidecars.py` answers "what sits BESIDE this transcript" - a question with a
directory to look in, `transcript_path.parent`. The stores here are siblings of
`projects/` itself, so there is no per-session directory to scan and nothing about
a transcript's location leads to them. They are reached by SESSION ID:

    ~/.claude/file-history/<session-uuid>/<hash>@vN     versioned file snapshots
    ~/.claude/todos/<session-uuid>-agent-<uuid>.json    the session's todo list

MEASURED 2026-09-08 on the live tree, because the plan's own numbers were a day
old and two of them moved:

  file-history   1,056 dirs, 929,845,225 bytes. ALL 1,056 are bare session uuids;
                 the plan expected roughly 5% not to be, and today none are. Flat,
                 no nesting. 1,014 resolve to a session the archive already holds,
                 42 do not. Sampled 23 snapshots across 12 sessions: the first 200
                 bytes of each appear in that session's own transcript ZERO times,
                 so the archive is the only place this content can survive.
  todos          3 files, 2 bytes each. Genuinely trivial, and archived anyway: a
                 store this module NAMES but nothing copies is the "parses, is
                 tested, does nothing" shape ticket 38's fence exists to forbid.

`paste-cache/` is deliberately absent. It is reachable only by joining through
`history.jsonl`, which is a later slice's work; naming it here without a copier is
exactly what the fence above rejects.

TWO SHAPES OF LOOKUP, because the two callers ask different questions. The capture
hook has ONE session and wants one answer, so it pays one stat. The sweep has tens
of thousands and wants the whole store, so it pays one scandir and joins in memory
- 1,056 entries read once, rather than 29,567 stats to find them.

THE BULK MAPS ARE ALSO THE ONLY THING THAT CAN SEE A STRANGER. The plan asked for
discovery driven from the catalog, to keep a directory NAME from becoming an
identity (F4). Scanning the store and joining second reaches the same join from the
other end and keeps the same guarantee - the name is still only a filter, and what
decides where bytes land is the archive folder that uuid resolves to. What it adds
is the case the plan's own risk table requires: iterating the catalog can only find
directories it already knows about, so a non-uuid directory or an unarchived
session's snapshots would be invisible to it by construction.

READ-ONLY, ALWAYS. Nothing in this module writes, moves or deletes anything under
`~/.claude` (operator rule, verbatim 2026-08-04), and nothing here opens a file:
directory entries answer every question it asks (F5).
"""

import os
import re
from pathlib import Path

FILE_HISTORY_DIR = "file-history"
TODOS_DIR = "todos"

# The stores this module knows how to reach. Every name here must have a copier,
# and the oracle suite asserts it, for the same reason `sidecars.COPIERS` does.
SESSION_STORES = frozenset({FILE_HISTORY_DIR, TODOS_DIR})

# Skipped at every depth, exactly as in `sidecars.IGNORED`. One exists in the live
# `file-history/` right now; Finder writes them into any folder a human browses.
IGNORED = frozenset({".DS_Store"})

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# `todos/` names a file after the session it belongs to, then repeats an agent id:
# `<session-uuid>-agent-<agent-uuid>.json`. Only the leading uuid is used, and only
# to ROUTE the file - it is a filter on a source layout, never an identity claim
# about the file's contents (F4).
_TODO_NAME = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-agent-.+\.json$"
)


def _entries(directory: Path) -> list[os.DirEntry[str]]:
    """Directory entries, or nothing at all when the directory cannot be listed.

    NEVER RAISES and never opens a file. A missing `~/.claude` subdirectory is the
    ordinary case on a fresh machine, and an unreadable one must not be the thing
    that fails a capture (DESIGN 12).
    """
    try:
        with os.scandir(directory) as it:
            return list(it)
    except OSError:
        return []


def file_history_dir(claude_home: Path, session_uuid: str | None) -> Path | None:
    """This session's file-history directory, or None.

    One stat, for the capture hook's single-session case. A payload with no
    session id joins to nothing and must NOT fall back to a path (F4).
    """
    if not session_uuid:
        return None
    candidate = claude_home / FILE_HISTORY_DIR / session_uuid
    return candidate if candidate.is_dir() else None


def todo_files(claude_home: Path, session_uuid: str | None) -> tuple[Path, ...]:
    """This session's todo files, by the uuid their names start with.

    A listing rather than a stat, because the agent id in the middle of the name is
    not derivable from the session. The store holds 3 files today, so this is
    cheaper than it looks; the sweep uses `todos_by_session` instead.
    """
    if not session_uuid:
        return ()
    found = [
        Path(entry.path)
        for entry in _entries(claude_home / TODOS_DIR)
        if (match := _TODO_NAME.match(entry.name)) and match.group(1) == session_uuid
    ]
    return tuple(sorted(found))


def file_history_by_session(claude_home: Path) -> dict[str, Path]:
    """Every session-keyed file-history directory, from ONE scandir.

    The sweep's half of the pair. 1,056 entries read once beats 29,567 stats to
    find the same 1,056, and unlike the per-session lookup it can also answer what
    is in the store that no session claims (see `unknown_children`).
    """
    return {
        entry.name: Path(entry.path)
        for entry in _entries(claude_home / FILE_HISTORY_DIR)
        if entry.is_dir() and _UUID.match(entry.name)
    }


def todos_by_session(claude_home: Path) -> dict[str, tuple[Path, ...]]:
    """Every todo file grouped by the session its name starts with."""
    grouped: dict[str, list[Path]] = {}
    for entry in _entries(claude_home / TODOS_DIR):
        match = _TODO_NAME.match(entry.name)
        if match:
            grouped.setdefault(match.group(1), []).append(Path(entry.path))
    return {uuid: tuple(sorted(paths)) for uuid, paths in grouped.items()}


def unknown_children(claude_home: Path, store: str) -> tuple[str, ...]:
    """Names in a store that this module cannot route to any session.

    THE SIGNAL, and the reason the bulk scan exists. Today it returns nothing for
    both stores, which is the point: it is the instrument that says when that
    changes, rather than a report of a problem we already have. A store whose
    shape drifts silently is how `tool-results/` went four months unnoticed.
    """
    if store == FILE_HISTORY_DIR:
        return tuple(sorted(
            entry.name
            for entry in _entries(claude_home / FILE_HISTORY_DIR)
            if entry.name not in IGNORED and not (entry.is_dir() and _UUID.match(entry.name))
        ))
    if store == TODOS_DIR:
        return tuple(sorted(
            entry.name
            for entry in _entries(claude_home / TODOS_DIR)
            if entry.name not in IGNORED and not _TODO_NAME.match(entry.name)
        ))
    raise ValueError(f"not a known external store: {store!r}")


def stranded_file_history(
    claude_home: Path, known: "frozenset[str] | set[str]"
) -> tuple[Path, ...]:
    """Snapshot directories whose session the archive does not hold.

    42 of the live 1,056 are in this state. They are named so they can be landed
    somewhere deliberate; their directory name is a LABEL and is never used to
    invent a session folder (F4), for the same reason ticket 38's stranded
    sidecars are not.
    """
    return tuple(
        path
        for uuid, path in sorted(file_history_by_session(claude_home).items())
        if uuid not in known
    )
