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
