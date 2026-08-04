# Ticket 26: prove it, then back it up

The gate between "everything has been rescued" and "anything may be deleted".
Nothing in ticket 27 starts until this one closes.

## Why this ticket exists

The standing lesson is that non-destructiveness is a precondition, not an
intention: prove a backup before touching its original, so the worst outcome of
a future defect is a refusal rather than a loss.

The plan as originally sketched had the vault deleted at step 5 and the backup
taken at step 6. That leaves a window in which the archive is a single
un-backed-up copy on one machine. The external drive is mounted with 331 GiB
free against a 5.1 GiB archive, so closing the window costs almost nothing.

There is a second reason. Verifying an INCOMPLETE archive proves the wrong
thing. Ticket 25 must land first, or 26.1 certifies a tree that is missing about
1,900 payloads and certifies it as sound.

## Work order

### 26.1  `ccw archive --verify` over the whole tree

Per folder: the JSONL still matches the `source_hash` its manifest recorded, all
five generated files are present, and the folder name agrees with the payload's
own UUID and start time (ruling (b)).

Expect the count to have grown from 13,829 by ticket 25's imports. State the new
total and reconcile it against the sum of what was imported.

### 26.2  Re-run the byte-for-byte superset proof

Hash every archive JSONL, compare the set against the vault's object filenames
(an object's filename IS its sha256, so this is exact rather than sampled).

Last run 2026-08-03: 13,836 vault objects, 13,829 archive files, 7 vault objects
with no byte-identical archive copy, 0 archive files absent from the vault. After
ticket 25 the 7 should become 0. IF IT DOES NOT, ticket 27 does not start.

### 26.3  Reconcile every count and state what is unaccounted for

Exactly as the ticket 19 migration did: every number reconciled, nothing
approximate, and any gap chased rather than rounded off. The ticket 19 record is
the template, including the 50-block thinking gap that was chased down rather
than absorbed.

### 26.4  Back up the archive to the external drive

    <external>   460Gi total, 331Gi free, mounted   (checked 2026-08-03)

REQUIREMENTS: the copy is verified after it lands, not assumed; the verification
is independent of the copy tool's own exit code; and the result is recorded with
a date, because a backup nobody can date is a backup nobody trusts.

Decide with the principal: a plain directory copy, or a second `ccw archive
--to <drive path>` run. The second regenerates rather than copies, which proves
the tree is reproducible but writes different bytes for the generated files. The
first preserves bytes exactly. They answer different questions.

## Oracle tests

Mostly not unit-testable; this ticket is an operation on real data. What IS
testable and should be:

- the superset proof as a reusable check rather than a throwaway script, so it
  can be re-run by anyone later (it has now been hand-written three times);
- a verify pass over a tree with a known-corrupted JSONL fails that folder and
  names it, and does not abort the batch (R10).

## Contract excerpts

DESIGN 15 ruling (b) (`ccw verify` becomes archive integrity), R10, F6, and the
standing "prove a backup before touching its original" lesson.

## TOUCHES

`src/cc_warehouse/archive.py` (verify), possibly a new checked-in proof script
under `tests/` or a verb, `harness/` records.

## Process

Every figure computed, none recalled. State the instrument beside each number.
Report what was NOT covered as explicitly as what was.

---

## 26.1 - 26.3 DONE 2026-08-04. 26.4 IS BLOCKED ON A MACOS PERMISSION.

**26.1 verify.** `ccw archive --verify --to ~/cc-warehouse-archive`:
**19,224 folders checked, 0 problems**, after the ticket 25.5 import took the
tree from 14,472 to 19,226 folders (19,224 sessions plus the two reserved
`_not-sessions/` subdirectories).

**26.2 superset proof.** Exact, not sampled: every archive JSONL hashed against
the vault's content-named objects.

    vault objects                                  19,238
    archive .jsonl files                           20,644
    vault objects with no archive copy                  7
    PAYLOADS WHOSE CONTENT IS NOT IN THE ARCHIVE:       0

**THIS TICKET'S GATE WAS COUNTING THE WRONG THING and is corrected here.** As
written it says the count of vault objects with no archive copy "must become 0",
recorded as 7 (the journals). It read 11 before the import and 7 after, and it
can NEVER reach 0: those 7 are earlier snapshots whose bytes are a strict PREFIX
of a copy the archive holds in full. A HASH MISS IS NOT A CONTENT MISS. The gate
is now content containment, and by that measure it is met at 0. A gate that
cannot pass teaches the next session to skip it, which is worse than no gate.

**26.3 reconciliation.** The acceptance census reads 8 remaining "orphans" and
all 8 are in the archive: 6 filed under their payload's `sessionId` rather than
their legacy directory name, 2 under `_not-sessions/` with no `sessionId` at all.
Genuinely absent: 0. The census keyed on the DIRECTORY NAME, which is
path-as-identity and exactly what F4 forbids; the instrument was wrong, not the
import.

## 26.4 BLOCKED: the drive is unreadable from this session

`/Volumes/<external>` is mounted, APFS, 331 GiB free. Every access is refused:

    ls /Volumes/<external>      Operation not permitted
    touch .../probe             Operation not permitted
    stat /Volumes/<external>    drwxrwxr-x        <- Unix permissions ALLOW it

So it is macOS TCC, not filesystem permissions and not the Claude Code sandbox
(re-tested with the sandbox disabled: identical refusal). Process ancestry is
`claude <- zsh <- zsh <- herdr <- launchd`, so the grant belongs to **herdr**
(`/opt/homebrew/opt/herdr/bin/herdr`), not to a terminal application:

    System Settings -> Privacy & Security -> Files and Folders -> Removable Volumes
    (or Full Disk Access), grant herdr, then restart the session.

**The backup script is written and dry-run tested**, at
`<session scratchpad>/backup-archive.py`. It implements decision (b) in full: an
exact `rsync -a` byte copy, then verification that hashes BOTH sides completely
and compares them, explicitly not trusting rsync's exit code; it refuses to write
into an existing dated target rather than merging into a half-finished backup;
and it writes a `BACKUP-PROVENANCE.json` carrying the date, counts, byte total
and result. It currently exits 2 with the diagnosis above rather than doing
anything.

**TICKET 27 REMAINS BLOCKED.** Nothing in it starts until 26.4 is complete AND
dated, and 27.9 (clear `~/.claude`) is gated on that specifically.

## 26.4 DONE 2026-08-04, VERIFIED. Ticket 27 is unblocked.

The copy was made by the principal (this session cannot read the volume; see the
blocker above, which remains true and is why the verification was split).

    source   ~/cc-warehouse-archive                         116,433 files
    target   /Volumes/<external>/cc-warehouse-archive-2026-08-04
    method   exact byte copy, per principal decision (b)

**VERIFIED INDEPENDENTLY OF THE COPY TOOL, which is the whole of decision (b).**
Every file on both sides was hashed with sha256 and the two sorted manifests
compared in full. Nothing sampled, and no copy tool's exit code was trusted:

    source manifest sha256   ee1996858860ff2efa807ec399f8f3560b4ddc59
    target manifest sha256   ee1996858860ff2efa807ec399f8f3560b4ddc59
    diff                     IDENTICAL, 116,433 of 116,433 files

The manifest-of-manifests equality is the compact form of the proof: identical
digests mean identical paths, identical content hashes AND identical ordering.

Finder's 84 `.DS_Store` files were excluded from BOTH sides deliberately; they
are Finder artifacts inside the archive, not archive content. The archive's real
content is 116,433 files.

**THE ARCHIVE NOW EXISTS IN TWO PLACES FOR THE FIRST TIME.** That is the property
every destructive step in ticket 27 was waiting on, and 27.9 (clear `~/.claude`)
is gated on this being complete AND dated. It is both, as of 2026-08-04.

REMAINING, and it is the principal's to do by hand since this session cannot
write to the volume: drop a `BACKUP-PROVENANCE.json` beside the copy so the drive
is self-describing when the repo is not to hand. The date is otherwise carried by
the directory name and by this record.
