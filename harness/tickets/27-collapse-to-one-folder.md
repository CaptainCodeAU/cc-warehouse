# Ticket 27: collapse to one folder

The destructive ticket. Every slice in it is gated on ticket 26 closing green,
and the two marked DESTRUCTIVE need the principal's explicit word at the moment
of running, not in advance.

> ⛔ **27.9 IS WITHDRAWN (principal, 2026-08-04). `~/.claude` IS NOT TO BE
> DELETED FROM, BY ANYTHING, EVER.** Ticket 26 closed green that evening, so
> every gate 27.9 was waiting on is now satisfied. That is NOT permission. Read
> 27.9 before acting on any part of this ticket.

## Status, 2026-08-21

**27.1, 27.2, 27.3 and 27.4 are all CLOSED. 27.5-27.8 are open. 27.9 is
withdrawn and stays withdrawn.** The `objects/` delete HAS been run and
re-verified; see 27.4, which said the opposite until this date.

## Why this ticket exists

The end state has ONE folder. When this was written there were two warehouse
trees plus two legacy exporter trees, because a migration was half done.

    ~/cc-warehouse-data       1.5 GB   objects/ + catalog.sqlite + locks/
    ~/cc-warehouse-archive    5.1 GB   the deliverable

**Measured again 2026-08-21, after 27.3 and 27.4 landed:**

    ~/cc-warehouse-data        52 MB   catalog.sqlite + locks/ + logs/   (no objects/)
    ~/cc-warehouse-archive    9.3 GB   the deliverable, 22,130 session folders

The vault is gone and the catalog is what remains beside the archive, which is
the shape 27.5-27.8 now act on. The figures above are the ORIGINAL ones kept
for the record, not current.

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

### 27.4  DONE. Rename `objects/` aside, exercise, then delete - CODE BLOCKER FIXED 2026-08-20, DELETE RUN AND VERIFIED

Rename, not delete. Then run capture, sweep, build, verify, status and a real
session end. Only when all of those pass does the renamed directory go, and the
principal runs that command.

**ATTEMPTED 2026-08-20, BLOCKED - do not attempt the delete until this is
fixed.** The rename-and-exercise half ran on the real machine, with the
operator's explicit go-ahead: `objects/` (2.6 GB, 22,030 files) was renamed
to `objects.27.4-renamed-aside`, then `ccw status`, `ccw verify`, and `ccw
build` were run against the real warehouse.

`ccw status` and `ccw verify` both passed clean - `verify` already redirects
to archive integrity when `keep_objects = false` and `archive_root` is set
(ruling (b), 2026-08-02), so it never touched `objects/` at all, confirmed
by reading `cli.py:_run_verify` before running it, not assumed.

**`ccw build` did NOT pass clean: 4 of 21,460 sessions failed with
`FileNotFoundError` reading `objects/<hash>.jsonl`**, even though all 4
already have a COMPLETE archive folder (JSONL plus all five generated
files, confirmed by listing each folder directly).

**CORRECTED the same session, before this entry was even committed: the
first write-up above named the wrong mechanism.** It said `build._read`
reads `objects/` unconditionally with no archive fallback. That is FALSE -
read `archive.read_payload` (`archive.py:329-374`) and it already prefers
the archive folder over the store, VERIFIED (not trusted): it reads the
folder's JSONL and only falls through to `objects/` when that JSONL's
sha256 does NOT match the hash the catalog named for this head. Confirmed
directly, not assumed: computed `shasum -a 256` on all 4 archive JSONLs and
compared against each head's `catalog.session.hash` - all 4 mismatch.

**The real mechanism is ticket 29's ALREADY-OPEN "Mechanism 1", not a new
build.py gap.** `harness/tickets/29-which-copy-is-the-current-one.md`
documented, 2026-08-04/05: `build._heads` picks a session's head as "the row
no other row supersedes" - the newest INSERT - regardless of whether that
row's payload is the one whose bytes actually survived in the shared
archive folder (`write_source`'s deliberate "larger payload wins" rule can
leave an OLDER, LARGER capture's bytes on disk when a newer-but-SMALLER
recapture arrives). Checked directly: 3 of the 4 failing sessions
(`80721130-...`, `17e372b3-...`, `c85f1e1b-...`) are EXACTLY the three uuids
ticket 29's own "Blast radius today" section already named on 2026-08-04/05
- this session did not discover them, it re-found them through a different
door (a hard `FileNotFoundError` once `objects/` briefly wasn't there,
instead of `ccw archive --verify`'s "no problem" plus a silently-served
wrong-but-correct-content answer from the store). **The 4th, `b087d6a2-...`
(`CaptainCodeAU-win_go_app_test`), is NEW**: a fresh, TODAY (2026-08-20)
occurrence of the same class, a three-version supersedes chain where the
head (smallest, latest-inserted) does not match what the archive folder
actually holds (second-largest of the three). This proves Mechanism 1 is
still live and adding new affected sessions, not a closed historical case.

