# Ticket 23: `ccw doctor`, and a sweep you can rehearse

The instrument, built BEFORE the thing it measures. Four surfaces: a health
verb, `--dry-run` and `--quiet` on sweep, and a gap figure on `status`.

## Why this ticket exists

The capture hook stopped working on 2026-07-24 and nobody found out for ten
days. Every link looked healthy: the plugin was enabled, its files were intact
and byte-identical to their repo copies, the delegated CLI existed and still
exposed a `hook` verb. The failure was one layer down, `uv tool run` resolving a
DIFFERENT package of the same name from PyPI, and the wrapper discarded the
non-zero exit with `check=False`.

Nothing in the product could have told the operator. `ccw status` reports
"recent captures, counts, store size, last errors" against the CATALOG, so a
hook that never runs produces no error to report and no row to miss. Silence
reads exactly like idleness.

**This ticket is ordered before ticket 24 on purpose.** Fixing capture and then
asserting it works is what produced the last ten days. Building the measurement
first turns ticket 24's exit condition into a command rather than a belief.

The same argument applies to the sweep. `ccw sweep -h` once imported 13,836
sessions because eight of ten verbs never checked for the flag (2026-08-01). The
first real sweep after this ticket processes about 1,857 payloads into a tree
that is about to become the only copy. Rehearsing it is not optional.

## Work order

- SLICE: doctor + rehearsal
- GOAL: one command answers "is capture working, and if not, since when", and
  no batch import runs without a rehearsal available.

### 23.1  `ccw doctor`

READ-ONLY by construction, and that must be PROVED by snapshotting the tree
rather than asserted (the 2026-08-01 lesson: exit 0 plus output is not evidence
nothing happened). Reports, each with its instrument:

    reachability   is `ccw` on PATH, and which one (path + version)
    hook           is a capture hook registered anywhere Claude Code reads
    firing         has it ever fired; when last; from what evidence
    freshness      sessions in ~/.claude with no archive folder, and the oldest
    config         root, archive_root, archive_timezone, keep_* effective values
    integrity      folder count, last `archive --verify` outcome if recorded

Exit non-zero when capture is not working, so it composes into a cron or a
session-start check.

### 23.2  `--dry-run` on `ccw sweep`

Reports exactly what a real run would import, by name and count, and writes
NOTHING. Same R10 batch reporting as the real run so the rehearsal and the run
are comparable line for line.

### 23.3  `--quiet` on `ccw sweep`

Suppresses per-item output, keeps the end summary and all failures. Required
before 24.5 schedules a daily sweep; a chatty cron job is a cron job whose
output nobody reads.

### 23.4  `ccw status` reports the `~/.claude` gap

The figure that had to be computed by throwaway script three times on
2026-08-03 belongs in the product: how many sessions exist in the source tree
with no archive folder, and how many sub-agents.

## Oracle tests (write first)

- doctor on a warehouse with no hook installed exits NON-ZERO and says so;
- doctor on a healthy warehouse exits ZERO;
- doctor writes nothing: snapshot the whole tree before and after, compare;
- doctor names the resolved `ccw` path, not merely "found";
- doctor's freshness count matches an independently computed set on a fixture;
- doctor reports "never fired" distinctly from "fired, but not recently"
  (the 2026-07-24 failure looked like the second and was the first);
- `sweep --dry-run` imports NOTHING: tree snapshot before and after;
- `sweep --dry-run` names every item a real sweep would import, and the counts
  agree with the subsequent real run on the same fixture;
- `sweep --dry-run --quiet` still reports the summary and any failure;
- `sweep --quiet` suppresses per-item lines but never a failure (R10);
- `status` gap figure matches an independently computed set on a fixture;
- the inert-help fence covers `doctor` the moment it is listed.

## Contract excerpts

DESIGN 7 (the verb table; `doctor` must be listed there or be sanctioned as an
internal verb per the 2026-07-24 ruling), R5 (refuse rather than guess), R10
(batch reports every failed item by name and carries on), F6 (no overclaiming),
and the inert-help rule.

## Adjacent

`cli.py` dispatcher and `_run_status` · `sweep.py` `_walk_source` ·
`config.py` `ENV_VARS` and the effective-config load · `archive.py:647`
`read_projects` (doctor can reuse it rather than reimplement, R9).

## TOUCHES

`src/cc_warehouse/cli.py`, `sweep.py`, `status.py`, `contract/DESIGN.md`
(section 7 verb table), `tests/`.

## Process

Standard loop, oracle tests first, red for the right reason classified by
exception type. ruff + pyright strict + pytest before any commit.
