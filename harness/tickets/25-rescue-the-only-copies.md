# Ticket 25: rescue everything that exists in one place

The largest ticket on this track, and the one with genuine unknowns. Purely
ADDITIVE: nothing is deleted, renamed or moved by any slice in it.

## Why this ticket exists

Five distinct sets of data exist in exactly one location. All five die if that
location goes, and `~/.claude` is scheduled to go.

    25.1  437 real sessions               41.6 MiB   ~/.claude only
    25.2  1,420 sub-agent transcripts    328.5 MiB   ~/.claude only; the archive
                                                     holds 0 sub-agent folders
    25.3  4 archived sessions that grew   +5.65 MB   archive holds truncated copies
    25.5  4,756 orphan sessions          392.2 MiB   NEITHER tree; 4,141 predate
                                                     the warehouse entirely
    25.7  7 workflow journals            399.5 KB    vault + ~/.claude only

All figures measured 2026-08-03 with the instrument stated beside each in
ticket 22 and the session record. THE COUNTS MOVE: 25.1 was 383 when measured
at 02:35Z and 441 at 05:12Z, the difference being exactly the 58 sessions whose
payload first timestamp falls in that window. Re-measure before acting; do not
plan against a number from a previous day.

## Work order

### 25.1 - 25.3  Sweep

No new code. `sweep.py` routes through `capture.capture_transcript` "exactly as
the hook does", and `capture.py:168-169` writes the archive unconditionally, so
a sweep today populates both trees and files sub-agents under their parents.
25.3 is handled by the same pass: re-capture replaces in place when the payload
is LARGER, and records a refusal in `manifest.json` when it is smaller.

PRECONDITION: ticket 23's `--dry-run`, rehearsed and compared to the real run.

ORDERING IS LOAD BEARING (ticket 21 finding 4): sessions first, then sub-agents,
because a sub-agent nests inside its parent's folder and a single pass in
filename order files most of them as orphans.

### 25.4  Build `ccw import --from <tree>`

NEW TOOLING. There is no route in for the legacy exporter layout:

    <tree>/<display-name>/<session-uuid>/
        <session-uuid>.jsonl        <- what we want
        index.html  page-NNN.html   <- theirs, not ours

Requirements: read ONLY the `.jsonl`; ignore their HTML entirely rather than
translating it; go through `capture_transcript` so identity, naming, dedup and
the manifest are decided by the same code as every other path (R9); be
idempotent; and skip anything already present by content hash.

`ccw migrate` exists for "one-shot legacy import" (DESIGN 10) and may be the
right home rather than a new verb. DECIDE THAT FIRST, with the principal, rather
than adding a verb DESIGN 7 does not list.

UNKNOWN, and the largest on this track: whether every one of those 4,754
payloads parses. They span 2026-02-14 to 2026-07-03, which is EARLIER than
anything the parser has seen; the corpus it was hardened against starts
2026-05-01. Ticket 18's registry found 0 unrecognised entries across 13,836
objects, but that census could not see entry types that only existed in
February. EXPECT unrecognised types and let the manifest counter report them
rather than failing.

`duplicates/` subtree: that tree contains one. Import must deduplicate by
content, and the count must be reported as distinct sessions, not folders. A
first pass on 2026-08-03 over-reported 4,756 as 9,541 for exactly this reason.

### 25.6  A reserved home for non-sessions

Ruling (a) says a file is a session if it carries a `sessionId` and no
`agentId`. The journals carry neither. They cannot be session folders.

`build.py:131` `RESERVED_LABELS = {"locks", "catalog.sqlite", "_orphaned-subagents"}`
and `archive.py:783` skips exactly that set when walking the tree. Any other
top-level folder is walked as a project label and its children yielded as
session folders, so an unreserved `_not-sessions/` would make
`ccw archive --verify` report garbage. Adding the label is therefore a code
change AND a contract amendment, not a `mkdir`.

Precedent exists: `_orphaned-subagents` was added the same way in ticket 21.

### 25.7  Move the journals in

COPY from ticket 22's interim location. R4 as amended: moving a JSONL means
deleting one, which the rebuild module may never do. The interim copy is
removed only by the principal, by hand, once the archive copy is verified.

## Oracle tests (write first)

- import reads only `.jsonl` and never opens or translates their HTML;
- import of a tree containing a `duplicates/` subtree yields DISTINCT sessions,
  and the reported count is distinct sessions not folders;
- re-running import over the same tree is a no-op (idempotence);
- a payload already present by content hash is skipped and REPORTED, not silent;
- a payload the parser does not fully understand still lands, and increments
  `unrecognised` rather than failing the batch (R10);
- the reserved label is refused as a project label (`build.py:218`) AND skipped
  by the tree walk (`archive.py:783`), asserted separately;
- a folder under the reserved label is NOT yielded as a session folder;
- `ccw archive --verify` passes with the reserved folder present;
- the journals arrive byte-identical to their vault objects;
- import never deletes: snapshot the source tree before and after.

## Contract excerpts

DESIGN 10 (migrate), DESIGN 15 ruling (a) as amended by ticket 21, R4 as
amended, R9, R10, R12, F4 (path is not identity), F6, F9.

## TOUCHES

`src/cc_warehouse/migrate.py` or a new import path, `build.py` (RESERVED_LABELS),
`archive.py`, `contract/DESIGN.md` (section 14 R4 note + section 15 entry),
`contract/SPEC.md` if the source-kind set grows, `tests/`.

## Process

Standard loop. Run on real data before believing it works, in a throwaway
target root first, never into the live archive.
