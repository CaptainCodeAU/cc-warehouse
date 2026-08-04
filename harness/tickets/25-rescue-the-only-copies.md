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

## 25.1 - 25.3 DONE 2026-08-04, by the scheduled sweep, unattended

The launchd agent installed for 24.5 ran on load and did the rescue: archive
13,829 -> 14,471 session folders, sub-agent folders 0 -> 1,411, vault 13,836 ->
14,482 objects, uncaptured 636 -> 2, overdue 321 -> 0. Exit 0, empty log.

Sub-agents reconcile EXACTLY: 1,411 source agent IDs, 1,411 archived, 0 missing.
An earlier "1,420" was a FILE count, not distinct IDs.

**IT ALSO EXPOSED A DEFECT, caught by verify rather than by reasoning.**
`ccw archive --verify` then reported 3,194 problems: 721 folders held a real
conversation and NONE of the five generated files. `sweep.py` never rendered,
because the hook renders by spawning a detached child and only `_run_hook` ever
called it. Fixed in b6aa3f4 (sweep now runs `build.build` when it stores
anything); archive repaired and re-verified at 14,471 folders, 0 problems. Cost
recorded as 28.20: build is O(everything), about 6 minutes regardless of what
changed.

## MEASURED 2026-08-04, before designing 25.4 (none of this was known when this
## ticket was written)

**THE TREE IS NOT THE UNIFORM `<project>/<uuid>/` THIS TICKET ASSUMED.**

    session dirs by depth:  depth 1: 2 · depth 2: 7,697 · depth 3: 6,420 · depth 4: 299
    top-level branches:     71, including `_DELETE/` and `_UNKNOWN`
    `_DELETE/` holds:       6,719 session dirs (drift-dedupe, drift-empty-projects,
                            duplicates, empty) - the PRINCIPAL'S OWN QUARANTINE

**ZERO of the 4,754 exist only inside `_DELETE/`.** Checked explicitly, because
importing someone's quarantine back into the archive would be the opposite of
help. The quarantine holds duplicates of things that also live outside it, so
skipping that branch loses nothing.

**TWO WORRIES MEASURED AWAY, both of which would have shaped the design wrongly:**

- THE WALK. `migrate._walk` (migrate.py:42) is already `os.walk`-based and fully
  depth-agnostic, selecting on `*.jsonl` alone, so it traverses this tree today
  and ignores the exporter's `index.html` / `page-NNN.html` by suffix. No new
  walker is needed.
- PROJECT LABELS. `capture._resolve` (capture.py:101) resolves payload cwd ->
  first jsonl cwd -> transcript PARENT DIRECTORY NAME -> `_unresolved`. On this
  layout the third rung would key the project on the UUID directory, which would
  be wrong. Measured: 250 of 250 sampled payloads carry a `cwd` (seed 11; 20
  distinct trailing names, led by `tax-data-sprint` x75). Rung one fires, the bad
  rung is never reached, and labels come out identical to a normal capture.

**IMPORT RISK IS LOW, not high as this ticket claimed.** 250 payloads sampled at
random (seed 7) from the 4,754: 250 parsed cleanly, 250 carry a `sessionId`.
Months in the sample: 2026-02 x7, 03 x15, 04 x199, 05 x29. Ticket 18's parser
hardening covers this era. The ticket called this "the largest unknown on this
track"; it is not.

## PRINCIPAL DECISIONS, 2026-08-04

(a) **A NEW `ccw import` verb**, not an extension of `migrate`. DESIGN 7 already
    lists `ccw import` under v1.1 and config.py:483,510 reserves an
    `[import] inbox` key, so the verb is anticipated. Extending `migrate` was
    rejected: it would become two tools wearing one name.

(b) **The external-drive backup is an EXACT BYTE COPY**, not a second `ccw archive --to`
    run. A rebuild proves reproducibility but writes different bytes for the
    generated files, which makes "is the backup the same?" hard to answer.
    Verify the copy independently of the copy tool's exit code, and date it.

(c) **`~/CODE/my-claude-code-transcripts` is KEPT until the backup is done and
    verified.** Removing it is then the principal's call, made with a proven
    backup in hand. Do not weaken this because an import "looked fine".

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

---

## 25.4 DONE 2026-08-04. 25.6 DONE. 25.7 DONE. 25.5 IS BLOCKED, see below.

**25.4 `ccw import --from DIR`** landed as `src/cc_warehouse/import_tree.py`
(`import` is a keyword) with 25 oracle tests. Gates: ruff clean, pyright strict
0 errors, 986 tests. The walk is `migrate.walk_jsonl`, promoted from private and
given a `skip_dirs` argument that prunes `dirnames` in place; the read-only
catalog probe is `sweep.cataloged_hashes_readonly`, promoted for the same reason.
No third walker was written.

**A FULL CENSUS REPLACED THE 250-PAYLOAD SAMPLE, and it changed two answers.**
Over all 4,754 orphans: 0 sub-agents, 0 parse failures, 0 uuids unique to the
quarantine, 2 with no `sessionId`. The 2 are CURSOR transcripts (`{"role":..}`,
no `type` key, no timestamp). Ruling (a) decides them: not sessions, so the
reserved home. Given a session folder they would BOTH compute
`undated_session/session.jsonl` and the larger would displace the smaller.

