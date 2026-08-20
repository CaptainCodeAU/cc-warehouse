# Ticket 31: sweep's full-corpus cost, and the resilience gap it exposed

Opened 2026-08-20, from `contract/PROPOSALS/daily-sweep-full-corpus-cost.md` -
a proposal filed the same day by an assistant session that started from one
broken session folder the operator handed over (`CaptainCodeAU-win_go_app_test/
20260820-093714+1000_b087d6a2-...`) and traced the investigation outward into
the daily `ccw sweep` job. Full evidence, numbers, and reasoning live in that
proposal; this ticket is the work-order.

**31.1 (folded into 31.2) DONE, 31.2 DONE, 31.3 DONE, 31.4 DONE (logging only,
by design - see below), 31.5 DONE. Ticket 31 is CLOSED as of 2026-08-20.**

## Why this ticket exists

`ccw sweep` runs daily (`com.captaincodeau.ccw-sweep`, 12:30) and its cost
grows with the *total* number of sessions this warehouse has ever captured
(21,728 and rising), not with how many are actually new since yesterday. This
is the third instance of one defect class in this project: ticket 28.20 named
it for `ccw build` and left it open; ticket 30 fixed the analogous cost for
`ccw archive`'s weekly job. Neither touched `ccw sweep` itself.

Measured today: 17,079 of 21,728 sessions got the FULL treatment (read + hash
+ a database write) during the daily run; 16,382 of those (96%) found nothing
new. On top of that, `ccw sweep` unconditionally calls `ccw build` whenever it
stores anything (541 sessions today), and `ccw build` is *also* O(everything)
(ticket 28.20) - on this deployment specifically, `keep_projections = false`
means that entire second pass writes nothing, anywhere, ever. Pure waste,
daily, forever, currently ~40-50+ minutes combined.

Chasing why this mattered surfaced a second, related finding: one real
session's capture partially failed during this exact daily window - its raw
transcript was safely saved, but the catalog row, the rendered pages, and the
operator's voice/Finder confirmation never happened, silently. `ccw archive
--verify` confirms this is rare (1 of 21,669 folders today), not systemic, but
the failure mode itself has no retry and no automatic alarm today.

## Work order

### 31.1  WRONG AS FIRST WRITTEN, CAUGHT BEFORE ANY CODE SHIPPED (2026-08-20).

The original text of this slice proposed guarding the `build.build()` call in
`_run_sweep()` (`cli.py` ~line 647-648) entirely on `config.keep_projections`,
on the premise that `build.build()`'s only job is maintaining `projections/`.
**That premise is false, verified by reading `build.build()`'s body
(`build.py` ~line 473-528) before implementing, not after:**

```python
for head in heads:
    ...
    data = _read(config, head)                              # unconditional
    if config.keep_projections:
        write_projection(directory, data, options, force=rebuild)
    _mirror(config, head.label, head.short, data, options)   # ALSO unconditional
