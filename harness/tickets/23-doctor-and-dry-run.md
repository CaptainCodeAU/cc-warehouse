# Ticket 23: `ccw doctor`, and a sweep you can rehearse

The instrument, built BEFORE the thing it measures. Four surfaces: a health
verb, `--dry-run` and `--quiet` on sweep, and a gap figure on `status`.

DONE 2026-08-03, all three slices, same day as defined. Gates: ruff clean,
pyright strict 0 errors, 942 tests (was 870 at ticket 21 close).

    23a  sweep --dry-run + --quiet        DONE 2026-08-03 (eac2ae7)
         unknown-flag fix it forced       DONE 2026-08-03 (bfd293d)
         DESIGN 7 amendment               DONE 2026-08-03 (c7687a6)
    23b  uncaptured gap, wired into `status`   DONE 2026-08-03 (3f18798)
    23c  `ccw doctor`                          DONE 2026-08-03 (5f40880)

## WHAT IT SAYS ABOUT THIS MACHINE, first run

    ok   reachable   ccw resolves to <path>
    FAIL hook        NO capture hook is registered
    ok   fired       last capture 2026-08-01T12:48:40Z
    ok   uncaptured  565 session(s), 1420 sub-agent(s) with no archive folder
    FAIL overdue     222 session(s) OVERDUE, oldest last active 2026-08-01T12:55Z
    ok   config      root=... archive_root=... keep_objects=True
    doctor: capture is NOT working                                     exit 1

One command now reaches the conclusion a full session of hand investigation
reached on 2026-08-03. That is the entire justification for building the
instrument before the fix.

## Design decisions worth not relearning

**OVERDUE IS RELATIVE TO THE CORPUS, not the wall clock.** The fixtures forced
the better rule: `basic_session` is pinned to 2026-01-05, so any "older than N
hours" test calls every fixture overdue. More importantly a wall-clock rule
flags the session doctor is being run FROM, which is the crying-wolf failure
that gets a check ignored. Comparing against the newest activity anywhere in the
source tree asks the question that matters: have other sessions ended since this
one while it stayed uncaptured? Payload timestamps only (R12), and deterministic
enough to test without freezing a clock.

**Blocking vs reported.** The gap and the config are printed without being
alarms; only the hook, the never-fired case and overdue sessions decide the exit
code. A figure that always fails is a figure nobody reads.

**Hook detection covers plugins.** settings.json, settings.local.json AND
installed plugin `hooks.json` files, because ticket 24 delivers the hook as a
PLUGIN and a doctor that only knew about settings.json would call a correctly
installed hook missing.

**The gap's instrument is by UUID and its blind spot is documented**: a source
stem that is not a bare UUID reads as uncaptured even when archived.
Over-reporting is the safe direction, and `doctor` pays for the exact answer
where `status` cannot.

## Three of my own tests were wrong, and the product was right each time

- A malformed payload does NOT fail capture. Measured: `1 items, 1 stored, 0
  failed`. The store is content addressed and malformed LINES go to the
  manifest's loss block. A capture that refused unparseable input would lose
  exactly the sessions most worth keeping.
- A test scanning all output for "never" was fooled by pytest's `tmp_path`
  containing the test's own name.
- The R8 fence caught "identical" in doctor.py's docstring, used for a
  historical anecdote rather than as a guarantee. The prose was corrected rather
  than a proof mapping invented for a claim not being made.

## An F4 fence caught a design smell, not a name

23b first split sessions from sub-agents inside `status.py` using the `agent-`
prefix. `test_no_module_identifies_a_subagent_by_filename` fired. Reading it
showed the fence already exempts `sweep.py` on exactly the applicable ground,
that it walks a source tree. So the answer was not an exemption but removing a
duplicated walk: `sweep.source_transcripts` owns the split, `status` calls it,
and the prefix stays in the one sanctioned file (R9). The fence needed no change.

## 23a, and the defect it uncovered on the way

Adding `--dry-run` meant asking first whether unknown flags were rejected. They
were not, anywhere:

    ccw sweep   --totally-bogus-flag   exit 0, root CREATED, "1 items, 1 stored"
    ccw build   --totally-bogus-flag   exit 0, root CREATED
    ccw verify  --totally-bogus-flag   exit 0, root CREATED
    ccw status  --totally-bogus-flag   exit 0, root CREATED

A typo ran a real import, and `ccw sweep --dry-runn` would have performed the
very sweep the flag exists to rehearse. Fixed structurally at the dispatcher,
beside the help check, deriving each verb's valid flags from the same tables the
help is built from.

THE FENCE THEN FOUND FOUR FLAGS THE HANDLERS READ THAT THEIR OWN HELP DID NOT
LIST: `relocate --apply` (the EXECUTE flag: dry-run is the default, so without
it nothing happens and the help never said the word), `relocate --yes`,
`migrate --retire`, `migrate --yes`. The v1 exit review's `ccw project` finding
recurring, and a reminder that a surface can ship without its documentation and
no test will notice.

TWO CORRECTIONS I OWE, both mine:

- The unknown-flag check initially BURIED `ccw build --since`'s bespoke refusal,
  which explains why a windowed build is refused and cites DESIGN 15 block 5.
  `_REFUSED_FLAGS` now defers to the handler. Recognised-in-order-to-refuse is
  not the same as unknown.
- One oracle test I wrote was WRONG and the product was right. It fed a
  malformed payload expecting a capture failure; measured, that is
  `1 items, 1 stored, 0 failed`, because the store is content addressed and
  malformed LINES go to the manifest's loss block rather than being rejected. A
  capture that refused unparseable input would lose exactly the sessions most
  worth keeping.

`test_the_compact_x_spelling_does_not_parse` was NARROWED by principal ruling
(the fifth instance of that pattern): it asserted the mechanism by which the
bijection held, which only worked because unknown flags were discarded
everywhere. It now asserts the decision directly.

GATES AT 23a CLOSE: ruff clean, pyright strict 0 errors, 919 tests.

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