**The sub-agent guard exists because of what capture does NOT do.** `capture`
archives unconditionally with no `is_subagent` check, and `migrate` hands it
every file, so a sub-agent in a legacy tree would be filed under its PARENT'S
uuid and replace-if-larger could overwrite the parent. Zero exist here, so import
REFUSES and reports rather than growing an unexercised rescue route.

**25.6** `_not-sessions` is in `build.RESERVED_LABELS`; `archive.walk_folders`
skips it, `build.archive_session_dir` neutralises it as a project label, and
`ccw archive --verify` over the real tree reports 14,471 folders, 0 problems with
the folder present.

**25.7** 8 of 8 files (7 journals + `PROVENANCE.json`) copied to
`<archive>/_not-sessions/journals/` through `store.atomic_write` (R2), never a
shell `cp`. Every sha256 re-verified on arrival; originals byte-identical after.

## 25.5 DONE 2026-08-04, after the writer was fixed first (principal, option 5)

    ccw import --from ~/CODE/my-claude-code-transcripts
    7,700 items · 4,756 stored · 1 branch pruned · 2 kept as not a session
    0 sub-agents refused · 0 FAILED · 10m22s

    archive folders   14,472 -> 19,226   (19,224 sessions + 2 reserved subdirs)
    ccw archive --verify   19,224 folders checked, 0 problems
    legacy tree            0 files modified (F9)

**THE ACCEPTANCE TEST IS MET, and the instrument was wrong before the product
was.** The census re-run named 8 remaining "orphans". All 8 are in the archive:
6 under their PAYLOAD's `sessionId` rather than their legacy folder name (the
exporter's directory name disagrees with the payload for those 6), and 2 under
`_not-sessions/` because they carry no `sessionId` at all. **Genuinely absent: 0.**
The census keyed on the DIRECTORY NAME, which is path-as-identity, the exact
thing F4 forbids and the product correctly refuses to do. Fix the census, not
the import, if this is ever re-run.

**The three at-risk folders came through intact, checked against a pre-import
hash snapshot:** the JSONL and all four rendered files are byte-identical.
`manifest.json` changed on all three, and that is the fix working: each now
carries `replace_refused` with both byte counts (51,704/751,607 ·
806,446/810,512 · 8,659,426/8,682,224), which is F6 being honoured rather than
damage.

## The ticket 26.2 gate after the import

    vault objects                          19,238
    archive .jsonl files                   20,644
    vault objects with no archive copy          7   all strict PREFIXES
    PAYLOADS WHOSE CONTENT IS NOT IN THE ARCHIVE: 0

The 7 are the 4 pre-existing earlier snapshots plus the 3 truncated legacy twins
this import stored, exactly as predicted before it ran. No content is missing.

## What was blocked, and what unblocked it (kept for the record)

A full import into a THROWAWAY root (7,700 items, 7,671 stored, 0 failed, 9m34s)
was then verified, and `ccw archive --verify` reported **1 problem**:

    CaptainCodeAU-cc-print-shop/20260616-165951+1000_c85f1e1b-...:
    JSONL does not match manifest source_hash

Measured, not inferred. That session has TWO copies in the legacy tree, one a
strict byte PREFIX of the other. The folder's JSONL is the FULL 8,682,224 B copy
(replace-if-larger did its job); the manifest and all four rendered files were
generated from the TRUNCATED 8,659,426 B copy.

**THE MECHANISM IS PRE-EXISTING AND HAS NOTHING TO DO WITH IMPORT.**
`catalog.add_session` points every new row's `supersedes` at the previous latest,
so the NEW row is never superseded and `build._heads` ("a row no other row
supersedes") therefore makes it the head. A late-imported OLDER copy becomes the
head and is what `build` renders. `catalog._latest_version`'s docstring promises
"a late-imported old export therefore never displaces the newer copy"; that holds
for the supersedes POINTER and not for head selection, which is what renders.

**BLAST RADIUS ON THE LIVE ARCHIVE: exactly 3 folders.** Three uuids already in
the archive have a truncated twin outside the quarantine
(`17e372b3`, `80721130`, `c85f1e1b`). Each twin would be stored, become the head,
and re-render its folder from the truncated payload. The JSONL - the
irreplaceable half - stays correct in all three, and `ccw archive --verify` names
every affected folder, so it is detectable and repairable. Nothing is lost either
way; what degrades is the READABLE half of 3 sessions out of 19,224.

The remaining 4,753 orphans are unaffected: each has exactly one would-store
payload and no archived twin.

**Options put to the principal (see the session record). Do not pick one here.**

## Ticket 26.2's gate was measuring the wrong thing (corrected 2026-08-04)

The gate as written is "vault objects with no archive copy must reach 0". The
naive test reads **11**, not the 7 this ticket recorded, and can never reach 0:
4 of the 11 are earlier snapshots whose bytes are a strict PREFIX of the archived
copy, so no content is missing. Reformulated to CONTENT containment: 7 before
25.7 (exactly the journals), **0 after**. The gate is met.

## Also found, not fixed (ticket 28 material)

`--config PATH` and `--no-config` are accepted by every verb but IGNORED by the
four whose handlers take no arguments: `hook`, `status`, `doctor`, `verify`.
`ccw doctor --config <other>` prints the LIVE roots while appearing to honour the
flag, which is how a rehearsal gets mistaken for isolated. Isolation for the
throwaway run was proved directly instead.