```

`_mirror()` (`build.py` ~line 397) calls `archive.write_session_folder()` -
the same function ticket 30 fixed. **This is what keeps a SWEPT session's
ARCHIVE folder current**, independent of `keep_projections` entirely - a
session captured via the daily safety net never gets a detached render child
(`sweep()`'s own comment: "this sweep would have spawned 2,064 processes"),
so `build.build()`'s per-head loop, called at the end of `_run_sweep`, is the
*only* thing that renders a swept session's archive pages at all.

**Guarding the whole call on `keep_projections` (this deployment's actual
setting) would have skipped `_mirror()` for every session sweep captures -
turning today's rare 1-of-21,669 desync into a guaranteed one, for every
swept session, forever.** That is a regression, not a fix, and it is exactly
the failure shape section "the resilience gap" above is about.

Two oracle tests were written for the original (wrong) design - one asserting
`build.build()` is never called when `keep_projections = false`, one asserting
it still is when true. The first was correctly RED before any implementation
(proving the described cost is real); before writing the fix, reading
`_mirror()` showed the assertion itself was wrong, not just unimplemented.
Both were reverted rather than shipped (`git checkout --` on the test file)
so the ticket does not carry a green suite built on a false premise.

**What ships instead:** `_read(config, head)` (the actual expensive part -
a full store read for every session, every run) has no cheap pre-check before
it runs, for *any* head, regardless of `keep_projections`. `_mirror()`
already benefits from ticket 30's `folder_is_current` check *after* the read
(covering the render+write cost); the read itself is not gated by anything.
This folds 31.1 into 31.2 below rather than keeping it a separate "quick win"
- there was no safe quick win here, only the general fix.

### 31.2  DONE 2026-08-20. Give `build.build()` a cheap pre-check, mirroring `archive.folder_is_current`

Plan: `Plans/federated-sleeping-lark.md`. Went through two rounds of
adversarial review (an Explore pass over the real code, then a Plan pass)
before any line shipped, because a first sketch of this exact slice (the
original 31.1, folded in here - see the correction above and in "31.1" below)
was caught mid-review as a regression: it would have skipped `_mirror()`,
which is the ONLY thing that renders a swept session's archive pages.

**What shipped**, mirroring ticket 30's proven shape rather than inventing a
new one:

- `archive.folder_is_current` split into a shared core (`archive.
  _current_manifest`, private) plus two public answers over it:
  `folder_is_current` (unchanged signature/behavior - archive folders, which
  can carry sub-agents) and new `archive.pages_are_current` (the old
  `projections/` tree, which never can - `write_subagent` only ever writes
  under `archive_root`, so a projection manifest has no `subagents` key and
  `folder_is_current` unmodified would return False there unconditionally).
- `build._head_is_current(config, head, projection_dir, options)`: ANDs
  whichever of the two trees this deployment actually keeps. Skips a head's
  ENTIRE read only when every live tree already reflects it; independently
  correct rather than leaning on `config.py` refusing the "nothing kept
  anywhere" combination.
- `build._archive_dir_for(config, head)`: computes the archive path from
  `_Head`'s existing columns (`hash`, `label`, `first_ts`, `session_uuid`) -
  no SQL widening needed, unlike ticket 30's own starting point. Same "safe
  by construction" argument: a wrong computed path just fails to find a
  manifest and falls through to a full rebuild, never a wrongful skip.
- Two things this review surfaced that ticket 30 itself never needed:
  1. `folder_is_current` never checked the archive JSONL itself, only the
     five generated files - `ccw build` had always happened to restore a
     deleted JSONL as a side effect of reading from the store first.
     **Operator decision (2026-08-20): keep that repair** rather than lose it
     silently - `_head_is_current` also checks `archive.sole_jsonl(folder)
     is not None`, one `glob()` per archived head.
  2. `build._mirror()` never forwarded `rebuild` to `write_session_folder`,
     so `ccw build --rebuild` had always silently done nothing to an
     already-current archive folder (masked because real drift always trips
     `folder_is_current` anyway). Fixed alongside - the skip depending on
     `rebuild` meaning something in both trees is what made the gap matter
     for the first time.
- `ccw build`'s CLI summary gained an "N unchanged" segment, never folded
  into "built" (R10/F6), mirroring `archive.MigrationReport.summary()`.

Full account: `contract/DESIGN.md` section 15, entry "2026-08-20, ticket
31.2". Read ticket 30's own account first
(`harness/tickets/30-incremental-archive-rebuild.md`) if picking up 31.3-31.5
next - it names three hazards a naive port of this pattern would reintroduce
if not carried over deliberately; 31.2 carried all three over explicitly.

**Oracle tests**: `tests/test_build_incremental.py` (new, 15 tests - 5 proving
the new skip behavior, 10 proving nothing that worked before broke), plus 2
in `tests/test_keep_projections.py` (the judgment-call ruling, both
directions) and 1 in `tests/test_sweep_projects.py` (a genuinely new session
is still fully rendered even when the rest of a large corpus is skip-eligible
- the case a naive "skip when nothing kept" design would have broken).
Confirmed RED-before/GREEN-after via `git stash` on the source changes alone,
not assumed. Gates: `uv run pytest` (1094 passed + these 18; the one
unrelated failure, `test_every_shipped_file_is_tracked_by_git`, is new files
not yet `git add`ed, not a regression), `uv run pyright` (0 errors), `uv run
ruff check` (clean). `tests/golden/matrix-anchor` untouched - no projected
byte moved, only when bytes get (re)written.

### 31.3  DONE 2026-08-20. Give `sweep()`'s own walk a cheap pre-check before the read+hash

**The ticket's own premise, measured before any design was written, was
FALSE.** Read+hash of a real transcript costs ~0.4 ms/file (~7 s/day across
the ~16,400 daily skips) - not the driver of the 34.5-minute daily window.
The real per-item cost, measured directly: `_is_subagent_file`'s full JSON
parse (~44 s/day) and, hidden because `capture.py`'s own `elapsed_ms` timer
stops one line before it, `record_event`'s per-item lock file + fresh sqlite
connection + `BEGIN IMMEDIATE`/COMMIT (~19 s/day, timed in isolation against
a throwaway copy of the real catalog). So the open design question this
section originally posed (mtime+size side-table vs. reducing per-skip DB
cost) was answered by neither option as framed: a side-table would have
spent an R1 exception on the 0.3% of the cost that was never the problem.

**What shipped**: `sweep.plan()`'s own already-shipped skip decision (read,
hash, compare against a cataloged-hashes snapshot) moved onto `sweep()`'s
hot path, taken ONCE up front rather than invented fresh. A hit skips
`_is_subagent_file`, the per-hash lock, and the database write entirely and
is still reported `skipped_unchanged` (R10). The snapshot is never updated
mid-run, so a session captured elsewhere during the sweep, or two
identical-content files both new to one run, are unaffected (both fall
through to the ordinary path exactly as before). R1 and R9 both hold without
exception - full account in `contract/DESIGN.md` section 15, entry
"2026-08-20, ticket 31.3".

**Operator decision, 2026-08-20**: the ~16,400/day per-item
`skipped_unchanged` rows are replaced by one aggregate `capture_event` row
per run (`action = "sweep-unchanged"`, `session_hash = NULL`, detail carries
the count), keeping `ccw doctor`'s `fired` check moving on a day nothing new
is stored.

**Oracle tests**: `tests/test_sweep_incremental.py` (new, 11 tests). RED
confirmed before implementation via `git stash` on the source changes alone,
GREEN after. Gates: `uv run pytest` (1105 passed, the pre-existing
"unrelated" `test_every_shipped_file_is_tracked_by_git` failure is the new
test file not yet `git add`ed, matching 31.2's own precedent, resolved by
staging it), `uv run pyright` (0 errors), `uv run ruff check` (clean).

**Verified on real data.** A real (non-dry-run) `ccw sweep` against the live
21,734-session corpus completed in **81.9 s wall-clock** (18,976 items, 200
stored, one `sweep-unchanged` row of 17,080, `elapsed_ms` 386 for the
pre-filter pass itself). `ccw doctor` and `ccw archive --verify` both
confirmed healthy afterward (see DESIGN 15 entry for both readings).

**What this entry does NOT claim**: every per-item mechanism identified here
sums to roughly 72 s for a corpus this size, nowhere near the 2,072.5 s
(34.5 min) the daily launchd job actually took on 2026-08-20. That ~91% gap
was never explained by anything in this codebase; the leading unproven
candidate is this machine's own confirmed resource contention under 4+
concurrent sessions, which cannot be reproduced by an isolated measurement.
Whether the daily job now runs faster in practice is unverified - the
81.9 s figure above is an interactive run under this session's own load, not
launchd's. 31.4 and 31.5 should treat the missing 91% as still open, not
assume this ticket closed it.

### 31.4  DONE 2026-08-20 (logging only; the retry loop stays unshipped). Retry-with-backoff on catalog lock contention in `_capture_locked`

The resilience half. `capture.py` `_capture_locked()` writes the archive
JSONL first (`_archive_source`, ~line 168) and only afterward opens/commits
the catalog row (`catalog.add_session`, ~line 186). `catalog.py` already sets
`PRAGMA busy_timeout = 5000` (~line 139), so a lock wait is bounded today, not
infinite - but nothing retries after that timeout is exceeded, and the
best-supported (not proven - see below) reading of the one broken folder
found today is exactly this: the JSONL write succeeded, something after it
didn't, and the whole capture aborted silently rather than partially
completing and reporting so.

**Open question the proposal flagged and this ticket inherits: the
lock-contention mechanism is not proven.** No stack trace was recoverable
live. Before writing the retry loop, add debug logging around the
post-`write_source` steps in `_capture_locked` and confirm the actual
exception on the next real occurrence, rather than designing a fix for an
unconfirmed cause. If a different exception shows up, the fix target changes;
don't assume.

**What shipped: debug logging only, exactly as scoped above - no retry loop.**
Reading `_capture_locked` (`capture.py`) before writing anything showed the
one broken folder's own shape is reachable two ways, and only one of them was
ever going to surface anything: the HOOK path (`_run_hook`) already wraps
`capture_transcript` in a never-raise boundary and calls `notify.report` on
any exception (SPEC 2.6/F7) - so a hook-side failure was already being
logged, just as a bare `repr(exc)` that never says WHICH post-archive-write
step failed. The SWEEP path (`sweep.sweep` -> `_capture_item`, `sweep.py`
~line 224-230) has **no such wrapper at all**: `_run_sweep` (`cli.py` ~line
628) calls `sweep.sweep()` directly with nothing catching a per-item
exception, so an uncaught `_capture_locked` failure during a sweep aborts the
ENTIRE `ccw sweep` process mid-batch, before `report = sweep.sweep(...)`
ever returns - nothing is printed, nothing is logged, and every item still
queued in that run is simply never attempted (picked up by the next sweep
instead, not lost). This is the more complete explanation for "silently":
not a caught-but-unreported failure, but an escape from every reporting path
the codebase has, for the one pipeline (sweep) that has no per-item
try/except at all. **This is analysis from reading the code, not a live
occurrence - still unconfirmed, per the open question above, and the fix
target (adding sweep-side per-item exception handling) is deliberately NOT
shipped here**, matching the ticket's own instruction not to design a fix
for an unproven cause.

What ships: `catalog.add_session` and `catalog.record_event` (`capture.py`
~line 186-193, the two calls after `_archive_source`/`_archive_subagents_of`)
are each wrapped in a narrow try/except that appends a diagnostic line to the
existing O_APPEND audit log (`notify.append_log`, `logs/capture.jsonl` -
DESIGN R2's sanctioned exception; no new write path) naming the STAGE
(`add_session` or `record_event`) and the exception, then unconditionally
re-raises. Behavior is byte-for-byte unchanged except for the added log line:
the hook path still reports via `notify.report` exactly as before, and the
sweep path still has no wrapper (deliberately untouched - see above). Also
confirmed by reading `catalog.py`: `add_session` and `record_event` are TWO
SEPARATE `writing()` transactions on the same connection, so a session CAN
end up cataloged (the `session` row commits) with no corresponding `stored`
`capture_event` row if `record_event` is the one that fails - a real,
previously undocumented partial-state case the stage label now distinguishes
from an `add_session`-stage failure (nothing cataloged at all).

**Decision, recorded as instructed: 31.3 does NOT make this moot.** 31.3
eliminated the ~16,382/day `skipped_unchanged` catalog writes entirely (they
now never reach `capture_transcript`). The suspected contention population
was never those - it is the FRESH-IDENTITY `add_session`/`record_event`
pair, `capture_event` `action='stored'` rows, measured today at 753/day, a
count 31.3 does not touch at all (it only ever ran the skip path, which
never wrote `stored`). Lower overall DB traffic plausibly lowers contention
PROBABILITY (fewer transactions contending for the same reserved lock across
a run), but that is a mitigating side effect, not a fix, and it is not
measured. The retry loop stays exactly where the ticket left it: blocked on
a confirmed exception, which has not recurred (0 `capture_event` rows with
`action='error'` in the live catalog as of this session, and the live
`add_session`/`record_event` wrap has not fired either).

**Cheap check done first, as instructed.** `catalog_event` and the launchd
job's own record (`launchctl print`, `runs = 6`, `last exit code = 0`) show
today's 12:30 local (02:30 UTC) `ccw sweep` run happened at 02:30:02-
02:38:17 UTC, producing 16,382 individual `skipped_unchanged` rows - the
PRE-31.3 shape. 31.3 was committed and tagged at 08:10-08:11 UTC, after
today's job had already run. So there has been NO real launchd-triggered
sweep on the 31.3 code yet; the only post-31.3 data point remains the
81.9s interactive verification run 31.3's own entry already flagged as not
representative of launchd's environment/load. Tomorrow's 12:30 run is still
the first real test - unchanged from what the previous handoff already said,
now confirmed from the actual event log rather than assumed.

**Oracle tests**: `tests/test_capture_stage_logging.py` (new, 2 tests) -
monkeypatches `catalog.add_session`/`catalog.record_event` to raise, and
pins both that the stage-labeled diagnostic line lands in `logs/
capture.jsonl` AND that the original exception still propagates unchanged
(no swallowing). RED confirmed via `git stash` on `capture.py` alone before
GREEN. Gates: `uv run pytest` (1109 passed; the one "unrelated" failure is
`.envrc`, untracked before this session started, not a file this ticket
touches - not 31.2/31.3's precedent repeating, a different pre-existing
gap), `uv run pyright` (0 errors), `uv run ruff check` (clean).

### 31.5  DONE 2026-08-20. Wire a cheap desync check into `ccw doctor`

`archive.py` `verify_folder()`'s "JSONL does not match manifest source_hash"
check is exactly the right instrument (it found today's broken folder, 1 of
21,669, correctly and immediately) but currently requires an operator to run
`ccw archive --verify` by hand. `ccw doctor` already runs at every Claude Code
SessionStart via `ccw-watch` (an external consumer of its text output - see
`contract/PROPOSALS/incremental-archive-rebuild.md` appendix item 1, still
true) and today only does a cheap file-count walk
(`sweep.source_transcripts()`), never a verify pass.

Scope this carefully: a full `ccw archive --verify` over 21,000+ folders is
not SessionStart-cheap. Whether this means a sampled check, a check scoped to
recently-touched folders only, or a separate lighter instrument is an
implementation decision, not answered by the proposal - decide and record the
reasoning, don't default silently to "check everything" and reintroduce the
exact cost this ticket exists to remove elsewhere.

**Decision, recorded: sampled by recency, not full coverage.** `ccw doctor`
gained a new `desync` check, blocking (it affects the exit code, same as
`overdue`). It verifies only the `_DESYNC_SAMPLE = 25` most RECENTLY STARTED
archive folders (`doctor._recent_archive_folders`, ordered by the payload's
own start time encoded in the folder name - R12, never mtime), against
`archive.verify_folder` - the same instrument `ccw archive --verify` uses,
unmodified. Reasoning: a desync from an in-flight capture failure (this
ticket's whole motivation) shows up in sessions just captured, not one
archived months ago, so a small bounded recent sample catches the failure
mode this check exists for without re-adding the O(everything) cost ticket
31 exists to remove elsewhere. **Explicitly NOT caught**: an old,
long-standing desync outside the sample - `ccw archive --verify` over the
full tree (by hand, or the weekly `com.captaincodeau.ccw-archive` job) stays
the complete answer; this check is a fast, narrow tripwire for RECENT
breakage, not a replacement.

`ccw doctor`'s existing TEXT OUTPUT compatibility surface (the `hook` line
and the `Uncaptured: N session(s)` figure `ccw-watch` regexes - see
`CLAUDE.md`) is untouched: `desync` is a brand-new check name, appended after
`overdue`, and nothing about the existing checks' wording changed.

**Oracle tests**: `tests/test_doctor.py` (+2) - one CLI-level (subprocess
`ccw doctor`) tampering a real archived JSONL and asserting non-zero exit
plus the folder name in the report, proving the check fires without a
hand-run `ccw archive --verify`; one in-process against `doctor._desync`
directly (the sample size is a module constant, not a flag a subprocess run
can override) proving the SCOPE decision itself: an old tampered folder
outside a sample of 1 is invisible, the same folder back in-sample (limit
25) is caught. RED confirmed via `git stash` on `doctor.py` alone before
GREEN. Gates: same run as 31.4 above (`uv run pytest` 1109 passed + the one
pre-existing unrelated `.envrc` failure, `uv run pyright` 0 errors after
adding `# pyright: ignore[reportPrivateUsage]` on the two direct `_desync`
calls - no other codebase precedent for a test calling another module's
private function existed to follow, so this was the smallest fix rather than
widening `_desync` into a public API it does not otherwise need -, `uv run
ruff check` clean). `tests/golden/matrix-anchor` untouched (re-run directly,
61 passed) - `ccw doctor` output is not part of the projected matrix.