**So 27.4's delete step is blocked on ticket 29 Mechanism 1, not on a
build.py fix.** While `objects/` exists, this class of mismatch is silent
and harmless (ticket 29's own words) - `read_payload` quietly falls back to
the store and serves the CORRECT (larger) content anyway. Once `objects/`
is gone, that fallback has nothing to fall back to, and `read_payload`'s own
documented conservative branch RAISES rather than serving the wrong
session - which is exactly the `FileNotFoundError` this exercise hit. Ticket
29 already scopes Mechanism 1's fix (head selection should not promote a
row whose payload the archive folder demonstrably does not hold) and
already lists the locked oracle test it must not break
(`test_a_smaller_payload_is_refused_and_the_refusal_is_recorded`) - read
that ticket in full before scoping a fix here rather than re-deriving it.

**`objects/` was renamed back immediately** (not left broken overnight); a
second `ccw build` against the restored vault came back `4 built, 0
failed`, confirming both the original symptom and this corrected diagnosis
without losing or risking anything - the rename-not-delete shape did exactly
its job twice over.

**RESOLVED, same day, same session, with the operator's explicit go-ahead
before touching `build._heads`/`head_for_short` (both this ticket and
ticket 29's own docstring warning required scoping that with the principal
first).** Ticket 29 Mechanism 1 shipped: full account in `harness/tickets/
29-which-copy-is-the-current-one.md` and `contract/DESIGN.md` section 15,
"2026-08-20, ticket 29 mechanism 1". In short: `build._heads`/`head_for_
short` now rank each session_uuid's rows by payload recency (`COALESCE(
last_ts, captured_at)`, the same ordering `catalog._latest_version` already
used) instead of by insertion order, via one shared query fragment
(`build._HEAD_RANK_CTE`, R9). Oracle tests first (`tests/test_head_
selection.py`, RED confirmed via `git stash` on `build.py` alone, GREEN
after), full gate suite green, matrix anchor untouched.

**Then the FULL 27.4 exercise was re-run for real, a second time, exactly
as this entry's previous version asked for:** `objects/` renamed aside
again, `ccw status`/`verify`/`build`/`sweep --quiet`/a real live Claude Code
session end (via Herdr) all passed clean. `ccw build` specifically went
from `4 failed` (before the fix) to `0 failed` (after) against the
UNCHANGED real 21,460-session corpus - not a smaller or different fixture.
All 4 previously-failing sessions were checked directly against the fixed
head-selection query and now resolve to the exact hash sitting in their
archive folder. `objects/` was restored afterward, same as the first pass.

**What is NOT proven and must not be assumed:** a clean re-run over today's
corpus does not prove no OTHER session will hit this same class tomorrow
through a different chain shape this session did not construct as a test
case (e.g., three-plus versions with more complex tie patterns than the two
tested). The oracle tests cover the exact measured shape (later-content,
later-first-ts vs earlier-content, later-INSERT) plus the ordinary growth
case; they do not exhaustively enumerate every possible chain.

**THE DELETE HAS SINCE BEEN RUN. 27.4 IS CLOSED.** The paragraph that stood
here said the opposite and was left behind when the delete happened; corrected
2026-08-21. What it used to say, kept because the reasoning is still right for
every future destructive step: the code fix and its verification were covered
by that session's go-ahead, the delete was not, and fixing a blocker is not
consent to act.

**Re-verified first-hand on 2026-08-21, by four independent instruments,
because a document claiming a destructive step is still pending is exactly how
one gets done twice:**

1. `~/cc-warehouse-data/` holds `catalog.sqlite`, `locks` and `logs` and
   nothing else, 52 MB. No `objects/`.
2. No renamed-aside copy survives: a `find` across `$HOME` at depth 2 for
   `objects*` and `*objects-aside*` returned nothing.
3. `ccw doctor` reports `keep_objects=False`, "capture is working",
   "0 problems in the 25 most recently captured folder(s)", and a capture as
   recent as 2026-08-21T06:41Z.
4. The archive carries what the vault used to: 22,130 session folders,
   22,137 payload `.jsonl`, 9.3 GB; and 40 catalog sessions drawn at random
   resolved to a real archive payload 40 times out of 40.

`OPENING-PROMPT.md`, written 2026-08-21, already recorded 27.1-27.4 as closed
"including the `objects/` delete", so the disagreement was between documents
and not about the fact. `CLAUDE.md` carried the same stale claim and was
corrected in the same pass.

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
