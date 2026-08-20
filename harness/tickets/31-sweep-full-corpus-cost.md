# Ticket 31: sweep's full-corpus cost, and the resilience gap it exposed

Opened 2026-08-20, from `contract/PROPOSALS/daily-sweep-full-corpus-cost.md` -
a proposal filed the same day by an assistant session that started from one
broken session folder the operator handed over (`CaptainCodeAU-win_go_app_test/
20260820-093714+1000_b087d6a2-...`) and traced the investigation outward into
the daily `ccw sweep` job. Full evidence, numbers, and reasoning live in that
proposal; this ticket is the work-order.

**NOT STARTED.**

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

### 31.3  Give `sweep()`'s own walk a cheap pre-check before the read+hash

The biggest single win (34-44 minutes measured today for the walk alone) and
the one part of this ticket with no existing shipped pattern to copy
directly - `sweep.py` `_walk_source()` + `capture.capture_transcript()` walk
every `.jsonl` under `~/.claude/projects` and fully read+hash every one of
them before any skip decision can be made.

Open design question, not decided by the proposal: what's the cheapest signal
that's still trustworthy enough for this project's own R1 (identity is
content-hash, not filesystem metadata)? Two honest options, not a false
choice - pick one, or something better, and say why:

- A new side-table (source path, mtime, size, last-known hash) checked before
  the read. Fast, but mtime/size is a *proxy* for content, not content itself.
- Reduce the cost *per skip* instead of avoiding the read: batch or drop
  per-item `capture_event` logging for `skipped_unchanged` outcomes, so the
  read+hash still happens but the ~17,000 individual `BEGIN IMMEDIATE`/
  `COMMIT` transactions collapse into far fewer. Simpler, smaller diff, does
  not fully solve the wall-clock cost but directly reduces the database write
  pressure implicated in 31.4/31.5.

Whichever is chosen, write the oracle test for "sweep run twice with nothing
changed between them is a true no-op below the skip line" before
implementing, per this project's own stated methodology.

### 31.4  Retry-with-backoff on catalog lock contention in `_capture_locked`

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

### 31.5  Wire a cheap desync check into `ccw doctor`

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
- A simulated `sqlite3.OperationalError` during the catalog-write phase of
  `_capture_locked`, *after* the JSONL write has already succeeded, is
  retried rather than silently aborting the whole capture (31.4) - contingent
  on 31.4's open question being resolved first.
- `ccw doctor`'s new check surfaces a deliberately-desynced folder (JSONL
  newer than its manifest) without requiring a full `ccw archive --verify`
  run (31.5).

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