## Things already checked and ruled out (do not re-investigate)

- Duplicate hook registration (old `claude-transcript-exporter` plugin cache
  vs. current `cc-capture@cc-warehouse`): confirmed only one is installed.
- `ccw-watch`/`ccw doctor` at SessionStart, fired by this operator's several
  concurrent sessions: confirmed read-only, a plain `os.walk`, not a
  contributor to the database write pressure.
- The weekly `ccw archive` job: separate schedule (Sunday only), already
  fixed by ticket 30, not stacked with the daily cost this ticket addresses.

Full evidence trail (file/line references, exact numbers, exact commands run)
is in the proposal - do not re-derive it, verify it against current code if
it looks stale.

## Oracle tests (write first)

- `ccw sweep`, run twice back to back with nothing changed on disk in
  between, produces zero reads/hashes/writes for previously-seen files below
  whatever skip line 31.3 lands on (exact assertion depends on the 31.3
  design decision).
- RESOLVED 2026-08-20 (31.3 DONE): the skip line is "never reaches
  `capture.capture_transcript`, `_is_subagent_file`'s parse, or a per-hash
  lock/DB write" - `test_a_second_sweep_never_calls_capture_transcript_
  for_an_unchanged_session` and `test_a_second_sweep_never_opens_a_per_item_
  lock_or_catalog_connection` in `tests/test_sweep_incremental.py` pin it
  both white-box and black-box.
- CORRECTED 2026-08-20: the bullet that stood here ("`_run_sweep` does not
  call `build.build()` when `keep_projections = false`") described 31.1's
  ORIGINAL, RETRACTED design and directly contradicted the retraction twelve
  lines above it. `build.build()` must still be called in that case -
  `_mirror()` is the only thing that renders an archive-only session's pages.
  See `tests/test_build_incremental.py` for the 15 tests that actually shipped
  (31.2 DONE below) instead.
- `build.build()`'s per-session skip check matches ticket 30's shape
  (source_hash, config, renderer_version) across BOTH trees a deployment might
  keep, ANDed - not a naive single-tree check (31.2).
- CORRECTED 2026-08-20 (31.4 DONE): this bullet described the retry loop
  itself, which stayed unshipped exactly as instructed (the lock-contention
  mechanism is still unproven). What shipped instead: a simulated
  `sqlite3.OperationalError` from `catalog.add_session` or
  `catalog.record_event` is logged BY STAGE to `logs/capture.jsonl` and then
  still propagates (no retry, no swallow) - `tests/
  test_capture_stage_logging.py`, both directions.
- DONE 2026-08-20 (31.5): `ccw doctor`'s new `desync` check surfaces a
  deliberately-desynced folder (JSONL vs. manifest `source_hash`, the check
  that found the real one) among the 25 most recently captured, without
  requiring a full `ccw archive --verify` run - `tests/test_doctor.py`, both
  the CLI-level catch and the in-process scope-boundary proof.

## Contract excerpts

R1 (content-hash identity, not filesystem metadata) - directly load-bearing
for 31.3's open question. R5/R10 (never silently do less and say nothing).
R14 (concurrent-write locking discipline) - relevant to 31.4.

## TOUCHES

`src/cc_warehouse/sweep.py`, `capture.py`, `cli.py`, `build.py`, `archive.py`,
`doctor.py`, `catalog.py`, `tests/`.

## Process

Standard loop for the code. 31.1 can ship alone, first, ahead of everything
else - it is independent and zero-risk. 31.4's retry design is blocked on
confirming the actual exception first (see 31.4). No destructive or
irreversible step in this ticket; nothing here needs the principal's word at
the moment of running, unlike ticket 27.
