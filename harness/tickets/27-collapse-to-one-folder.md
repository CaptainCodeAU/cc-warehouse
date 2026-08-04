# Ticket 27: collapse to one folder

The destructive ticket. Every slice in it is gated on ticket 26 closing green,
and the two marked DESTRUCTIVE need the principal's explicit word at the moment
of running, not in advance.

> ⛔ **27.9 IS WITHDRAWN (principal, 2026-08-04). `~/.claude` IS NOT TO BE
> DELETED FROM, BY ANYTHING, EVER.** Ticket 26 closed green that evening, so
> every gate 27.9 was waiting on is now satisfied. That is NOT permission. Read
> 27.9 before acting on any part of this ticket.

## Why this ticket exists

The end state has ONE folder. Today there are two warehouse trees plus two
legacy exporter trees, and the reason is simply that a migration is half done.

    ~/cc-warehouse-data       1.5 GB   objects/ + catalog.sqlite + locks/
    ~/cc-warehouse-archive    5.1 GB   the deliverable

The archive was proved a byte-exact superset of the vault except the 7 workflow
journals, which ticket 25 moves in. After that the vault holds nothing unique.

A NOTE ON WHAT "DELETE THE VAULT" MEANT. The original step list said delete
`objects/`. That leaves `catalog.sqlite` and `locks/` behind, so
`~/cc-warehouse-data` survives and the end state is still two folders. The
principal's own proposal, to merge rather than delete-and-keep, is what actually
reaches one, and the contract already reserved the two names it needs:
`build.py:131` reserves `locks` and `catalog.sqlite` as project labels precisely
so the flattened archive root cannot collide with them.

## Work order

### 27.1  `ccw reindex`

The principal's idea, and the half that is missing. `archive.py:647`
`read_projects` already reconstructs every project label and alias from the
tree with no database; it recovered 57 projects and 114 aliases on the real
archive. NOTHING CALLS IT. There is no verb.

`reindex` rebuilds `catalog.sqlite` from the archive folder alone. Once it
exists, "the catalog is a disposable index" stops being a claim and becomes a
demonstrable property, which is exactly the F6 class this project exists to
eliminate.

### 27.2  Prove it

Delete the catalog, run `reindex`, and compare the result against the original
row by row. The test asserts the fixture had aliases stored FIRST, because a
round trip over an empty set passes for the wrong reason (ticket 19f's lesson).

### 27.3  `keep_objects = false`

A NEW line in `~/.config/cc-warehouse/config.toml`; the key has never been in
that file and runs on its `config.py:162` default of True today. Reversible by
deleting the line.

`config.py:363` refuses `keep_objects = false` when there is no `archive_root`,
because that combination gives a capture nowhere to store the payload. The
interlock is already in the operator's favour and should be left alone.

### 27.4  DESTRUCTIVE: rename `objects/` aside, exercise, then delete

Rename, not delete. Then run capture, sweep, build, verify, status and a real
session end. Only when all of those pass does the renamed directory go, and the
principal runs that command.

### 27.5  Decide whether `root` moves into the archive

Setting `root == archive_root` would put `catalog.sqlite` and `locks/` inside
the archive, reaching one folder literally. UNTESTED: no test in the suite sets
them equal. Oracle tests first.

ARGUMENT AGAINST, recorded so it is decided rather than defaulted: an archive is
valuable because it does not change, and a live SQLite file plus lock files are
churn inside the thing being backed up. The alternative is to leave the root
where it is and let it hold nothing but regenerable state, which 27.1 makes
free to discard.

### 27.6  Re-read the `ccw archive --to` guard

Ticket 19h made `--to` refuse to target the warehouse. If the warehouse root
becomes the archive, that guard either blocks a legitimate run or waves through
a bad one. Read it before 27.5, not after.

### 27.7  Reconcile `ccw verify` with ruling (b)

Ruling (b) says `ccw verify` BECOMES archive integrity. Today that behaviour
lives on `ccw archive --verify` and plain `verify` still re-hashes the vault.
Once the vault is gone, plain `verify` has nothing to check.

### 27.8  Retire `store.py`

Dead once the vault goes. Ticket 19's instruction stands: do not delete the
module until the migration has run and been verified.

### 27.9  WITHDRAWN 2026-08-04 BY THE PRINCIPAL. DO NOT DO THIS.

**"I do NOT want you to delete anything from `~/.claude`. You do not have my
permission to delete anything from `~/.claude`."** (principal, verbatim,
2026-08-04, immediately after 26.4 was verified.)

This slice is CANCELLED, not deferred and not pending a gate. It read "clear
`~/.claude`" and it is now forbidden. The preconditions it was waiting on all
went green that same evening (26.4 complete and dated, 26.2 showing 0 payloads
whose content is absent from the archive), so a future session WILL find every
gate satisfied and must not read that as permission. The gates are satisfied and
the instruction is still NO.

Nothing in `~/.claude` is to be deleted, moved, emptied, pruned, rotated or
"cleaned up" by this project or by anything an agent runs on its behalf. That
includes `~/.claude/projects`, which is the source tree every capture path reads
and which F9 already makes read-only.

This does not weaken anything else: the archive being a proven superset is still
worth having, and `~/.claude` simply keeps its copies. The whole track was
justified by "five sets of data exist in exactly one place"; that problem is
solved by ADDING a second place, which is done, not by removing the first.

Earlier records in this repo say `~/.claude` "is scheduled to be wiped" and use
that to justify urgency. That was true when written and is now SUPERSEDED. The
supersession is left visible rather than edited away, per the append-not-rewrite
convention.

## Oracle tests (write first)

- `reindex` on a deleted catalog restores projects AND aliases, with the fixture
  asserted non-empty first;
- `reindex` is idempotent;
- `reindex` on a tree with a corrupt `project.json` skips that project and
  reports it, rather than dying (R5);
- `keep_objects = false` with no `archive_root` is REFUSED with the existing
  message;
- with `keep_objects = false`, a capture that cannot write the archive RAISES
  rather than reporting success (the promise flip at `capture.py:203-208`);
- `root == archive_root`: a capture writes exactly one copy, `locks/` and
  `catalog.sqlite` do not collide with any project label, and `read_projects`
  skips them;
- the rebuild module still never deletes a session JSONL (R4 as amended, the
  load-bearing test from ticket 19).

## Contract excerpts

DESIGN 15 "ARCHIVE-FIRST LAYOUT" in full, rulings (a) (b) (c), R1 and R4 as
amended, R2, R9, F1, F6, F9.

## TOUCHES

`src/cc_warehouse/cli.py`, `catalog.py`, `archive.py`, `store.py` (removal),
`config.py`, `contract/DESIGN.md`, `contract/SPEC.md`, `CLAUDE.md`, `tests/`.

## Process

Standard loop for the code; explicit principal confirmation at the moment of
running 27.4's delete and 27.9. Prove a backup before touching its original.
