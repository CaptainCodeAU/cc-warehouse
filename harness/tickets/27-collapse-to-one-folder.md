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

---

## 27.1 DONE 2026-08-05. 27.2 DONE, AND ITS ANSWER IS "NOT YET".

`ccw reindex [--from DIR] [--to DIR] [--dry-run]` ships. Oracle tests were
written first and seen RED (17 failing on "unknown verb 'reindex'") before any
implementation existed. Gates: ruff clean, pyright strict 0 errors.

**27.2 RUN AGAINST THE REAL ARCHIVE, and the comparison is the point of the
slice.** `--to` writes the rebuilt catalog into a scratch directory, so the
live catalog a firing hook is writing to was never replaced.

                              LIVE      REBUILT
        session rows         19,247      19,233
        distinct uuids       19,233      19,233
        projects                 97          90
        aliases               4,913         114
        capture_event        36,332           0

        hashes in both ............... 19,233
        in LIVE only .................     14
        in REBUILT only ..............      0     <- invents nothing
        uuids in LIVE only ...........      0     <- loses no session
        project labels matched .......  90 of 90

**EVERY ONE OF THE 14 IS ACCOUNTED FOR, none is a lost session:**

        workflow journals (no sessionId, filed under _not-sessions/) ....  7
        superseded versions linked by a supersedes chain ................  4
        older copies of a uuid whose larger copy the archive holds .....   3
        GENUINELY ABSENT ...............................................   0

The 3 were chased rather than rounded off: in each case the live catalog holds
two copies of one uuid and the archive holds the larger, so the rebuild has the
better copy and not the worse one.

**THE VERDICT, and it decides the order of the rest of this ticket. The catalog
is disposable for SESSIONS and LABELS. It is NOT yet disposable for ALIASES:
114 of 4,913 recovered, 2.3%.** That is ticket 28.21 measured at full scale.
`archive.write_project_files` has one caller, the `ccw archive` verb, so every
alias learned since the 2026-08-02 bulk run exists only in the database. A
rebuild would keep every session and every label and lose the mapping from
Claude Code's encoded dirs and cwds to the names the operator chose, which is
what stops a renamed project splitting in two on the next capture.

**SO 28.21 IS NOW A PREREQUISITE OF 27.4, not a backlog item.** 27.4 renames
`objects/` aside and then deletes it; the argument for that being safe is that
the archive is a complete substitute. On sessions it is. On aliases it is not,
and the proof above is how we know rather than how we hope.

**28.21 CLOSED 2026-08-05, SO THAT PREREQUISITE IS MET FOR EVERYTHING WRITTEN
FROM NOW ON.** The sidecar is written by the path that creates the folder, and
the round trip that could not pass before now does: capture only, `ccw archive`
never run, catalog deleted, `ccw reindex`, and both labels and aliases return.
Details and the measured cost are on 28.21.

**THE 33 EXISTING FOLDERS WERE FILLED IN THE SAME DAY, on the principal's word,
and the gate was RE-MEASURED rather than inferred from the fix.**

`archive.write_project_files` was called directly rather than through
`ccw archive --to`. That verb was what had been offered, but it re-renders 19k
folders; the function is the part of it that writes sidecars, and reading its
code shows its only write target is `directory / project.json` through
`store.atomic_write`. Narrower instrument, same result.

    BEFORE   90 label dirs, 57 project.json, 116,585 files
    AFTER    90 label dirs, 90 project.json, 116,618 files
    TOUCHED  45 project.json, and NOTHING ELSE (0 non-sidecar files modified)

45 rather than 90 because the content skip works on real data: 33 new, 12 whose
alias sets had grown, 45 already correct and left alone with their mtimes intact.

    ccw archive --verify     19,235 folders checked, 0 problems

**THE RE-MEASURED GATE, which is the number 27.4 actually rests on:**

                           LIVE    REBUILT
        projects             97         90
        aliases           4,913      4,906
        sessions         19,249     19,235
        distinct uuids   19,235     19,235

        ALIAS RECOVERY   4,906 of 4,913  =  99.9%   (was 2.3%)
        invented         0 aliases, 0 labels, 0 sessions

**THE 7 THAT DID NOT COME BACK ARE THE 7 WORKFLOW JOURNALS, and they are not a
gap.** The 7 unrecovered aliases and the 7 unrecovered projects are the same 7
`wf_*` labels: payloads with no `sessionId`, filed under `_not-sessions/journals/`
by ruling (a). `walk_folders` skips `_not-sessions` because it is a reserved
label, so those projects have no folder for a sidecar to sit beside. A project
with no session folder has nothing in the tree to describe, which is what
`write_project_file` returning False for a missing directory already says.

So on ALIASES the archive is now a complete substitute for everything the tree
can describe. That was 27.4's open objection and it is closed. 27.4 is still
DESTRUCTIVE and still needs the principal's word at the moment of running.

## Two fences fired during 27.1, and both were right

Recorded because the standing rule is that a locked test blocking correct work
is a SIGNAL, and because what they changed was the design, not the paperwork.

1. `test_no_deletion_primitives_outside_rebuild_modules` (R4) caught
   `shutil.rmtree` on the staging DIRECTORY the first version built into. The
   dodges available were adding `reindex.py` to the closed list, or reaching for
   `tempfile.TemporaryDirectory` whose cleanup the fence cannot see. Both
   declined. R2's own words are "tmp FILE plus os.replace", so the fence was
   pointing at the sanctioned shape rather than blocking the work, and the
   rewrite deletes nothing at all.
2. `test_write_handles_only_in_sanctioned_modules` (R2) then caught the
   `.write_bytes` that truncates an inherited staging file. Routed through
   `store.atomic_write`, which is what R2 exists to make unavoidable.

A fence that can be defeated by a synonym teaches the next session to skip it.
Neither was widened.

### 27.3  DONE 2026-08-20. `keep_objects = false`

A NEW line in `~/.config/cc-warehouse/config.toml`; the key has never been in
that file and runs on its `config.py:162` default of True today. Reversible by
deleting the line.

`config.py:363` refuses `keep_objects = false` when there is no `archive_root`,
because that combination gives a capture nowhere to store the payload. The
interlock is already in the operator's favour and should be left alone.

**What shipped and how it was verified, on the real live machine, with the
operator's explicit go-ahead first.** The line was added to `~/.config/
cc-warehouse/config.toml` (config file, not repo-tracked - no commit for the
edit itself). `ccw doctor` immediately confirmed the interlock accepted it
(`config ... keep_objects=False`, no refusal, since `archive_root` is already
set on this machine) rather than trusting the config file alone.

Verified end to end with a REAL Claude Code session (via Herdr, not a test
fixture): opened a session, got a real reply, exited it with `/exit` to fire
a genuine SessionEnd hook capture. Confirmed directly on disk and in the
catalog: `~/cc-warehouse-data/objects/` file count stayed at exactly 22,030
before and after (the vault got NO new file - `keep_objects = false` is
honoured, not just accepted), the session's archive folder was created
correctly under `~/cc-warehouse-archive/`, its catalog row exists, `logs/
capture.jsonl` shows a clean `"status": "ok"` line (5 ms), and no
`post-archive-write failure` diagnostic line appeared (31.4's stage logging,
confirming the catalog-write path is unaffected by this config change).
`ccw doctor` stayed fully green afterward, including the new `desync` check
(31.5) against the freshly archived folder.

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

**WHERE THIS SLICE ACTUALLY CAME FROM, traced through the transcript archive on
2026-08-04 at the principal's request. It was never his instruction.** The chain,
with timestamps:

    2026-08-03T02:44:48  THE PRINCIPAL, and these are his only words on it:
      "Please note that ~/.claude Will not outlive this folder because the
       warehouse data folder or the warehouse archive folder, whichever one you
       are deciding to keep, or whichever one is the proper name"

    2026-08-03T02:44:48  ME, same minute, turning it into a premise:
      "That changes the stakes materially [...] If ~/.claude is going away too,
       then anything not in the warehouse is lost"

    2026-08-03T04:42:31  ME, ~2 hours later, premise now stated as FACT and as a
    step I would carry out:
      "7  ONLY THEN clear ~/.claude"
      "Context that changes everything: ~/.claude is being wiped once the
       archive is backed up."

A census of every user message across the whole transcript corpus found **ZERO**
instructions from the principal to delete, clear or wipe `~/.claude`.

His sentence was dictated and garbled ("Will not outlive this folder because the
... folder, whichever one you are deciding to keep"), and the standing rule for
dictated input is explicit: when a transcription leaves ambiguity that would
change what you do, ASK. It would have changed what I did. I did not ask, and
two hours later an ambiguous observation about durability had become a red-marked
task in a numbered plan, carried forward through three more documents without
ever being put back to him as a decision.

The failure is not the plan step. It is that a step which destroys the source of
every session on the machine was created by inference, marked urgent, and never
once surfaced as "confirm this is what you want". Every subsequent document then
cited the earlier one, so the premise hardened by repetition rather than by
evidence.

Earlier records in this repo say `~/.claude` "is scheduled to be wiped" and lean
on it for urgency. SUPERSEDED, and it was never sourced. The supersession is left
visible rather than edited away, per the append-not-rewrite convention.

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
